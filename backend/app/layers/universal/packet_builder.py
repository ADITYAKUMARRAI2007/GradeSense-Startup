"""Phase 5 packet builder for universal pipeline."""

from __future__ import annotations

from typing import Any, Dict


def build_packets_from_continuity(continuity_payload: Dict[str, Any]) -> Dict[Any, Any]:
    """Finalize packets after continuity assignment."""
    packets = (continuity_payload or {}).get("packets", {}) or {}
    for qid, pkt in list(packets.items()):
        if not isinstance(qid, int) or not isinstance(pkt, dict):
            continue
        pkt["pages"] = sorted({int(p) for p in (pkt.get("pages") or [])})
        pkt["segment_ids"] = list(dict.fromkeys(pkt.get("segment_ids") or []))
        pkt["table_segments"] = list(dict.fromkeys(pkt.get("table_segments") or []))
        pkt["working_note_segments"] = list(dict.fromkeys(pkt.get("working_note_segments") or []))
        pkt["mapping_trace"] = list(dict.fromkeys(pkt.get("mapping_trace") or []))
        confs = [float(b.get("ocr_confidence", b.get("confidence", 0.0)) or 0.0) for b in (pkt.get("text_blocks") or [])]
        pkt["mapping_confidence"] = round(sum(confs) / max(1, len(confs)), 4)
        pkt["combined_text"] = "\n".join((b.get("text", "") or "").strip() for b in (pkt.get("text_blocks") or []) if (b.get("text") or "").strip())[:14000]
        packets[qid] = pkt

    packets["_meta"] = {
        "mapping_coverage": round(1.0 - float((continuity_payload or {}).get("orphan_block_ratio", 0.0) or 0.0), 4),
        "packets_generated": len([k for k in packets.keys() if isinstance(k, int)]),
        "subpacket_count": 0,
        "low_confidence_questions": [
            int(k)
            for k, v in packets.items()
            if isinstance(k, int) and float((v or {}).get("mapping_confidence", 0.0) or 0.0) < 0.6
        ],
        "consistency_flags": [],
        "unassigned_region_count": int((continuity_payload or {}).get("orphan_block_count", 0) or 0),
        "continuity_confidence_summary": (continuity_payload or {}).get("continuity_confidence_summary", {}),
        "orphan_block_count": int((continuity_payload or {}).get("orphan_block_count", 0) or 0),
        "orphan_block_ratio": float((continuity_payload or {}).get("orphan_block_ratio", 0.0) or 0.0),
        "semantic_attach_events": int((continuity_payload or {}).get("semantic_attach_events", 0) or 0),
        "table_continuity_events": int((continuity_payload or {}).get("table_continuity_events", 0) or 0),
    }
    return packets


__all__ = ["build_packets_from_continuity"]
