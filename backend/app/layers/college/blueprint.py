"""Phase 1: robust blueprint extraction/health helpers for college V2."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import fitz

from app.config import logger
from app.services.answer_sheet_pipeline import (
    build_question_blueprint_from_exam_questions,
    build_question_blueprint_from_pdf,
)
from app.utils.blueprint import compute_blueprint_health, derive_expected_question_count


SECTION_MARKERS = (
    "section a",
    "section b",
    "section c",
    "part a",
    "part b",
    "part c",
    "option i",
    "option ii",
)


def repair_json_payload(raw_text: str) -> List[Dict[str, Any]]:
    """Parse imperfect JSON payloads and return list rows where possible."""
    text = (raw_text or "").strip()
    if not text:
        return []

    candidates: List[str] = [text]
    for m in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE):
        block = (m.group(1) or "").strip()
        if block:
            candidates.append(block)

    arr_match = re.search(r"\[[\s\S]*\]", text)
    if arr_match:
        candidates.append(arr_match.group(0).strip())

    obj_match = re.search(r"\{\s*\"questions\"[\s\S]*\}", text)
    if obj_match:
        candidates.append(obj_match.group(0).strip())

    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, list):
            return [row for row in parsed if isinstance(row, dict)]
        if isinstance(parsed, dict) and isinstance(parsed.get("questions"), list):
            return [row for row in parsed.get("questions") if isinstance(row, dict)]
    return []


def extract_question_numbers_regex(raw_text: str) -> List[int]:
    matches = re.findall(r"(?:^|\n|\s)(?:q\.?\s*)?(\d{1,3})(?:[\).:]|\s)", raw_text or "", re.IGNORECASE)
    nums = sorted({int(m) for m in matches if m.isdigit() and int(m) > 0})
    return nums


def _count_sections(rows: List[Dict[str, Any]]) -> int:
    seen = set()
    for row in rows or []:
        text = f"{row.get('question_text', '')} {row.get('rubric', '')}".lower()
        for marker in SECTION_MARKERS:
            if marker in text:
                seen.add(marker)
    return len(seen)


def _build_pdf_page_index(pdf_bytes: bytes) -> Dict[int, List[int]]:
    """Map question numbers to page numbers using regex on PDF text."""
    out: Dict[int, List[int]] = {}
    if not pdf_bytes:
        return out
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            nums = extract_question_numbers_regex(text)
            for n in nums:
                out.setdefault(int(n), []).append(i)
        doc.close()
    except Exception as exc:
        logger.warning("[COLLEGE-V2] Failed to build PDF page index: %s", exc)
    return out


def _localize_missing_ranges(missing_numbers: List[int], page_index: Dict[int, List[int]]) -> List[Tuple[int, int]]:
    pages: List[int] = []
    for qn in missing_numbers or []:
        pages.extend(page_index.get(int(qn), []))
    if not pages:
        return []
    pages = sorted(set(int(p) for p in pages))

    ranges: List[Tuple[int, int]] = []
    start = pages[0]
    prev = pages[0]
    for page in pages[1:]:
        if page == prev + 1:
            prev = page
            continue
        ranges.append((start, prev))
        start = page
        prev = page
    ranges.append((start, prev))
    return ranges


def _enrich_blueprint_from_pdf(
    exam_blueprint: List[Dict[str, Any]],
    question_paper_pdf_bytes: Optional[bytes],
) -> List[Dict[str, Any]]:
    """Optionally enrich rubric/type fields from question-paper PDF extraction."""
    if not exam_blueprint:
        return exam_blueprint
    allow_enrich = os.getenv("ANSWER_PACKET_ALLOW_PDF_ENRICH", "false").lower() in ("1", "true", "yes", "on")
    if not allow_enrich or not question_paper_pdf_bytes:
        return exam_blueprint

    pdf_blueprint = build_question_blueprint_from_pdf(question_paper_pdf_bytes)
    if not pdf_blueprint:
        return exam_blueprint

    exam_by_q = {int(q["question_id"]): q for q in exam_blueprint if q.get("question_id") is not None}
    pdf_by_q = {int(q["question_id"]): q for q in pdf_blueprint if q.get("question_id") is not None}

    merged: List[Dict[str, Any]] = []
    for qid in sorted(exam_by_q.keys()):
        q_exam = exam_by_q[qid]
        q_pdf = pdf_by_q.get(qid) or {}
        merged.append(
            {
                **q_exam,
                "question_text": q_exam.get("question_text") or q_pdf.get("question_text", ""),
                "rubric": q_exam.get("rubric") or q_pdf.get("rubric", ""),
                "type": q_exam.get("type") or q_pdf.get("type", "theory"),
                "expected_components": q_exam.get("expected_components") or q_pdf.get("expected_components", []),
            }
        )

    dropped_qids = sorted(set(pdf_by_q.keys()) - set(exam_by_q.keys()))
    if dropped_qids:
        logger.warning(
            "[COLLEGE-V2] Ignoring PDF-only question IDs not present in exam blueprint: %s",
            dropped_qids[:20],
        )
    return merged


def assemble_blueprint(
    exam_questions: List[Dict[str, Any]],
    question_paper_pdf_bytes: Optional[bytes] = None,
    failed_chunks: Optional[List[Dict[str, Any]]] = None,
    completeness_threshold: float = 0.92,
) -> Dict[str, Any]:
    """Create robust question blueprint + health with recovery diagnostics."""
    exam_questions = exam_questions or []
    base_blueprint = build_question_blueprint_from_exam_questions(exam_questions)
    question_blueprint = _enrich_blueprint_from_pdf(base_blueprint, question_paper_pdf_bytes)

    expected_count = derive_expected_question_count({"questions": exam_questions}, fallback_questions=exam_questions)
    health = compute_blueprint_health(exam_questions, expected_count=expected_count)

    parsed_numbers = list(health.get("parsed_numbers", []) or [])
    numbering_contiguous = bool(parsed_numbers) and parsed_numbers == list(range(parsed_numbers[0], parsed_numbers[-1] + 1))
    sections_detected = _count_sections(question_blueprint)

    failed_chunks_list = list(failed_chunks or [])
    page_index = _build_pdf_page_index(question_paper_pdf_bytes) if question_paper_pdf_bytes else {}

    # If numbering has gaps, provide localized recovery targets (max 2 passes/ranges).
    missing_numbers = list(health.get("missing", []) or [])
    localized_ranges = _localize_missing_ranges(missing_numbers, page_index)
    localized_ranges = localized_ranges[:2]

    if missing_numbers and localized_ranges:
        for (start_page, end_page) in localized_ranges:
            failed_chunks_list.append(
                {
                    "type": "targeted_reextract",
                    "page_start": int(start_page),
                    "page_end": int(end_page),
                    "reason": f"missing_question_numbers:{missing_numbers[:20]}",
                }
            )

    completeness_score = float(health.get("completeness_score", 0.0) or 0.0)
    is_complete = bool(health.get("is_complete")) and numbering_contiguous and completeness_score >= completeness_threshold

    health.update(
        {
            "numbering_contiguous": numbering_contiguous,
            "sections_detected": int(sections_detected),
            "failed_chunks": failed_chunks_list,
            "is_complete": bool(is_complete),
        }
    )

    blockers: List[str] = []
    if not numbering_contiguous:
        blockers.append("numbering_not_contiguous")
    if completeness_score < completeness_threshold:
        blockers.append(f"completeness_score_below_threshold:{completeness_score:.3f}<{completeness_threshold:.3f}")
    if missing_numbers:
        blockers.append(f"missing_questions:{','.join(str(n) for n in missing_numbers[:25])}")
    if health.get("duplicates"):
        blockers.append(f"duplicate_questions:{','.join(str(n) for n in (health.get('duplicates') or [])[:25])}")

    return {
        "question_blueprint": question_blueprint,
        "blueprint_health": health,
        "can_lock": len(blockers) == 0,
        "blockers": blockers,
        "diagnostics": {
            "expected_count": expected_count,
            "localized_missing_ranges": localized_ranges,
            "missing_numbers": missing_numbers,
        },
    }


__all__ = [
    "assemble_blueprint",
    "repair_json_payload",
    "extract_question_numbers_regex",
]
