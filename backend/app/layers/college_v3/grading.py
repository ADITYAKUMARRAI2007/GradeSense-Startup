"""CBSE-style grading helpers for college_v3."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional


def build_cbse_prompt(question: Dict[str, Any], answer_payload: Dict[str, Any]) -> str:
    q_num = question.get("question_number")
    max_marks = question.get("max_marks") or question.get("total_marks") or 0
    rubric = question.get("rubric") or question.get("question_text") or ""
    answer_text = answer_payload.get("combined_text") or ""
    page_refs = answer_payload.get("page_refs") or []
    return (
        "You are grading CBSE-style answers. Return strict JSON only.\n\n"
        f"Question {q_num} (max {max_marks}):\n{rubric}\n\n"
        f"Student answer (pages {page_refs}):\n{answer_text}\n\n"
        "Return JSON: {\"score\":0,\"feedback\":\"\",\"confidence\":0,\"page_notes\":[] }"
    )


def parse_grade_response(raw_text: str) -> Optional[Dict[str, Any]]:
    if not raw_text:
        return None
    raw = raw_text.strip()
    candidates = [raw]
    for m in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE):
        block = (m.group(1) or "").strip()
        if block:
            candidates.append(block)
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue
    return None


__all__ = ["build_cbse_prompt", "parse_grade_response"]
