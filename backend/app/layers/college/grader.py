"""Phase 9 helpers: AI grading payload validation for college layer."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List


def parse_tolerant_json(raw_text: str) -> Dict[str, Any]:
    """Parse tolerant JSON object from LLM output."""
    text = (raw_text or "").strip()
    if not text:
        return {}

    candidates = [text]
    for m in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE):
        block = (m.group(1) or "").strip()
        if block:
            candidates.append(block)

    obj = re.search(r"\{[\s\S]*\}", text)
    if obj:
        candidates.append(obj.group(0).strip())

    for c in candidates:
        try:
            parsed = json.loads(c)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue
    return {}


def validate_question_grade(
    question_id: int,
    max_marks: float,
    grade_payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Validate and clamp AI grade payload for one question."""
    marks = float(grade_payload.get("marks", 0.0) or 0.0)
    max_marks_val = float(max_marks or 0.0)
    if max_marks_val <= 0:
        max_marks_val = 1.0
    marks = min(max_marks_val, max(0.0, marks))

    return {
        "question_id": int(question_id),
        "marks": round(marks, 4),
        "feedback": str(grade_payload.get("feedback", "") or ""),
        "annotations": grade_payload.get("annotations", []) if isinstance(grade_payload.get("annotations"), list) else [],
        "confidence": float(grade_payload.get("confidence", 0.0) or 0.0),
    }


def validate_grading_response(
    expected_questions: List[Dict[str, Any]],
    llm_response_text: str,
) -> List[Dict[str, Any]]:
    """Validate full response schema and return normalized per-question grades."""
    parsed = parse_tolerant_json(llm_response_text)
    raw_rows = parsed.get("grades") if isinstance(parsed.get("grades"), list) else []

    by_q = {}
    for row in raw_rows:
        try:
            qid = int(row.get("question_id"))
        except Exception:
            continue
        by_q[qid] = row

    out: List[Dict[str, Any]] = []
    for q in expected_questions or []:
        qid = int(q.get("question_id") or 0)
        row = by_q.get(qid) or {}
        out.append(validate_question_grade(qid, float(q.get("marks") or 0.0), row))
    return out


__all__ = ["parse_tolerant_json", "validate_question_grade", "validate_grading_response"]
