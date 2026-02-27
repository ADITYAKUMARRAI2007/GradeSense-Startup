"""Phase 3 question detection and blueprint health checks."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Set, Tuple


def _question_type_from_text(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in ["choose", "mcq", "option", "true/false"]):
        return "mcq"
    if any(k in t for k in ["calculate", "journal", "ledger", "balance", "table", "prepare"]):
        return "table/numerical"
    if any(k in t for k in ["define", "state", "write short", "one word"]):
        return "short"
    return "descriptive"


def detect_question_blueprint(exam_questions: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Build question blueprint from exam question metadata with health diagnostics."""
    blueprint: List[Dict[str, Any]] = []
    parsed_numbers: List[int] = []

    for q in exam_questions or []:
        qn = q.get("question_number")
        if qn is None or not str(qn).isdigit():
            continue
        qid = int(qn)
        parsed_numbers.append(qid)
        rubric = str(q.get("rubric", "") or "")
        marks = float(q.get("marks") or q.get("max_marks") or 0.0)
        if marks <= 0:
            marks = float(sum(float(sq.get("marks") or 0.0) for sq in (q.get("sub_questions") or [])))
        subparts = []
        for sq in (q.get("sub_questions") or []):
            subparts.append({
                "sub_id": str(sq.get("sub_question_number") or sq.get("sub_id") or ""),
                "text": str(sq.get("text") or sq.get("rubric") or "").strip(),
                "marks": float(sq.get("marks") or 0.0),
            })
        blueprint.append(
            {
                "question_id": qid,
                "subparts": subparts,
                "marks": marks,
                "type": _question_type_from_text(rubric),
                "optional_group": q.get("optional_group"),
                "expected_components": q.get("expected_components") or [],
                "question_text": rubric,
                "source_question": q,
            }
        )

    parsed_numbers = sorted(parsed_numbers)
    count = Counter(parsed_numbers)
    duplicates = sorted([n for n, c in count.items() if c > 1])
    unique_numbers = sorted(set(parsed_numbers))
    missing: List[int] = []
    numbering_contiguous = True
    if unique_numbers:
        expected = list(range(unique_numbers[0], unique_numbers[-1] + 1))
        expected_set: Set[int] = set(expected)
        missing = sorted(list(expected_set - set(unique_numbers)))
        numbering_contiguous = len(missing) == 0
    completeness = 1.0 if numbering_contiguous else max(0.0, 1.0 - (len(missing) / max(1, len(unique_numbers))))

    health = {
        "question_count": len(unique_numbers),
        "parsed_numbers": unique_numbers,
        "missing": missing,
        "duplicates": duplicates,
        "unexpected": [],
        "expected_count": len(unique_numbers),
        "completeness_score": round(completeness, 4),
        "numbering_contiguous": numbering_contiguous,
        "sections_detected": 1,
        "is_complete": numbering_contiguous and not duplicates,
        "failed_chunks": [],
    }
    return sorted(blueprint, key=lambda x: int(x.get("question_id") or 0)), health


__all__ = ["detect_question_blueprint"]
