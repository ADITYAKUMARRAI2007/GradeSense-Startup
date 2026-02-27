"""Confidence summaries for universal pipeline."""

from __future__ import annotations

from typing import Any, Dict, List


def _summary(values: List[float]) -> Dict[str, float]:
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return {"min": 0.0, "max": 0.0, "avg": 0.0}
    return {
        "min": round(min(vals), 4),
        "max": round(max(vals), 4),
        "avg": round(sum(vals) / max(1, len(vals)), 4),
    }


def compute_confidence_vectors(aligned_answers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    vectors: List[Dict[str, Any]] = []
    for row in aligned_answers or []:
        packet = row.get("packet") or {}
        blocks = packet.get("text_blocks") or []
        ocr_vals = [float(b.get("ocr_confidence", b.get("confidence", 0.0)) or 0.0) for b in blocks]
        ocr_conf = sum(ocr_vals) / max(1, len(ocr_vals)) if ocr_vals else 0.0
        table_conf = ocr_conf if (packet.get("table_segments") or []) else max(0.0, ocr_conf - 0.1)
        align_conf = float(row.get("alignment_confidence", packet.get("mapping_confidence", 0.0)) or 0.0)
        vectors.append(
            {
                "question_id": int(row.get("question_id") or 0),
                "anchor_confidence": 1.0 if row.get("aligned_by") == "anchor" else 0.6 if row.get("aligned_by") == "recovered" else 0.0,
                "ocr_confidence": round(float(ocr_conf), 4),
                "table_confidence": round(float(table_conf), 4),
                "alignment_confidence": round(float(align_conf), 4),
                "mapping_confidence": round(float(packet.get("mapping_confidence", 0.0) or 0.0), 4),
            }
        )
    return vectors


def build_confidence_gate(
    expected_question_ids: List[int],
    aligned_answers: List[Dict[str, Any]],
    confidence_vectors: List[Dict[str, Any]],
    mapping_coverage: float,
    orphan_block_ratio: float,
    orphan_block_ratio_threshold: float,
) -> Dict[str, Any]:
    detected = sorted({int(r.get("question_id") or 0) for r in (aligned_answers or []) if r.get("packet_id")})
    unresolved = sorted(set(expected_question_ids) - set(detected))
    mapped_ratio = len(detected) / float(len(expected_question_ids) or 1)

    low_conf = sorted(
        [int(v.get("question_id") or 0) for v in (confidence_vectors or []) if float(v.get("mapping_confidence", 0.0) or 0.0) < 0.55]
    )

    reasons: List[str] = []
    if mapped_ratio < 0.85:
        reasons.append(f"mapped_question_ratio_below_threshold:{mapped_ratio:.3f}<0.850")
    if mapping_coverage < 0.75:
        reasons.append(f"mapping_coverage_below_threshold:{mapping_coverage:.3f}<0.750")
    if orphan_block_ratio > orphan_block_ratio_threshold:
        reasons.append(f"orphan_block_ratio_above_threshold:{orphan_block_ratio:.3f}>{orphan_block_ratio_threshold:.3f}")
    if unresolved and len(unresolved) > max(2, int(round(len(expected_question_ids) * 0.1))):
        reasons.append(f"too_many_unresolved_questions:{len(unresolved)}")

    status = "pass"
    if reasons:
        status = "needs_review"

    return {
        "mapping_status": status,
        "mapped_question_ratio": round(mapped_ratio, 4),
        "mapping_coverage": round(float(mapping_coverage), 4),
        "unresolved_questions": unresolved,
        "mapping_fail_reasons": reasons,
        "low_confidence_questions": low_conf,
        "consistency_flags": ["mapping_gate_failed"] if reasons else [],
        "anchor_confidence_summary": _summary([float(v.get("anchor_confidence", 0.0) or 0.0) for v in confidence_vectors]),
        "table_confidence_summary": _summary([float(v.get("table_confidence", 0.0) or 0.0) for v in confidence_vectors]),
        "alignment_confidence_summary": _summary([float(v.get("alignment_confidence", 0.0) or 0.0) for v in confidence_vectors]),
        "continuity_confidence_summary": {},
        "orphan_block_ratio": round(float(orphan_block_ratio), 4),
    }


__all__ = ["compute_confidence_vectors", "build_confidence_gate"]
