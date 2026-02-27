"""Phase 6 question-packet alignment for universal pipeline."""

from __future__ import annotations

from typing import Any, Dict, List


def align_packets(question_blueprint: List[Dict[str, Any]], packets: Dict[Any, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for q in (question_blueprint or []):
        qid = int(q.get("question_id") or 0)
        pkt = packets.get(qid) if isinstance(packets, dict) else None
        if pkt:
            out.append(
                {
                    "question_id": qid,
                    "packet_id": pkt.get("packet_id"),
                    "aligned_by": "anchor" if "anchor_match" in (pkt.get("mapping_trace") or []) else "recovered",
                    "alignment_confidence": float(pkt.get("mapping_confidence", 0.0) or 0.0),
                    "packet": pkt,
                }
            )
        else:
            out.append(
                {
                    "question_id": qid,
                    "packet_id": None,
                    "aligned_by": "missing",
                    "alignment_confidence": 0.0,
                    "packet": None,
                }
            )
    return out


__all__ = ["align_packets"]
