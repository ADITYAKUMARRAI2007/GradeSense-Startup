"""Visual answer alignment against structured blueprint."""

from __future__ import annotations

import json
import re
import uuid
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

from app.config import get_llm_api_key, logger
from app.services.llm import ImageContent, LlmChat, UserMessage
from app.utils.ocr_provider import get_ocr_provider

from .cache import get_alignment_cache, set_alignment_cache
from .prompts import build_alignment_prompt


ALIGNMENT_COVERAGE_GATE = 0.7


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _parse_json_object(raw_text: str) -> Dict[str, Any]:
    if not raw_text:
        raise ValueError("empty_alignment_response")

    candidates = [raw_text.strip()]
    for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", raw_text, flags=re.IGNORECASE):
        block = (match.group(1) or "").strip()
        if block:
            candidates.append(block)

    for candidate in candidates:
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("invalid_alignment_json")


def _extract_option_letter(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"\b([A-D])\b", text.strip().upper())
    if m:
        return m.group(1)
    m = re.search(r"\(([A-D])\)", text.strip().upper())
    return m.group(1) if m else None


def _is_objective_question(question: Dict[str, Any]) -> bool:
    qtype = str(question.get("question_type") or "").strip().lower()
    return qtype in {"mcq", "fill_blank"}


def _extract_objective_from_ocr(
    question_structure: Dict[str, Any],
    answer_images: List[str],
) -> Dict[int, Dict[str, Any]]:
    """Extract objective answers (MCQ/fill-blank) from OCR lines as a fallback."""
    objective_qns = {
        int(q.get("number"))
        for q in (question_structure.get("questions") or [])
        if str(q.get("number", "")).isdigit() and _is_objective_question(q)
    }
    if not objective_qns:
        return {}

    ocr = get_ocr_provider()
    extracted: Dict[int, Dict[str, Any]] = {}
    pattern = re.compile(r"\b(?:Q\s*)?(\d{1,3})\s*[\).:\-]?\s*\(?\s*([A-D])\s*\)?\b", flags=re.IGNORECASE)

    for page_idx, img in enumerate(answer_images):
        try:
            # Use lenient thresholds for objective answers: we rely on strict pattern matching.
            res = ocr.detect(img, min_conf=0.35, min_words=1, min_lines=1, allow_fallback=False)
            lines = [str(row.get("text") or "").strip() for row in (res.get("lines") or [])]
        except Exception as exc:
            logger.warning("Objective OCR fallback failed page=%s: %s", page_idx + 1, exc)
            lines = []

        for line in lines:
            if not line:
                continue
            for match in pattern.finditer(line):
                try:
                    qn = int(match.group(1))
                except Exception:
                    continue
                if qn not in objective_qns:
                    continue
                letter = str(match.group(2) or "").strip().upper()
                if not letter:
                    continue
                if qn not in extracted:
                    extracted[qn] = {
                        "answer_text": letter,
                        "page_index": page_idx,
                        "confidence": 0.45,
                        "detected_type": "mcq",
                    }
    if extracted:
        logger.info("MCQ_OCR_FALLBACK_FOUND questions=%s", sorted(extracted.keys()))
    return extracted


def _normalize_alignment_answers(payload: Dict[str, Any], expected_numbers: List[int]) -> List[Dict[str, Any]]:
    answers = []
    allowed_types = {"mcq", "written", "blank"}
    expected_set = set(expected_numbers)

    for row in (payload.get("answers") or []):
        if not isinstance(row, dict):
            continue
        try:
            qn = int(row.get("question_number"))
        except Exception:
            continue
        detected_type = str(row.get("detected_type") or "written").strip().lower()
        if detected_type not in allowed_types:
            detected_type = "written"
        ans = {
            "question_number": qn,
            "sub_label": (str(row.get("sub_label") or "").strip() or None),
            "answer_text": str(row.get("answer_text") or "").strip(),
            "detected_type": detected_type,
            "page_index": int(row.get("page_index")) if str(row.get("page_index", "")).isdigit() else None,
            "bbox": row.get("bbox") if isinstance(row.get("bbox"), list) else None,
            "confidence": max(0.0, min(1.0, _to_float(row.get("confidence"), 0.0))),
            "_is_expected": qn in expected_set,
        }
        answers.append(ans)
    return answers


def _compute_alignment_metrics(
    answers: List[Dict[str, Any]],
    expected_numbers: List[int],
    page_count: int,
) -> Dict[str, Any]:
    expected_set = set(expected_numbers)
    key_counter: Counter[Tuple[int, Optional[str]]] = Counter()
    mapped_question_set = set()
    answered_question_set = set()
    used_pages = set()
    unmapped_answers = []

    for ans in answers:
        qn = int(ans.get("question_number", 0) or 0)
        sub_label = (str(ans.get("sub_label") or "").strip().lower() or None)
        key_counter[(qn, sub_label)] += 1

        if ans.get("page_index") is not None:
            used_pages.add(int(ans["page_index"]))

        text = str(ans.get("answer_text") or "").strip()
        is_blank = str(ans.get("detected_type") or "").lower() == "blank" or not text
        if not is_blank:
            answered_question_set.add(qn)

        if qn in expected_set:
            mapped_question_set.add(qn)
        else:
            unmapped_answers.append(ans)

    question_coverage_map = {str(qn): (qn in mapped_question_set) for qn in expected_numbers}
    duplicate_answers = [
        {"question_number": qn, "sub_label": sub, "count": count}
        for (qn, sub), count in key_counter.items()
        if count > 1
    ]

    expected_questions = len(expected_set)
    answered_questions = len({qn for qn in answered_question_set if qn in expected_set})
    mapped_questions = len(mapped_question_set)

    coverage_ratio = (mapped_questions / float(expected_questions)) if expected_questions else 0.0
    alignment_coverage = (mapped_questions / float(answered_questions)) if answered_questions else 0.0

    avg_conf = (
        sum(_to_float(ans.get("confidence"), 0.0) for ans in answers) / float(len(answers))
        if answers
        else 0.0
    )
    duplicate_penalty = min(1.0, len(duplicate_answers) / float(max(1, expected_questions)))
    unmapped_penalty = min(1.0, len(unmapped_answers) / float(max(1, len(answers))))

    alignment_confidence_score = (
        0.45 * coverage_ratio
        + 0.2 * alignment_coverage
        + 0.25 * avg_conf
        + 0.1 * max(0.0, 1.0 - duplicate_penalty)
        - 0.15 * unmapped_penalty
    )
    alignment_confidence_score = max(0.0, min(1.0, alignment_confidence_score))

    orphan_pages = sorted(set(range(page_count)) - used_pages) if page_count > 0 else []

    return {
        "coverage_ratio": round(coverage_ratio, 4),
        "alignment_coverage": round(alignment_coverage, 4),
        "question_coverage_map": question_coverage_map,
        "unmapped_answers": unmapped_answers,
        "duplicate_answers": duplicate_answers,
        "orphan_pages": orphan_pages,
        "alignment_confidence_score": round(alignment_confidence_score, 4),
        "expected_questions": expected_questions,
        "answered_questions": answered_questions,
        "mapped_questions": mapped_questions,
    }


async def _llm_align_answers(
    *,
    question_structure: Dict[str, Any],
    answer_images: List[str],
    model_name: str,
) -> Dict[str, Any]:
    api_key = get_llm_api_key()
    if not api_key:
        raise RuntimeError("missing_gemini_api_key")

    prompt = build_alignment_prompt(question_structure=question_structure)
    chat = LlmChat(
        api_key=api_key,
        session_id=f"ai_struct_align_{uuid.uuid4().hex[:10]}",
        system_message="Return strict JSON only.",
    ).with_model("gemini", model_name).with_params(temperature=0)

    message = UserMessage(
        text=prompt,
        file_contents=[ImageContent(image_base64=img) for img in answer_images],
    )
    raw = await chat.send_message(message)
    return _parse_json_object(raw)


async def _fallback_align_answers(
    *,
    question_structure: Dict[str, Any],
    answer_images: List[str],
) -> Dict[str, Any]:
    expected_numbers = [int(q.get("number")) for q in (question_structure.get("questions") or []) if str(q.get("number", "")).isdigit()]
    expected_set = set(expected_numbers)
    ocr = get_ocr_provider()
    answers: List[Dict[str, Any]] = []
    current_q: Optional[int] = None

    for page_idx, img in enumerate(answer_images):
        try:
            res = ocr.detect(img)
            lines = [str(row.get("text") or "").strip() for row in (res.get("lines") or [])]
        except Exception as exc:
            logger.warning("Alignment OCR fallback failed page=%s: %s", page_idx + 1, exc)
            lines = []

        page_chunks: Dict[int, List[str]] = defaultdict(list)
        for line in lines:
            m = re.match(r"^(?:Q(?:uestion)?\s*)?(\d{1,3})[\).:-]?\s*(.*)$", line, flags=re.IGNORECASE)
            if m:
                qn = int(m.group(1))
                if qn in expected_set:
                    current_q = qn
                text_tail = (m.group(2) or "").strip()
                if current_q and text_tail:
                    page_chunks[current_q].append(text_tail)
                continue
            if current_q and line:
                page_chunks[current_q].append(line)

        for qn, chunk_lines in page_chunks.items():
            answers.append(
                {
                    "question_number": qn,
                    "sub_label": None,
                    "answer_text": "\n".join(chunk_lines).strip(),
                    "detected_type": "written" if chunk_lines else "blank",
                    "page_index": page_idx,
                    "bbox": None,
                    "confidence": 0.35,
                }
            )

    return {"answers": answers}


async def align_answers(
    *,
    submission_id: str,
    question_structure: Dict[str, Any],
    answer_images: List[str],
    blueprint_signature: str,
    model_name: str = "gemini-2.5-flash",
    use_cache: bool = True,
) -> Dict[str, Any]:
    expected_numbers = sorted(
        {
            int(q.get("number"))
            for q in (question_structure.get("questions") or [])
            if str(q.get("number", "")).isdigit()
        }
    )

    if use_cache:
        cached = get_alignment_cache(submission_id, blueprint_signature)
        if cached:
            return cached

    try:
        payload = await _llm_align_answers(
            question_structure=question_structure,
            answer_images=answer_images,
            model_name=model_name,
        )
    except Exception as exc:
        logger.warning("ALIGNMENT_LLM_FAILED submission=%s fallback=%s", submission_id, exc)
        payload = await _fallback_align_answers(
            question_structure=question_structure,
            answer_images=answer_images,
        )

    answers = _normalize_alignment_answers(payload, expected_numbers)

    # Objective fallback: if LLM alignment misses a clear MCQ answer, use OCR extraction.
    objective_fallback = _extract_objective_from_ocr(question_structure, answer_images)
    if objective_fallback:
        by_qn: Dict[int, Dict[str, Any]] = {}
        for ans in answers:
            try:
                qn = int(ans.get("question_number"))
            except Exception:
                continue
            if qn not in by_qn:
                by_qn[qn] = ans

        expected_set = set(expected_numbers)
        for qn, fallback in objective_fallback.items():
            existing = by_qn.get(qn)
            if existing:
                existing_text = str(existing.get("answer_text") or "").strip()
                if not existing_text or not _extract_option_letter(existing_text):
                    existing["answer_text"] = fallback.get("answer_text")
                    existing["detected_type"] = fallback.get("detected_type", existing.get("detected_type"))
                    existing["page_index"] = fallback.get("page_index", existing.get("page_index"))
                    existing["confidence"] = max(
                        float(existing.get("confidence") or 0.0),
                        float(fallback.get("confidence") or 0.0),
                    )
                    logger.info("MCQ_OCR_FALLBACK_APPLIED question=%s page=%s", qn, existing.get("page_index"))
            else:
                answers.append(
                    {
                        "question_number": qn,
                        "sub_label": None,
                        "answer_text": fallback.get("answer_text"),
                        "detected_type": fallback.get("detected_type", "mcq"),
                        "page_index": fallback.get("page_index"),
                        "bbox": None,
                        "confidence": float(fallback.get("confidence") or 0.0),
                        "_is_expected": qn in expected_set,
                    }
                )
    metrics = _compute_alignment_metrics(answers, expected_numbers, page_count=len(answer_images))

    result = {
        "answers": answers,
        **metrics,
    }

    if use_cache:
        set_alignment_cache(submission_id, blueprint_signature, result)

    return result


__all__ = ["ALIGNMENT_COVERAGE_GATE", "align_answers"]
