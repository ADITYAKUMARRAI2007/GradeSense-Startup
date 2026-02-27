"""Semantic continuity resolver for orphan OCR blocks."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.config import (
    UNIVERSAL_CONTINUITY_ATTACH_THRESHOLD,
    UNIVERSAL_CONTINUITY_MAX_PAGE_GAP,
    UNIVERSAL_CONTINUITY_SEMANTIC_WEIGHT,
    UNIVERSAL_CONTINUITY_SPATIAL_WEIGHT,
    UNIVERSAL_CONTINUITY_STRUCTURAL_WEIGHT,
)

from .embeddings import SemanticEmbeddingService, cosine_similarity

ANCHOR_RE = re.compile(r"^\s*(?:q\.?\s*)?0*(\d{1,3})(?:\s*[\).:]|\b)", re.IGNORECASE)
WORKING_RE = re.compile(r"\b(?:working\s*note|working|wn|note|calc|calculation)\b", re.IGNORECASE)
LEDGER_RE = re.compile(r"\b(?:dr\.?|cr\.?|journal|ledger|balance|particulars)\b", re.IGNORECASE)


def _bbox(block: Dict[str, Any]) -> List[float]:
    return [float(v) for v in (block.get("bbox") or [0, 0, 0, 0])]


def _spatial_score(block: Dict[str, Any], packet: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
    pages = packet.get("pages") or []
    if not pages:
        return 0.0, {"reason": "empty_packet"}
    last_page = int(max(pages))
    b_page = int(block.get("page_number") or 1)
    page_gap = abs(b_page - last_page)
    if page_gap > UNIVERSAL_CONTINUITY_MAX_PAGE_GAP:
        return 0.0, {"page_gap": page_gap, "max_gap": UNIVERSAL_CONTINUITY_MAX_PAGE_GAP}

    b = _bbox(block)
    blocks = packet.get("text_blocks") or []
    if not blocks:
        return 0.25, {"page_gap": page_gap, "vertical_gap": None, "column_delta": None}
    last = blocks[-1]
    lb = _bbox(last)
    vertical_gap = abs(float(b[1]) - float(lb[3])) if b_page == int(last.get("page_number") or b_page) else 0.0
    block_center = (float(b[0]) + float(b[2])) / 2.0
    last_center = (float(lb[0]) + float(lb[2])) / 2.0
    column_delta = abs(block_center - last_center)

    page_score = 1.0 if page_gap == 0 else 0.8
    vertical_score = max(0.0, 1.0 - (vertical_gap / 250.0))
    column_score = max(0.0, 1.0 - (column_delta / 300.0))
    score = max(0.0, min(1.0, (0.4 * page_score) + (0.3 * vertical_score) + (0.3 * column_score)))
    return score, {
        "page_gap": page_gap,
        "vertical_gap": round(vertical_gap, 4),
        "column_delta": round(column_delta, 4),
        "page_score": round(page_score, 4),
        "vertical_score": round(vertical_score, 4),
        "column_score": round(column_score, 4),
    }


def _structural_score(block: Dict[str, Any], packet: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
    text = str(block.get("text") or "")
    is_table = bool(block.get("is_table"))
    is_working = bool(block.get("is_working_note") or WORKING_RE.search(text))
    packet_tables = packet.get("table_segments") or []
    packet_working = packet.get("working_note_segments") or []
    packet_text = str(
        packet.get("combined_text")
        or "\n".join((b.get("text", "") or "").strip() for b in (packet.get("text_blocks") or []) if (b.get("text") or "").strip())
    )
    flow_cont = 1.0 if packet_text.strip() and len(text.strip()) >= 8 else 0.0

    table_cont = 1.0 if (is_table and packet_tables) else (0.3 if is_table else 0.0)
    working_cont = 1.0 if is_working else (0.6 if (packet_working and "=" in text) else 0.0)
    ledger_cont = 1.0 if (LEDGER_RE.search(text) and LEDGER_RE.search(packet_text)) else 0.0
    layout = 1.0 if bool(block.get("block_type") == "table" and packet_tables) else 0.5

    score = max(
        0.0,
        min(
            1.0,
            (0.25 * table_cont)
            + (0.20 * working_cont)
            + (0.20 * ledger_cont)
            + (0.15 * layout)
            + (0.20 * flow_cont),
        ),
    )
    return score, {
        "table_continuity": round(table_cont, 4),
        "working_continuity": round(working_cont, 4),
        "ledger_continuity": round(ledger_cont, 4),
        "layout_similarity": round(layout, 4),
        "flow_continuity": round(flow_cont, 4),
    }


def _semantic_score(block: Dict[str, Any], packet: Dict[str, Any], embedder: SemanticEmbeddingService) -> Tuple[float, Dict[str, Any]]:
    block_text = str(block.get("text") or "").strip()
    pkt_text = str(
        packet.get("combined_text")
        or "\n".join((b.get("text", "") or "").strip() for b in (packet.get("text_blocks") or []) if (b.get("text") or "").strip())
    ).strip()
    if not block_text or not pkt_text:
        return 0.0, {"similarity": 0.0, "reason": "empty_text"}
    vectors = embedder.embed([block_text, pkt_text])
    if len(vectors) < 2:
        return 0.0, {"similarity": 0.0, "reason": "insufficient_vectors"}
    sim = cosine_similarity(vectors[0], vectors[1])
    return sim, {"similarity": round(sim, 4)}


def _is_strong_anchor(block: Dict[str, Any], valid_qids: set[int]) -> Optional[int]:
    if block.get("question_anchor") and int(block.get("question_anchor")) in valid_qids:
        return int(block.get("question_anchor"))
    text = str(block.get("text") or "")
    m = ANCHOR_RE.match(text)
    if not m:
        return None
    qid = int(m.group(1))
    return qid if qid in valid_qids else None


def _packet_for_qid(packets: Dict[int, Dict[str, Any]], qid: int) -> Optional[Dict[str, Any]]:
    return packets.get(int(qid))


def _append_block(packet: Dict[str, Any], block: Dict[str, Any], reason: str) -> None:
    sid = str(block.get("block_id") or "")
    if sid and sid in (packet.get("segment_ids") or []):
        return
    packet.setdefault("segment_ids", []).append(sid)
    packet.setdefault("text_blocks", []).append(block)
    packet.setdefault("pages", []).append(int(block.get("page_number") or 1))
    if block.get("is_table"):
        packet.setdefault("table_segments", []).append(sid)
    if block.get("is_working_note"):
        packet.setdefault("working_note_segments", []).append(sid)
    packet.setdefault("mapping_trace", []).append(reason)


def resolve_continuity(
    region_text: List[Dict[str, Any]],
    question_blueprint: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Assign blocks to packets using anchors + deterministic continuity scores."""
    valid_qids = {
        int(item.get("question_id"))
        for item in (question_blueprint or [])
        if item.get("question_id") is not None
    }
    sorted_blocks = sorted(
        region_text or [],
        key=lambda r: (
            int(r.get("page_number", 0)),
            float((r.get("bbox") or [0, 0])[1]),
            float((r.get("bbox") or [0])[0]),
        ),
    )

    packets: Dict[int, Dict[str, Any]] = {}
    resolved_blocks: List[Dict[str, Any]] = []
    active_qid: Optional[int] = None
    orphan_count = 0
    semantic_attach_events = 0
    table_continuity_events = 0
    embedder = SemanticEmbeddingService()

    def ensure_packet(qid: int) -> Dict[str, Any]:
        pkt = packets.get(qid)
        if pkt is None:
            pkt = {
                "packet_id": f"upkt_q{qid}",
                "question_id": qid,
                "pages": [],
                "segment_ids": [],
                "text_blocks": [],
                "table_segments": [],
                "working_note_segments": [],
                "subanswers": [],
                "mapping_trace": [],
                "mapping_confidence": 0.0,
                "start_anchor": None,
                "end_anchor": None,
            }
            packets[qid] = pkt
        return pkt

    for block in sorted_blocks:
        strong_anchor = _is_strong_anchor(block, valid_qids)
        text = str(block.get("text") or "")
        is_working = bool(block.get("is_working_note") or WORKING_RE.search(text))

        if strong_anchor is not None:
            active_qid = strong_anchor
            pkt = ensure_packet(active_qid)
            _append_block(pkt, block, "anchor_match")
            resolved_blocks.append(
                {
                    "block_id": str(block.get("block_id") or ""),
                    "assigned_packet_id": pkt.get("packet_id"),
                    "continuity_score": 1.0,
                    "continuity_trace": {
                        "candidate_packet_id": pkt.get("packet_id"),
                        "spatial_features": {},
                        "structural_features": {},
                        "semantic_features": {},
                        "weights": {
                            "spatial": UNIVERSAL_CONTINUITY_SPATIAL_WEIGHT,
                            "structural": UNIVERSAL_CONTINUITY_STRUCTURAL_WEIGHT,
                            "semantic": UNIVERSAL_CONTINUITY_SEMANTIC_WEIGHT,
                        },
                        "final_score": 1.0,
                        "decision_reason": "anchor_priority",
                    },
                    "attached_by": "anchor",
                }
            )
            continue

        candidate_qid = active_qid
        candidate_packet = _packet_for_qid(packets, candidate_qid) if candidate_qid is not None else None

        if is_working and candidate_packet is not None:
            _append_block(candidate_packet, block, "working_note_attached")
            resolved_blocks.append(
                {
                    "block_id": str(block.get("block_id") or ""),
                    "assigned_packet_id": candidate_packet.get("packet_id"),
                    "continuity_score": 0.99,
                    "continuity_trace": {
                        "candidate_packet_id": candidate_packet.get("packet_id"),
                        "spatial_features": {},
                        "structural_features": {"working_note_rule": 1.0},
                        "semantic_features": {},
                        "weights": {
                            "spatial": UNIVERSAL_CONTINUITY_SPATIAL_WEIGHT,
                            "structural": UNIVERSAL_CONTINUITY_STRUCTURAL_WEIGHT,
                            "semantic": UNIVERSAL_CONTINUITY_SEMANTIC_WEIGHT,
                        },
                        "final_score": 0.99,
                        "decision_reason": "working_note_attach",
                    },
                    "attached_by": "recovered",
                }
            )
            continue

        if candidate_packet is None:
            orphan_count += 1
            resolved_blocks.append(
                {
                    "block_id": str(block.get("block_id") or ""),
                    "assigned_packet_id": None,
                    "continuity_score": 0.0,
                    "continuity_trace": {
                        "candidate_packet_id": None,
                        "spatial_features": {},
                        "structural_features": {},
                        "semantic_features": {},
                        "weights": {
                            "spatial": UNIVERSAL_CONTINUITY_SPATIAL_WEIGHT,
                            "structural": UNIVERSAL_CONTINUITY_STRUCTURAL_WEIGHT,
                            "semantic": UNIVERSAL_CONTINUITY_SEMANTIC_WEIGHT,
                        },
                        "final_score": 0.0,
                        "decision_reason": "no_active_packet",
                    },
                    "attached_by": "unresolved",
                }
            )
            continue

        spatial, spatial_trace = _spatial_score(block, candidate_packet)
        structural, structural_trace = _structural_score(block, candidate_packet)
        semantic, semantic_trace = _semantic_score(block, candidate_packet, embedder)
        continuity_score = max(
            0.0,
            min(
                1.0,
                (UNIVERSAL_CONTINUITY_SPATIAL_WEIGHT * spatial)
                + (UNIVERSAL_CONTINUITY_STRUCTURAL_WEIGHT * structural)
                + (UNIVERSAL_CONTINUITY_SEMANTIC_WEIGHT * semantic),
            ),
        )

        attached_by = "unresolved"
        assigned_packet_id: Optional[str] = None
        decision_reason = "below_threshold"

        # Sequential-flow boost for non-anchored continuation when signals agree.
        if spatial >= 0.8 and (structural >= 0.35 or semantic >= 0.25):
            continuity_score = max(continuity_score, 0.72)
            decision_reason = "sequential_continuity_boost"

        if block.get("is_table") and candidate_packet.get("table_segments"):
            continuity_score = max(continuity_score, 0.95)
            decision_reason = "table_sticky"

        if continuity_score >= UNIVERSAL_CONTINUITY_ATTACH_THRESHOLD:
            _append_block(candidate_packet, block, "continuity_attach")
            attached_by = "continuity"
            assigned_packet_id = candidate_packet.get("packet_id")
            decision_reason = "continuity_threshold_met"
            if semantic >= 0.7:
                semantic_attach_events += 1
            if block.get("is_table"):
                table_continuity_events += 1
        else:
            orphan_count += 1

        resolved_blocks.append(
            {
                "block_id": str(block.get("block_id") or ""),
                "assigned_packet_id": assigned_packet_id,
                "continuity_score": round(float(continuity_score), 4),
                "continuity_trace": {
                    "candidate_packet_id": candidate_packet.get("packet_id"),
                    "spatial_features": spatial_trace,
                    "structural_features": structural_trace,
                    "semantic_features": semantic_trace,
                    "weights": {
                        "spatial": UNIVERSAL_CONTINUITY_SPATIAL_WEIGHT,
                        "structural": UNIVERSAL_CONTINUITY_STRUCTURAL_WEIGHT,
                        "semantic": UNIVERSAL_CONTINUITY_SEMANTIC_WEIGHT,
                    },
                    "final_score": round(float(continuity_score), 4),
                    "decision_reason": decision_reason,
                },
                "attached_by": attached_by,
            }
        )

    total = len(sorted_blocks)
    orphan_ratio = float(orphan_count / max(1, total))
    summary = {
        "continuity_confidence_summary": {
            "min": round(min((r.get("continuity_score", 0.0) for r in resolved_blocks), default=0.0), 4),
            "max": round(max((r.get("continuity_score", 0.0) for r in resolved_blocks), default=0.0), 4),
            "avg": round(sum(float(r.get("continuity_score", 0.0) or 0.0) for r in resolved_blocks) / max(1, len(resolved_blocks)), 4),
        },
        "orphan_block_count": int(orphan_count),
        "orphan_block_ratio": round(orphan_ratio, 4),
        "semantic_attach_events": int(semantic_attach_events),
        "table_continuity_events": int(table_continuity_events),
    }

    return {
        "resolved_blocks": resolved_blocks,
        "continuity_confidence_summary": summary["continuity_confidence_summary"],
        "orphan_block_count": summary["orphan_block_count"],
        "orphan_block_ratio": summary["orphan_block_ratio"],
        "semantic_attach_events": summary["semantic_attach_events"],
        "table_continuity_events": summary["table_continuity_events"],
        "packets": packets,
    }


__all__ = ["resolve_continuity"]
