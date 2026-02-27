"""Phase 6: packet-to-blueprint alignment for college V2 pipeline."""

from __future__ import annotations

from typing import Any, Dict, List


def align_packets_to_blueprint(
    question_blueprint: List[Dict[str, Any]],
    packets: Dict[Any, Any],
) -> List[Dict[str, Any]]:
    """Strict anchor-first alignment; no sequence/page heuristic fallback."""
    aligned: List[Dict[str, Any]] = []

    for item in sorted(question_blueprint or [], key=lambda q: int(q.get("question_id") or 0)):
        qid = int(item.get("question_id") or 0)
        packet = packets.get(qid)
        if packet:
            aligned_by = "anchor"
            if "boundary_expanded" in (packet.get("mapping_trace") or []):
                aligned_by = "recovered"
            aligned.append(
                {
                    "question_id": qid,
                    "packet_id": packet.get("packet_id"),
                    "packet": packet,
                    "expected": item,
                    "aligned_by": aligned_by,
                    "alignment_confidence": float(packet.get("mapping_confidence", 0.0) or 0.0),
                }
            )
            continue

        aligned.append(
            {
                "question_id": qid,
                "packet_id": None,
                "packet": None,
                "expected": item,
                "aligned_by": "missing",
                "alignment_confidence": 0.0,
            }
        )

    return aligned


__all__ = ["align_packets_to_blueprint"]
