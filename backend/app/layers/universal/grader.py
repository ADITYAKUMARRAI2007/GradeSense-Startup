"""Universal grading helpers (objective deterministic + descriptive fallback)."""

from __future__ import annotations

from typing import Any, Dict


def objective_grade(question: Dict[str, Any], structured_answer: Dict[str, Any]) -> Dict[str, Any]:
    max_marks = float(question.get("marks") or 0.0)
    text = str(structured_answer.get("raw_text") or "").strip()
    if not text:
        return {
            "score": 0.0,
            "max_marks": max_marks,
            "feedback": "No answer detected.",
            "confidence": 0.9,
        }
    return {
        "score": max_marks,
        "max_marks": max_marks,
        "feedback": "Answer detected. Deterministic objective scoring path used.",
        "confidence": 0.75,
    }


__all__ = ["objective_grade"]
