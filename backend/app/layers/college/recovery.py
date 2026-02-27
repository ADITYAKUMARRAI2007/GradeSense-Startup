"""Phase 8: confidence scoring and localized recovery for college V2."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .alignment import align_packets_to_blueprint
from .packet_builder import expand_low_confidence_packets


def _summary(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"min": 0.0, "max": 0.0, "avg": 0.0}
    vals = [float(v) for v in values]
    return {
        "min": round(min(vals), 4),
        "max": round(max(vals), 4),
        "avg": round(sum(vals) / max(1, len(vals)), 4),
    }


def _content_similarity(text1: str, text2: str) -> float:
    """Calculate simple word-based similarity between two texts."""
    if not text1 or not text2:
        return 0.0
    
    words1 = set((text1 or "").lower().split())
    words2 = set((text2 or "").lower().split())
    
    if not words1 or not words2:
        return 0.0
    
    intersection = len(words1 & words2)
    union = len(words1 | words2)
    
    return float(intersection / max(1, union))


def recover_missing_by_content_matching(
    question_blueprint: List[Dict[str, Any]],
    packets: Dict[Any, Any],
    regions: List[Dict[str, Any]],
    missing_qids: List[int],
) -> Dict[int, Dict[str, Any]]:
    """Try to match missing questions to unassigned regions by content similarity."""
    if not missing_qids:
        return {}
    
    # Get blueprint questions for missing IDs
    blueprint_by_qid = {
        int(q.get("question_id")): q
        for q in (question_blueprint or [])
        if q.get("question_id") is not None
    }
    
    # Get assigned segment IDs
    assigned_segments = set()
    for qid, packet in packets.items():
        if isinstance(qid, int):
            assigned_segments.update(packet.get("segment_ids", []))
    
    # Get unassigned regions with question-like content
    unassigned_regions = [
        r for r in (regions or [])
        if (r.get("block_id") not in assigned_segments and
            (r.get("is_question_content") or
             r.get("has_accounting_marker") or
             r.get("has_language_marker") or
             r.get("has_maths_marker") or
             r.get("has_science_marker")))
    ]
    
    if not unassigned_regions:
        return {}
    
    recovered: Dict[int, Dict[str, Any]] = {}
    
    for qid in missing_qids:
        blueprint_q = blueprint_by_qid.get(qid)
        if not blueprint_q:
            continue
        
        # Get question text from blueprint
        q_text = str(blueprint_q.get("question_text", "") or "")
        if not q_text or len(q_text) < 10:
            continue
        
        # Find best matching unassigned region
        best_match = None
        best_score = 0.0
        
        for region in unassigned_regions:
            region_text = str(region.get("text", "") or "")
            if not region_text:
                continue
            
            similarity = _content_similarity(q_text, region_text)
            
            # Boost score if region has subject-specific markers
            if region.get("has_accounting_marker"):
                similarity += 0.1
            if region.get("has_language_marker"):
                similarity += 0.1
            if region.get("has_maths_marker"):
                similarity += 0.1
            if region.get("has_science_marker"):
                similarity += 0.1
            
            if similarity > best_score and similarity > 0.15:
                best_score = similarity
                best_match = region
        
        if best_match:
            # Create packet from matched region
            from .packet_builder import _init_packet, _finalize_packet
            
            packet = _init_packet(qid)
            packet["mapping_trace"].append("content_matched")
            
            block_id = str(best_match.get("block_id") or "")
            page = int(best_match.get("page_number") or 1)
            bbox = best_match.get("bbox") or [0, 0, 0, 0]
            
            entry = {
                "block_id": block_id,
                "page_number": page,
                "bbox": bbox,
                "text": best_match.get("text", "") or "",
                "confidence": float(best_match.get("ocr_confidence", 0.0) or 0.0),
                "is_table": bool(best_match.get("is_table")),
                "is_working_note": bool(best_match.get("is_working_note")),
                "subpart_id": best_match.get("subpart_id"),
            }
            
            packet["pages"].append(page)
            packet["segment_ids"].append(block_id)
            packet["text_blocks"].append(entry)
            
            if best_match.get("is_table"):
                packet["table_segments"].append(block_id)
            if best_match.get("is_working_note"):
                packet["working_note_segments"].append(block_id)
            
            recovered[qid] = _finalize_packet(packet)
            assigned_segments.add(block_id)
            unassigned_regions.remove(best_match)
    
    return recovered


def compute_confidence_vectors(aligned_answers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    vectors: List[Dict[str, Any]] = []
    for row in aligned_answers or []:
        qid = int(row.get("question_id") or 0)
        packet = row.get("packet") or {}
        text_blocks = packet.get("text_blocks") or []
        ocr_values = [float(b.get("confidence", 0.0) or 0.0) for b in text_blocks]
        ocr_conf = float(sum(ocr_values) / max(1, len(ocr_values))) if ocr_values else 0.0
        anchor_conf = 1.0 if packet.get("start_anchor") else 0.0
        has_table = bool(packet.get("table_segments"))
        table_conf = 1.0 if has_table else 0.35
        align_conf = float(row.get("alignment_confidence", 0.0) or 0.0)
        mapping_conf = float(packet.get("mapping_confidence", 0.0) or 0.0)
        vectors.append(
            {
                "question_id": qid,
                "anchor_confidence": round(anchor_conf, 4),
                "ocr_confidence": round(ocr_conf, 4),
                "table_confidence": round(table_conf, 4),
                "alignment_confidence": round(align_conf, 4),
                "mapping_confidence": round(mapping_conf, 4),
            }
        )
    return vectors


def run_recovery(
    question_blueprint: List[Dict[str, Any]],
    packets: Dict[Any, Any],
    aligned_answers: List[Dict[str, Any]],
    region_text: List[Dict[str, Any]],
    packet_conf_min: float = 0.6,
) -> Tuple[Dict[Any, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Apply multi-strategy recovery: boundary expansion + content matching."""
    vectors = compute_confidence_vectors(aligned_answers)
    
    # Strategy 1: Expand low-confidence packets
    low_qids = sorted(
        int(v.get("question_id") or 0)
        for v in vectors
        if float(v.get("mapping_confidence", 0.0) or 0.0) < float(packet_conf_min)
    )
    
    if low_qids:
        packets = expand_low_confidence_packets(packets, region_text, low_qids)
        aligned_answers = align_packets_to_blueprint(question_blueprint, packets)
        vectors = compute_confidence_vectors(aligned_answers)
    
    # Strategy 2: Content-based matching for completely missing questions
    missing_qids = sorted(
        int(q.get("question_id") or 0)
        for q in (question_blueprint or [])
        if q.get("question_id") is not None and int(q.get("question_id")) not in packets
    )
    
    if missing_qids:
        recovered_packets = recover_missing_by_content_matching(
            question_blueprint,
            packets,
            region_text,
            missing_qids
        )
        
        # Merge recovered packets
        for qid, packet in recovered_packets.items():
            packets[qid] = packet
        
        # Re-align and recompute vectors
        if recovered_packets:
            aligned_answers = align_packets_to_blueprint(question_blueprint, packets)
            vectors = compute_confidence_vectors(aligned_answers)
            
            # Update meta with recovery stats
            meta = packets.get("_meta", {})
            meta["content_matched_count"] = len(recovered_packets)
            packets["_meta"] = meta
    
    return packets, aligned_answers, vectors


def build_gate(
    expected_question_ids: List[int],
    aligned_answers: List[Dict[str, Any]],
    confidence_vectors: List[Dict[str, Any]],
    mapping_coverage: float,
    mapped_ratio_min: float,
    mapping_coverage_min: float,
    unresolved_ratio_max: float,
    confidence_min: float,
) -> Dict[str, Any]:
    aligned_by_q = {int(r.get("question_id") or 0): r for r in aligned_answers or []}
    vector_by_q = {int(v.get("question_id") or 0): v for v in confidence_vectors or []}

    mapped = [qid for qid in expected_question_ids if (aligned_by_q.get(qid) or {}).get("packet")]
    unresolved = sorted([qid for qid in expected_question_ids if qid not in mapped])
    mapped_ratio = float(len(mapped) / max(1, len(expected_question_ids)))

    unresolved_limit = max(2, int(round(len(expected_question_ids) * unresolved_ratio_max))) if expected_question_ids else 0
    low_conf = sorted(
        qid
        for qid in mapped
        if float((vector_by_q.get(qid) or {}).get("mapping_confidence", 0.0) or 0.0) < float(confidence_min)
    )

    fail_reasons: List[str] = []
    if mapped_ratio < mapped_ratio_min:
        fail_reasons.append(f"mapped_question_ratio_below_threshold:{mapped_ratio:.3f}<{mapped_ratio_min:.3f}")
    if mapping_coverage < mapping_coverage_min:
        fail_reasons.append(f"mapping_coverage_below_threshold:{mapping_coverage:.3f}<{mapping_coverage_min:.3f}")
    if len(unresolved) > unresolved_limit:
        fail_reasons.append(f"too_many_unresolved_questions:{len(unresolved)}>{unresolved_limit}")
    if low_conf:
        fail_reasons.append(f"low_confidence_packets:{','.join(str(q) for q in low_conf[:25])}")

    status = "pass" if not fail_reasons else "needs_review"
    if mapped_ratio <= 0.01 and mapping_coverage <= 0.01:
        status = "failed"

    anchor_vals = [float(v.get("anchor_confidence", 0.0) or 0.0) for v in confidence_vectors]
    table_vals = [float(v.get("table_confidence", 0.0) or 0.0) for v in confidence_vectors]
    align_vals = [float(v.get("alignment_confidence", 0.0) or 0.0) for v in confidence_vectors]

    return {
        "mapping_status": status,
        "mapped_question_ratio": round(mapped_ratio, 4),
        "mapping_coverage": round(float(mapping_coverage), 4),
        "unresolved_questions": unresolved,
        "mapping_fail_reasons": fail_reasons,
        "low_confidence_questions": low_conf,
        "consistency_flags": ["mapping_gate_failed"] if fail_reasons else [],
        "anchor_confidence_summary": _summary(anchor_vals),
        "table_confidence_summary": _summary(table_vals),
        "alignment_confidence_summary": _summary(align_vals),
    }


__all__ = ["compute_confidence_vectors", "run_recovery", "build_gate"]
