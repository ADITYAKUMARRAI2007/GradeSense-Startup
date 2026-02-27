"""Phase 5: authoritative packet builder for college V2 pipeline."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple


def _avg(values: List[float]) -> float:
    vals = [float(v) for v in values if v is not None]
    return float(sum(vals) / max(1, len(vals))) if vals else 0.0


def _table_similarity(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    abox = a.get("bbox") or [0, 0, 0, 0]
    bbox = b.get("bbox") or [0, 0, 0, 0]
    aw = max(1.0, float(abox[2]) - float(abox[0]))
    bw = max(1.0, float(bbox[2]) - float(bbox[0]))
    dx_left = abs(float(abox[0]) - float(bbox[0]))
    dx_right = abs(float(abox[2]) - float(bbox[2]))
    width_ratio = min(aw, bw) / max(aw, bw)
    if width_ratio <= 0:
        return 0.0
    penalty = min(1.0, (dx_left + dx_right) / max(aw, bw))
    return max(0.0, min(1.0, width_ratio * (1.0 - penalty)))


def _init_packet(question_id: int) -> Dict[str, Any]:
    return {
        "packet_id": f"pkt_q{question_id}",
        "question_id": int(question_id),
        "pages": [],
        "segment_ids": [],
        "text_blocks": [],
        "table_segments": [],
        "working_note_segments": [],
        "subanswers": [],
        "mapping_trace": [],
        "start_anchor": None,
        "end_anchor": None,
        "mapping_confidence": 0.0,
    }


def _finalize_packet(packet: Dict[str, Any]) -> Dict[str, Any]:
    packet["pages"] = sorted(set(int(p) for p in (packet.get("pages") or []) if p is not None))
    packet["segment_ids"] = list(dict.fromkeys(packet.get("segment_ids") or []))
    packet["table_segments"] = list(dict.fromkeys(packet.get("table_segments") or []))
    packet["working_note_segments"] = list(dict.fromkeys(packet.get("working_note_segments") or []))
    packet["mapping_trace"] = list(dict.fromkeys(packet.get("mapping_trace") or []))

    confs = [float(b.get("confidence", 0.0) or 0.0) for b in (packet.get("text_blocks") or [])]
    anchor_bonus = 0.2 if packet.get("start_anchor") else 0.0
    table_bonus = 0.08 if packet.get("table_segments") else 0.0
    packet["mapping_confidence"] = round(min(0.99, _avg(confs) + anchor_bonus + table_bonus), 4)

    packet["combined_text"] = "\n".join(
        str(b.get("text", "") or "")
        for b in (packet.get("text_blocks") or [])
        if (b.get("text") or "").strip()
    )[:14000]

    by_sub: Dict[str, List[Dict[str, Any]]] = {}
    for block in (packet.get("text_blocks") or []):
        sid = block.get("subpart_id")
        if sid:
            by_sub.setdefault(str(sid), []).append(block)

    packet["subanswers"] = []
    for sid, blocks in sorted(by_sub.items(), key=lambda kv: kv[0]):
        packet["subanswers"].append(
            {
                "sub_id": sid,
                "segment_ids": [b.get("block_id") for b in blocks if b.get("block_id")],
                "combined_text": "\n".join((b.get("text", "") or "").strip() for b in blocks)[:5000],
                "page_refs": sorted({int(b.get("page_number") or 1) for b in blocks}),
                "mapping_confidence": round(_avg([float(b.get("confidence", 0.0) or 0.0) for b in blocks]), 4),
            }
        )
    packet["subquestion_count"] = len(packet["subanswers"])
    return packet


def _infer_missing_questions(
    valid_qids: Set[int],
    found_qids: Set[int],
    regions: List[Dict[str, Any]],
) -> Dict[int, List[Dict[str, Any]]]:
    """Infer missing question locations using sequence and content analysis."""
    missing_qids = sorted(valid_qids - found_qids)
    if not missing_qids:
        return {}
    
    inferred: Dict[int, List[Dict[str, Any]]] = {}
    
    # Build position map of found questions
    qid_positions: Dict[int, int] = {}
    for idx, region in enumerate(regions):
        q_anchor = region.get("question_anchor")
        if isinstance(q_anchor, int) and q_anchor in valid_qids:
            qid_positions[q_anchor] = idx
    
    # For each missing question, try to infer its location
    for missing_qid in missing_qids:
        # Find surrounding questions
        prev_qid = None
        next_qid = None
        
        for qid in sorted(qid_positions.keys()):
            if qid < missing_qid:
                prev_qid = qid
            elif qid > missing_qid and next_qid is None:
                next_qid = qid
                break
        
        # If we have both prev and next, infer the missing question is between them
        if prev_qid is not None and next_qid is not None:
            start_idx = qid_positions[prev_qid]
            end_idx = qid_positions[next_qid]
            
            # Collect regions between prev and next
            candidate_regions = []
            for idx in range(start_idx + 1, end_idx):
                region = regions[idx]
                # Skip if already assigned
                if region.get("question_anchor") is not None:
                    continue
                # Include if it looks like question content
                if (region.get("is_question_content") or 
                    region.get("has_accounting_marker") or
                    region.get("has_language_marker") or
                    region.get("has_maths_marker") or
                    region.get("has_science_marker")):
                    candidate_regions.append(region)
            
            if candidate_regions:
                inferred[missing_qid] = candidate_regions
        
        # If only prev exists, check regions after it
        elif prev_qid is not None and next_qid is None:
            start_idx = qid_positions[prev_qid]
            candidate_regions = []
            for idx in range(start_idx + 1, min(start_idx + 15, len(regions))):
                region = regions[idx]
                if region.get("question_anchor") is not None:
                    break
                if (region.get("is_question_content") or 
                    region.get("has_accounting_marker") or
                    region.get("has_language_marker") or
                    region.get("has_maths_marker") or
                    region.get("has_science_marker")):
                    candidate_regions.append(region)
            
            if candidate_regions:
                inferred[missing_qid] = candidate_regions
        
        # If only next exists, check regions before it
        elif prev_qid is None and next_qid is not None:
            end_idx = qid_positions[next_qid]
            candidate_regions = []
            for idx in range(max(0, end_idx - 15), end_idx):
                region = regions[idx]
                if region.get("question_anchor") is not None:
                    continue
                if (region.get("is_question_content") or 
                    region.get("has_accounting_marker") or
                    region.get("has_language_marker") or
                    region.get("has_maths_marker") or
                    region.get("has_science_marker")):
                    candidate_regions.append(region)
            
            if candidate_regions:
                inferred[missing_qid] = candidate_regions
    
    return inferred


def build_packets(
    region_text: List[Dict[str, Any]],
    question_blueprint: List[Dict[str, Any]],
) -> Dict[Any, Any]:
    """Build packets using anchor-driven grouping with content-based inference for missing questions."""
    valid_qids: Set[int] = {
        int(q.get("question_id"))
        for q in (question_blueprint or [])
        if q.get("question_id") is not None
    }
    packets: Dict[int, Dict[str, Any]] = {}
    active_qid: Optional[int] = None
    assigned_segments: Set[str] = set()
    found_qids: Set[int] = set()

    regions = sorted(
        region_text or [],
        key=lambda r: (
            int(r.get("page_number", 0)),
            float((r.get("bbox") or [0, 0])[1]),
            float((r.get("bbox") or [0])[0]),
        ),
    )

    # Phase 1: Anchor-based packet building
    for region in regions:
        q_anchor = region.get("question_anchor")
        if isinstance(q_anchor, int) and q_anchor in valid_qids:
            active_qid = int(q_anchor)
            found_qids.add(active_qid)
            packets.setdefault(active_qid, _init_packet(active_qid))

        if active_qid is None:
            continue

        packet = packets.setdefault(active_qid, _init_packet(active_qid))
        block_id = str(region.get("block_id") or "")
        if block_id and block_id in assigned_segments:
            continue
        if block_id:
            assigned_segments.add(block_id)

        page = int(region.get("page_number") or 1)
        bbox = region.get("bbox") or [0, 0, 0, 0]

        entry = {
            "block_id": block_id,
            "page_number": page,
            "bbox": bbox,
            "text": region.get("text", "") or "",
            "confidence": float(region.get("ocr_confidence", 0.0) or 0.0),
            "is_table": bool(region.get("is_table")),
            "is_working_note": bool(region.get("is_working_note")),
            "subpart_id": region.get("subpart_id"),
        }

        packet["pages"].append(page)
        packet["segment_ids"].append(block_id)
        packet["text_blocks"].append(entry)

        if region.get("is_table"):
            packet["table_segments"].append(block_id)
            packet["mapping_trace"].append("table_attached")
        if region.get("is_working_note"):
            packet["working_note_segments"].append(block_id)
            packet["mapping_trace"].append("working_note_attached")

        if isinstance(q_anchor, int) and q_anchor == active_qid:
            anchor = {
                "page": page,
                "y": float(bbox[1]),
                "raw": (region.get("text", "") or "")[:120],
                "segment_id": block_id,
            }
            if packet.get("start_anchor") is None:
                packet["start_anchor"] = anchor
            packet["end_anchor"] = anchor
            packet["mapping_trace"].append("anchor_match")

    # Phase 2: Infer missing questions using sequence and content analysis
    inferred_packets = _infer_missing_questions(valid_qids, found_qids, regions)
    
    for qid, candidate_regions in inferred_packets.items():
        if qid in packets:
            continue  # Already found via anchor
        
        packet = _init_packet(qid)
        packet["mapping_trace"].append("sequence_inferred")
        
        for region in candidate_regions:
            block_id = str(region.get("block_id") or "")
            if block_id in assigned_segments:
                continue
            assigned_segments.add(block_id)
            
            page = int(region.get("page_number") or 1)
            bbox = region.get("bbox") or [0, 0, 0, 0]
            
            entry = {
                "block_id": block_id,
                "page_number": page,
                "bbox": bbox,
                "text": region.get("text", "") or "",
                "confidence": float(region.get("ocr_confidence", 0.0) or 0.0),
                "is_table": bool(region.get("is_table")),
                "is_working_note": bool(region.get("is_working_note")),
                "subpart_id": region.get("subpart_id"),
            }
            
            packet["pages"].append(page)
            packet["segment_ids"].append(block_id)
            packet["text_blocks"].append(entry)
            
            if region.get("is_table"):
                packet["table_segments"].append(block_id)
            if region.get("is_working_note"):
                packet["working_note_segments"].append(block_id)
        
        if packet["text_blocks"]:
            packets[qid] = packet
            found_qids.add(qid)

    # Merge likely continued multi-page tables by continuity in x-columns.
    for qid, packet in packets.items():
        tables = [b for b in (packet.get("text_blocks") or []) if b.get("is_table")]
        tables = sorted(tables, key=lambda b: (int(b.get("page_number", 0)), float((b.get("bbox") or [0, 0])[1])))
        for prev, cur in zip(tables, tables[1:]):
            if int(cur.get("page_number", 0)) >= int(prev.get("page_number", 0)):
                sim = _table_similarity(prev, cur)
                if sim >= 0.72:
                    packet["mapping_trace"].append("multi_page_table_merge")
        packets[qid] = _finalize_packet(packet)

    mapped_regions = len(assigned_segments)
    total_regions = len([r for r in regions if (r.get("text") or "").strip() or r.get("is_table")])
    mapping_coverage = float(mapped_regions / max(1, total_regions))

    low_conf = sorted(
        int(qid)
        for qid, packet in packets.items()
        if float(packet.get("mapping_confidence", 0.0) or 0.0) < 0.6
    )
    
    inferred_count = len([p for p in packets.values() if "sequence_inferred" in p.get("mapping_trace", [])])

    packets["_meta"] = {
        "mapping_coverage": round(mapping_coverage, 4),
        "packets_generated": len(packets),
        "subpacket_count": int(sum(len((p.get("subanswers") or [])) for k, p in packets.items() if isinstance(k, int))),
        "low_confidence_questions": low_conf,
        "consistency_flags": ["low_mapping_coverage"] if mapping_coverage < 0.85 else [],
        "unassigned_region_count": max(0, total_regions - mapped_regions),
        "inferred_question_count": inferred_count,
        "found_via_anchor": len(found_qids) - inferred_count,
        "found_via_inference": inferred_count,
    }

    return packets


def expand_low_confidence_packets(
    packets: Dict[Any, Any],
    regions: List[Dict[str, Any]],
    low_question_ids: List[int],
) -> Dict[Any, Any]:
    """Recovery helper: extend low-confidence packets until next anchor."""
    if not low_question_ids:
        return packets

    by_seg = {
        str(r.get("block_id") or ""): r
        for r in (regions or [])
        if r.get("block_id")
    }
    ordered = sorted(
        regions or [],
        key=lambda r: (
            int(r.get("page_number", 0)),
            float((r.get("bbox") or [0, 0])[1]),
            float((r.get("bbox") or [0])[0]),
        ),
    )
    index = {str(r.get("block_id") or ""): i for i, r in enumerate(ordered)}

    for qid in low_question_ids:
        pkt = packets.get(int(qid))
        if not isinstance(pkt, dict):
            continue
        segment_ids = [sid for sid in (pkt.get("segment_ids") or []) if sid in index]
        if not segment_ids:
            continue
        end_idx = max(index[sid] for sid in segment_ids)

        for next_region in ordered[end_idx + 1 :]:
            if isinstance(next_region.get("question_anchor"), int):
                break
            sid = str(next_region.get("block_id") or "")
            if not sid or sid in (pkt.get("segment_ids") or []):
                continue
            entry = {
                "block_id": sid,
                "page_number": int(next_region.get("page_number") or 1),
                "bbox": next_region.get("bbox") or [0, 0, 0, 0],
                "text": next_region.get("text", "") or "",
                "confidence": float(next_region.get("ocr_confidence", 0.0) or 0.0),
                "is_table": bool(next_region.get("is_table")),
                "is_working_note": bool(next_region.get("is_working_note")),
                "subpart_id": next_region.get("subpart_id"),
            }
            pkt["segment_ids"].append(sid)
            pkt["text_blocks"].append(entry)
            pkt["pages"].append(int(next_region.get("page_number") or 1))
            if next_region.get("is_table"):
                pkt["table_segments"].append(sid)
            if next_region.get("is_working_note"):
                pkt["working_note_segments"].append(sid)
            pkt["mapping_trace"].append("boundary_expanded")
            # Bound the extension to avoid runaway packet growth.
            if len(pkt.get("segment_ids") or []) >= len(segment_ids) + 6:
                break

        packets[int(qid)] = _finalize_packet(pkt)

    packets["_meta"] = packets.get("_meta") or {}
    packets["_meta"]["recovery_boundary_expansion"] = True
    return packets


__all__ = ["build_packets", "expand_low_confidence_packets"]
