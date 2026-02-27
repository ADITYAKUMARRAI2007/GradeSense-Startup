"""Recovery hooks for universal pipeline."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def run_recovery(
    region_text: List[Dict[str, Any]],
    aligned_answers: List[Dict[str, Any]],
    confidence_vectors: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Perform bounded local recovery on low-confidence rows.

    Current implementation is conservative and trace-oriented: it flags low-confidence
    rows for review and avoids aggressive remapping that could corrupt grading.
    """
    low_ids = {
        int(v.get("question_id") or 0)
        for v in (confidence_vectors or [])
        if float(v.get("mapping_confidence", 0.0) or 0.0) < 0.45
    }
    if not low_ids:
        return aligned_answers, confidence_vectors

    updated = []
    for row in aligned_answers or []:
        qid = int(row.get("question_id") or 0)
        if qid in low_ids:
            row = dict(row)
            row["aligned_by"] = "recovered" if row.get("packet_id") else "missing"
            row["alignment_confidence"] = max(0.0, float(row.get("alignment_confidence", 0.0) or 0.0) - 0.05)
        updated.append(row)

    for vec in confidence_vectors:
        qid = int(vec.get("question_id") or 0)
        if qid in low_ids:
            vec["alignment_confidence"] = max(0.0, float(vec.get("alignment_confidence", 0.0) or 0.0) - 0.05)
            vec["mapping_confidence"] = max(0.0, float(vec.get("mapping_confidence", 0.0) or 0.0) - 0.05)

    return updated, confidence_vectors


__all__ = ["run_recovery"]
