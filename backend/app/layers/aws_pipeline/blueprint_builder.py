"""Blueprint builder for AWS Textract pipeline (resilient, span-evidence)."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.config import get_llm_api_key, logger
from app.services.llm import LlmChat, UserMessage
from app.utils.blueprint import compute_blueprint_health

from .question_identity import generate_question_uuid


def _parse_first_json_object(raw_text: str) -> Optional[str]:
    if not raw_text:
        return None
    start = raw_text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(raw_text)):
        ch = raw_text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return raw_text[start:i + 1]
    return None


def _parse_payload(raw_text: str) -> Optional[Dict[str, Any]]:
    if not raw_text:
        return None
    raw = (raw_text or "").strip()
    candidates: List[str] = [raw]
    for m in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE):
        block = (m.group(1) or "").strip()
        if block:
            candidates.append(block)
    first_obj = _parse_first_json_object(raw)
    if first_obj:
        candidates.append(first_obj)
    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _to_float(value: Any) -> Optional[float]:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except Exception:
        match = re.search(r"(\d+(?:\.\d+)?)", str(value))
        if match:
            try:
                return float(match.group(1))
            except Exception:
                return None
        return None


def _detect_optional_group(text: str) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    t = (text or "").lower()
    if re.search(r"\battempt any\s+\d+\s+out of\s+\d+\b", t):
        return f"group_{uuid.uuid4().hex[:6]}", None, None
    return None, None, None


def _clean_question_line(text: str) -> str:
    if not text:
        return ""
    out = str(text).strip()
    out = re.sub(r"^\s*(?:Q\.?\s*)?\d+\s*[\).]?\s*", "", out, flags=re.IGNORECASE)
    return out.strip()


def _extract_stem_text(span: Dict[str, Any], default_text: str) -> str:
    lines = span.get("lines") or []
    for line in lines[:8]:
        text = _clean_question_line(line.get("text", ""))
        if len(text) < 8:
            continue
        if re.search(r"\b\d+\s*[xX*]\s*\d+\s*=\s*\d+\b", text):
            continue
        if re.search(r"\bmarks?\b", text, re.IGNORECASE):
            continue
        if re.search(r"\bdirected\b", text, re.IGNORECASE):
            continue
        if text.lower().startswith("section"):
            continue
        if text.lower().startswith("read the text given below"):
            continue
        return text[:240]
    return (default_text or "").strip()[:240]


def _mark_candidates(lines: List[Dict[str, Any]], max_value: float = 200.0) -> List[float]:
    candidates: List[float] = []
    for line in lines:
        text = (line.get("text") or "").strip()
        if not text:
            continue
        mul = re.search(r"(\d{1,2})\s*[xX*]\s*(\d{1,2})\s*=\s*(\d{1,3})", text)
        if mul:
            total = _to_float(mul.group(3))
            if total and 0 < total <= max_value:
                candidates.append(total)
            continue
        marks = re.search(r"\b(\d{1,2})\s*marks?\b", text, re.IGNORECASE)
        if marks:
            value = _to_float(marks.group(1))
            if value and 0 < value <= max_value:
                candidates.append(value)
            continue
        right_num = re.fullmatch(r"\s*(\d{1,2})\s*", text)
        left = float((line.get("bbox") or {}).get("left", 0.0))
        if right_num and left >= 0.75:
            value = _to_float(right_num.group(1))
            if value and 0 < value <= max_value:
                candidates.append(value)
    return candidates


def _pick_stable_mark(values: List[float]) -> Optional[float]:
    if not values:
        return None
    freq: Dict[float, int] = {}
    for value in values:
        v = float(value)
        freq[v] = freq.get(v, 0) + 1
    ranked = sorted(freq.items(), key=lambda item: (-item[1], item[0]))
    return ranked[0][0] if ranked else None


def _derive_subquestions_from_span(span: Dict[str, Any]) -> List[Dict[str, Any]]:
    sub_questions: List[Dict[str, Any]] = []
    span_choices = span.get("span_graph", {}).get("choices") or span.get("choices") or []
    span_subparts = span.get("span_graph", {}).get("subparts") or span.get("subparts") or []

    if span_choices:
        for choice in span_choices:
            choice_id = str(choice.get("choice_id") or f"choice_{len(sub_questions)+1}")
            choice_lines = choice.get("lines") or []
            choice_text = str(choice.get("text") or "").strip()
            mark = _pick_stable_mark(_mark_candidates(choice_lines, max_value=10.0))
            nested_subparts = choice.get("subparts") or []
            if nested_subparts:
                nested_marks: List[float] = []
                for nested in nested_subparts:
                    nested_mark = _pick_stable_mark(_mark_candidates(nested.get("lines") or [], max_value=6.0))
                    if nested_mark:
                        nested_marks.append(float(nested_mark))
                if nested_marks:
                    mark = float(sum(nested_marks))
            sub_questions.append(
                {
                    "sub_id": choice_id,
                    "max_marks": mark,
                    "rubric": choice_text[:400] if choice_text else f"Option {choice_id}",
                }
            )
        return sub_questions

    for subpart in span_subparts:
        sid = str(subpart.get("sub_id") or "").strip()
        if not sid:
            continue
        part_lines = subpart.get("lines") or []
        mark = _pick_stable_mark(_mark_candidates(part_lines, max_value=10.0))
        sub_questions.append(
            {
                "sub_id": sid,
                "max_marks": mark,
                "rubric": str(subpart.get("text") or "").strip()[:400] or f"Part ({sid})",
            }
        )
    return sub_questions


def _extract_multiplicative_pattern(text: str) -> Optional[Tuple[int, float, float]]:
    if not text:
        return None
    match = re.search(r"\b(\d{1,2})\s*[xX*]\s*(\d{1,2})\s*=\s*(\d{1,3})\b", text)
    if not match:
        return None
    count = int(match.group(1))
    per_mark = float(match.group(2))
    total = float(match.group(3))
    return count, per_mark, total


def _derive_question_marks(span: Dict[str, Any], ai_marks: Optional[float], sub_questions: List[Dict[str, Any]]) -> Optional[float]:
    span_lines = span.get("lines") or []
    span_text = "\n".join((p.get("text", "") for p in span.get("raw_text_by_page") or []))
    candidates = _mark_candidates(span_lines[:80])
    direct_mark = _pick_stable_mark(candidates)

    sub_marks = [float(sq.get("max_marks")) for sq in sub_questions if sq.get("max_marks") not in (None, "")]
    any_one = bool(
        re.search(r"\b(any one|attempt any one|choose any one)\b", span_text, re.IGNORECASE)
    )
    has_choices = bool(span.get("span_graph", {}).get("choices") or span.get("choices"))

    if sub_marks:
        sum_marks = sum(sub_marks)
        if has_choices:
            return max(sub_marks)
        if any_one:
            return max(sub_marks)
        if direct_mark and direct_mark > 0 and abs(sum_marks - direct_mark) <= 2:
            return direct_mark
        return sum_marks

    if direct_mark and direct_mark > 0:
        return direct_mark

    return ai_marks


def build_spans(
    anchors: List[Dict[str, Any]],
    line_positions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Build global spans from anchor candidates; spans may cross pages."""
    anchors_sorted = sorted(
        [a for a in anchors if a.get("anchor_level") == "question"],
        key=lambda a: (a.get("page_index", 0), (a.get("bbox") or {}).get("top", 0.0)),
    )

    if not anchors_sorted:
        # No anchors => single fallback span covering all text.
        lines_sorted = sorted(
            line_positions,
            key=lambda l: (l.get("page", 0), (l.get("bbox") or {}).get("top", 0.0)),
        )
        raw_text = "\n".join([l.get("text", "") for l in lines_sorted]).strip()
        preview = raw_text[:300]
        return [
            {
                "span_id": "span_fallback",
                "question_number": None,
                "anchor_level": "question",
                "anchor_text": "fallback",
                "anchor_bbox": None,
                "page_numbers": sorted({l.get("page") for l in lines_sorted if l.get("page")}),
                "raw_text_by_page": [{"page": l.get("page"), "text": l.get("text", "")} for l in lines_sorted],
                "preview_text": preview,
                "anchor_confidence": 0.2,
                "span_length": len(raw_text),
            }
        ]

    spans: List[Dict[str, Any]] = []
    lines_sorted = sorted(
        line_positions,
        key=lambda l: (l.get("page", 0), (l.get("bbox") or {}).get("top", 0.0)),
    )

    def _extract_first_qnum(text: str) -> Optional[str]:
        if not text:
            return None
        patterns = [
            re.compile(r"\\bQ\\s*(\\d+)", re.IGNORECASE),
            re.compile(r"\\bQuestion\\s*(\\d+)", re.IGNORECASE),
            re.compile(r"^\\s*(\\d+)\\s*[\\.)]", re.MULTILINE),
        ]
        for pat in patterns:
            m = pat.search(text)
            if m:
                return m.group(1)
        return None

    # Add preface span if there is content before first anchor (common for Q1)
    first_anchor = anchors_sorted[0]
    first_page = first_anchor.get("page_index")
    first_top = (first_anchor.get("bbox") or {}).get("top", 0.0)
    pre_lines: List[Dict[str, Any]] = []
    for line in lines_sorted:
        page = line.get("page")
        top = (line.get("bbox") or {}).get("top", 0.0)
        if page is None:
            continue
        if page < first_page or (page == first_page and top < first_top):
            pre_lines.append(line)
    if pre_lines:
        pre_text = "\\n".join([l.get("text", "") for l in pre_lines]).strip()
        pre_page_numbers = sorted({l.get("page") for l in pre_lines if l.get("page")})
        pre_qnum = _extract_first_qnum(pre_text)
        spans.append(
            {
                "span_id": "span_preface",
                "question_number": pre_qnum,
                "anchor_level": "question",
                "anchor_text": "preface",
                "anchor_bbox": None,
                "page_numbers": pre_page_numbers,
                "raw_text_by_page": [{"page": l.get("page"), "text": l.get("text", "")} for l in pre_lines],
                "preview_text": pre_text[:300],
                "anchor_confidence": 0.2,
                "span_length": len(pre_text),
                "next_anchor_text": first_anchor.get("text_snippet"),
            }
        )

    for idx, anchor in enumerate(anchors_sorted):
        next_anchor = anchors_sorted[idx + 1] if idx + 1 < len(anchors_sorted) else None
        start_page = anchor.get("page_index")
        start_top = (anchor.get("bbox") or {}).get("top", 0.0)
        end_page = next_anchor.get("page_index") if next_anchor else None
        end_top = (next_anchor.get("bbox") or {}).get("top", 1.1) if next_anchor else None

        span_lines: List[Dict[str, Any]] = []
        for line in lines_sorted:
            page = line.get("page")
            top = (line.get("bbox") or {}).get("top", 0.0)
            if page is None:
                continue
            if page < start_page:
                continue
            if end_page is not None and page > end_page:
                continue
            if page == start_page and top < start_top:
                continue
            if end_page is not None and page == end_page and top >= end_top:
                continue
            span_lines.append(line)

        raw_text = "\n".join([l.get("text", "") for l in span_lines]).strip()
        page_numbers = sorted({l.get("page") for l in span_lines if l.get("page")})
        preview_text = raw_text[:300]

        spans.append(
            {
                "span_id": f"span_{idx+1}",
                "question_number": anchor.get("question_number"),
                "anchor_level": "question",
                "anchor_text": anchor.get("text_snippet") or "",
                "anchor_bbox": anchor.get("bbox"),
                "page_numbers": page_numbers,
                "raw_text_by_page": [{"page": l.get("page"), "text": l.get("text", "")} for l in span_lines],
                "preview_text": preview_text,
                "anchor_confidence": anchor.get("confidence", 0.6),
                "span_length": len(raw_text),
                "next_anchor_text": (next_anchor.get("text_snippet") if next_anchor else None),
            }
        )

    return spans


def _span_evidence(span: Dict[str, Any]) -> Dict[str, Any]:
    lines = span.get("raw_text_by_page") or []
    line_count = max(1, len(lines))
    avg_line_height = None
    density = float(line_count)
    table_presence = False
    return {
        "anchor_bbox": span.get("anchor_bbox"),
        "anchor_text": span.get("anchor_text"),
        "next_anchor_text": span.get("next_anchor_text"),
        "page_range": span.get("page_numbers"),
        "layout_features": {
            "avg_line_height": avg_line_height,
            "density": density,
            "table_presence": table_presence,
        },
        "span_confidence": span.get("anchor_confidence", 0.5),
    }


def _build_numbering_diagnostics(questions: List[Dict[str, Any]]) -> Dict[str, Any]:
    nums = []
    for q in questions:
        raw = q.get("question_number")
        if raw is None:
            continue
        try:
            nums.append(int(raw))
        except Exception:
            continue
    nums_sorted = sorted(nums)
    duplicates = sorted({n for n in nums_sorted if nums_sorted.count(n) > 1})
    numbering_gaps: List[int] = []
    if nums_sorted:
        expected = list(range(nums_sorted[0], nums_sorted[-1] + 1))
        numbering_gaps = sorted(set(expected) - set(nums_sorted))
    return {
        "numbering_gaps": numbering_gaps,
        "duplicate_numbers": duplicates,
        "probable_optional_groups": [],
    }


async def build_blueprint_from_spans(spans: List[Dict[str, Any]]) -> Dict[str, Any]:
    api_key = get_llm_api_key()
    if not api_key:
        logger.warning("[AWS] GEMINI_API_KEY missing; blueprint structuring will be degraded.")

    questions: List[Dict[str, Any]] = []
    span_structuring_errors: List[Dict[str, Any]] = []
    blueprint_spans_structured: List[Dict[str, Any]] = []

    for idx, span in enumerate(spans):
        if span.get("span_type") == "non_question" or span.get("anchor_type") == "preface":
            continue

        span_text = "\n".join((p.get("text", "") for p in span.get("raw_text_by_page") or []))
        span_text = (span_text or "").strip()
        anchor_text = span.get("anchor_text") or ""
        page_nums = span.get("page_numbers") or []
        page_num = int(page_nums[0]) if page_nums else 1
        question_uuid = generate_question_uuid(anchor_text, page_num, span.get("preview_text") or "")
        logger.info("QUESTION_UUID_ASSIGNED span_id=%s uuid=%s", span.get("span_id"), question_uuid)

        span_question_number = span.get("question_number") or f"unknown_{idx+1}"
        span_subparts = span.get("span_graph", {}).get("subparts") or span.get("subparts") or []
        span_choices = span.get("span_graph", {}).get("choices") or span.get("choices") or []
        span_graph_summary = {
            "question_number": span_question_number,
            "subparts": [{"sub_id": sp.get("sub_id"), "kind": sp.get("kind")} for sp in span_subparts],
            "choices": [{"choice_id": ch.get("choice_id")} for ch in span_choices],
        }

        prompt = f"""Extract blueprint for exactly ONE question span. If unsure, return best partial structure. Never return empty. Always output a fallback.

Use the deterministic span graph below. Do NOT invent new questions, subparts, or choices.
Span graph:
{json.dumps(span_graph_summary, ensure_ascii=False)}

Question span OCR text (for rubric only):
{span_text}

Return ONLY JSON:
{{
  "question_number": "{span_question_number}",
  "marks": null,
  "question_text": "",
  "rubric": "",
  "type": "descriptive",
  "subparts": [],
  "is_optional": false,
  "optional_group_id": null,
  "group_size": null,
  "choose_k": null
}}"""

        payload: Optional[Dict[str, Any]] = None
        response_text = ""
        for attempt in range(4):
            try:
                chat = LlmChat(
                    api_key=api_key or "",
                    session_id=f"aws_bp_{uuid.uuid4().hex[:8]}",
                    system_message="Return a single JSON object. No prose.",
                ).with_model("gemini", "gemini-2.5-flash").with_params(
                    temperature=0,
                    response_mime_type="application/json",
                )
                response = await chat.send_message(UserMessage(text=prompt))
                response_text = response or ""
                payload = _parse_payload(response_text)
                if payload:
                    break
            except Exception as e:
                span_structuring_errors.append({"span_id": span.get("span_id"), "error": str(e)})

        if not payload:
            deterministic_sub_questions = _derive_subquestions_from_span(span)
            deterministic_marks = _derive_question_marks(span, None, deterministic_sub_questions)
            # fallback span object
            questions.append(
                {
                    "question_uuid": question_uuid,
                    "question_number": span_question_number,
                    "max_marks": deterministic_marks,
                    "question_text": _extract_stem_text(span, span_text.splitlines()[0] if span_text else ""),
                    "rubric": span_text,
                    "type": "descriptive",
                    "sub_questions": deterministic_sub_questions,
                    "is_optional": False,
                    "optional_group": None,
                    "required_count": None,
                    "group_size": None,
                    "source": "fallback_span",
                    "source_span_id": span.get("span_id"),
                    "source_anchor_text": anchor_text,
                    "source_page_range": span.get("page_numbers"),
                }
            )
            logger.info("SPAN_FALLBACK_USED span_id=%s", span.get("span_id"))
            continue

        marks = _to_float(payload.get("marks"))
        sub_questions: List[Dict[str, Any]] = _derive_subquestions_from_span(span)

        # Fallback to AI subparts only when deterministic segmentation produced none.
        if not sub_questions:
            payload_subparts = payload.get("subparts") or []
            if isinstance(payload_subparts, list):
                for sp in payload_subparts:
                    if not isinstance(sp, dict):
                        continue
                    sid = str(sp.get("sub_id") or "").strip()
                    if not sid:
                        continue
                    sub_questions.append(
                        {
                            "sub_id": sid,
                            "max_marks": _to_float(sp.get("marks")),
                            "rubric": str(sp.get("text") or "").strip() or f"Part ({sid})",
                        }
                    )

        marks = _derive_question_marks(span, marks, sub_questions)
        mul_pattern = _extract_multiplicative_pattern(span_text)
        if mul_pattern and sub_questions:
            _, per_mark, total_mark = mul_pattern
            for sq in sub_questions:
                if sq.get("max_marks") in (None, "", 0):
                    sq["max_marks"] = per_mark
            if marks in (None, "", 0):
                marks = total_mark

        # Optional groups are deterministic-only. Ignore AI optional fields.
        opt_group_id = None
        group_size = None
        choose_k = None
        if not span_choices:
            opt_group_id, group_size, choose_k = _detect_optional_group(span_text)

        question_text_fallback = _extract_stem_text(span, span_text.splitlines()[0] if span_text else f"Question {idx+1}")
        payload_question_text = str(payload.get("question_text") or "").strip()
        if len(_clean_question_line(payload_question_text)) < 8:
            payload_question_text = ""

        questions.append(
            {
                "question_uuid": question_uuid,
                "question_number": span_question_number,
                "max_marks": marks,
                "question_text": payload_question_text or question_text_fallback,
                "rubric": str(payload.get("rubric") or "").strip() or span_text or f"Question {idx+1}",
                "type": str(payload.get("type") or "descriptive"),
                "sub_questions": sub_questions,
                "is_optional": bool(opt_group_id),
                "optional_group": opt_group_id,
                "required_count": choose_k,
                "group_size": group_size,
                "source": "structured",
                "source_span_id": span.get("span_id"),
                "source_anchor_text": anchor_text,
                "source_page_range": span.get("page_numbers"),
            }
        )

        blueprint_spans_structured.append({"span_id": span.get("span_id"), "question_uuid": question_uuid})

    numbering_diag = _build_numbering_diagnostics(questions)
    if numbering_diag.get("numbering_gaps"):
        logger.info("NUMBERING_GAP_DETECTED gaps=%s", numbering_diag.get("numbering_gaps"))
    health = compute_blueprint_health(questions)

    return {
        "questions": questions,
        "blueprint_spans_structured": blueprint_spans_structured,
        "numbering_gaps": numbering_diag.get("numbering_gaps", []),
        "duplicate_numbers": numbering_diag.get("duplicate_numbers", []),
        "probable_optional_groups": numbering_diag.get("probable_optional_groups", []),
        "blueprint_health": health,
        "span_structuring_errors": span_structuring_errors,
    }


def build_span_evidence(spans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            **span,
            "span_evidence": _span_evidence(span),
        }
        for span in spans
    ]
