"""UniversalPipelineV2 orchestrator with continuity resolver."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from app.config import (
    UNIVERSAL_HARD_STOP,
    UNIVERSAL_ORPHAN_BLOCK_RATIO_THRESHOLD,
    logger,
)

from .alignment import align_packets
from .confidence import build_confidence_gate, compute_confidence_vectors
from .contracts import UniversalPipelineResult
from .continuity import resolve_continuity
from .ingestion import ingest_pdf_pages
from .ocr import extract_ocr_blocks
from .packet_builder import build_packets_from_continuity
from .question_detection import detect_question_blueprint
from .recovery import run_recovery
from .structuring import structure_answers


class UniversalPipelineV2:
    """Strict extraction-first universal orchestrator."""

    def _phase_timer(self, name: str, timings: Dict[str, float], start: float) -> None:
        timings[name] = round(time.perf_counter() - start, 4)

    def run(
        self,
        exam_id: str,
        exam_questions: List[Dict[str, Any]],
        answer_images: List[str],
        question_paper_pdf_bytes: Optional[bytes] = None,
        failed_chunks: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        timings: Dict[str, float] = {}
        logger.info("[UNIVERSAL-V2] run start exam_id=%s pages=%s", exam_id, len(answer_images or []))

        # Phase 3 question detection / blueprint (from extracted exam questions)
        phase_start = time.perf_counter()
        question_blueprint, blueprint_health = detect_question_blueprint(exam_questions or [])
        self._phase_timer("phase_3_question_detection", timings, phase_start)
        if not question_blueprint or not blueprint_health.get("numbering_contiguous", False):
            gate = {
                "mapping_status": "failed",
                "mapped_question_ratio": 0.0,
                "mapping_coverage": 0.0,
                "unresolved_questions": [int(q.get("question_id")) for q in question_blueprint if q.get("question_id") is not None],
                "mapping_fail_reasons": ["blueprint_not_contiguous_or_empty"],
                "low_confidence_questions": [],
                "consistency_flags": ["blueprint_gate_failed"],
                "anchor_confidence_summary": {"min": 0.0, "max": 0.0, "avg": 0.0},
                "table_confidence_summary": {"min": 0.0, "max": 0.0, "avg": 0.0},
                "alignment_confidence_summary": {"min": 0.0, "max": 0.0, "avg": 0.0},
            }
            return UniversalPipelineResult(
                question_blueprint=question_blueprint,
                blueprint_health=blueprint_health,
                gate=gate,
                phase_timings=timings,
            ).as_dict()

        # Phase 1 ingestion
        phase_start = time.perf_counter()
        clean_pages, preprocess_metrics = ingest_pdf_pages(answer_images or [])
        self._phase_timer("phase_1_ingestion", timings, phase_start)
        if not clean_pages:
            gate = {
                "mapping_status": "failed",
                "mapped_question_ratio": 0.0,
                "mapping_coverage": 0.0,
                "unresolved_questions": [int(q.get("question_id")) for q in question_blueprint if q.get("question_id") is not None],
                "mapping_fail_reasons": ["ingestion_failed"],
                "low_confidence_questions": [],
                "consistency_flags": ["ingestion_gate_failed"],
                "anchor_confidence_summary": {"min": 0.0, "max": 0.0, "avg": 0.0},
                "table_confidence_summary": {"min": 0.0, "max": 0.0, "avg": 0.0},
                "alignment_confidence_summary": {"min": 0.0, "max": 0.0, "avg": 0.0},
            }
            return UniversalPipelineResult(
                question_blueprint=question_blueprint,
                blueprint_health=blueprint_health,
                clean_pages_count=0,
                preprocess_metrics=preprocess_metrics,
                gate=gate,
                phase_timings=timings,
            ).as_dict()

        # Phase 2 OCR
        phase_start = time.perf_counter()
        page_layout, region_text, layout_flags = extract_ocr_blocks(clean_pages)
        self._phase_timer("phase_2_ocr", timings, phase_start)

        # Phase 4 continuity resolver
        phase_start = time.perf_counter()
        continuity = resolve_continuity(region_text, question_blueprint)
        self._phase_timer("phase_4_continuity", timings, phase_start)

        # Phase 5 packet builder
        phase_start = time.perf_counter()
        packets = build_packets_from_continuity(continuity)
        self._phase_timer("phase_5_packet_builder", timings, phase_start)

        # Phase 6 alignment
        phase_start = time.perf_counter()
        aligned_answers = align_packets(question_blueprint, packets)
        self._phase_timer("phase_6_alignment", timings, phase_start)

        # Phase 7 structuring
        phase_start = time.perf_counter()
        structured_answers = structure_answers(question_blueprint, aligned_answers)
        self._phase_timer("phase_7_structuring", timings, phase_start)

        # Phase 8 confidence/recovery
        phase_start = time.perf_counter()
        confidence_vectors = compute_confidence_vectors(aligned_answers)
        aligned_answers, confidence_vectors = run_recovery(region_text, aligned_answers, confidence_vectors)
        expected_ids = [int(q.get("question_id")) for q in question_blueprint if q.get("question_id") is not None]
        mapping_coverage = float((packets.get("_meta", {}) or {}).get("mapping_coverage", 0.0) or 0.0)
        orphan_ratio = float((continuity or {}).get("orphan_block_ratio", 0.0) or 0.0)
        gate = build_confidence_gate(
            expected_question_ids=expected_ids,
            aligned_answers=aligned_answers,
            confidence_vectors=confidence_vectors,
            mapping_coverage=mapping_coverage,
            orphan_block_ratio=orphan_ratio,
            orphan_block_ratio_threshold=UNIVERSAL_ORPHAN_BLOCK_RATIO_THRESHOLD,
        )
        gate["continuity_confidence_summary"] = (continuity or {}).get("continuity_confidence_summary", {})
        gate["orphan_block_count"] = int((continuity or {}).get("orphan_block_count", 0) or 0)
        gate["orphan_block_ratio"] = orphan_ratio

        if UNIVERSAL_HARD_STOP and orphan_ratio > UNIVERSAL_ORPHAN_BLOCK_RATIO_THRESHOLD:
            status = str(gate.get("mapping_status", "needs_review") or "needs_review")
            if status == "pass":
                gate["mapping_status"] = "needs_review"
            reasons = gate.get("mapping_fail_reasons") or []
            marker = (
                f"orphan_block_ratio_above_threshold:{orphan_ratio:.3f}>{UNIVERSAL_ORPHAN_BLOCK_RATIO_THRESHOLD:.3f}"
            )
            if marker not in reasons:
                reasons.append(marker)
            gate["mapping_fail_reasons"] = reasons
        self._phase_timer("phase_8_confidence_recovery", timings, phase_start)

        # Phase 9 grading stays in service layer; emit final payload only.
        final_output = []
        for row in structured_answers:
            qid = int(row.get("question_id") or 0)
            aligned = next((a for a in aligned_answers if int(a.get("question_id") or 0) == qid), None)
            packet = (aligned or {}).get("packet")
            conf = float((aligned or {}).get("alignment_confidence", 0.0) or 0.0)
            issues: List[str] = []
            if not packet:
                issues.append("missing_packet")
            if conf < 0.55:
                issues.append("low_mapping_confidence")
            final_output.append(
                {
                    "question_id": qid,
                    "expected": next((q for q in question_blueprint if int(q.get("question_id") or 0) == qid), {}),
                    "student_answer_structured": row.get("structured_answer", {}),
                    "confidence": round(conf, 4),
                    "issues": issues,
                    "aligned_by": (aligned or {}).get("aligned_by"),
                    "packet": packet,
                }
            )

        return UniversalPipelineResult(
            question_blueprint=question_blueprint,
            blueprint_health=blueprint_health,
            clean_pages_count=len(clean_pages),
            preprocess_metrics=preprocess_metrics,
            page_layout=page_layout,
            region_text=region_text,
            continuity=continuity,
            packets=packets,
            aligned_answers=aligned_answers,
            structured_answers=structured_answers,
            confidence_vectors=confidence_vectors,
            final_output=final_output,
            gate=gate,
            phase_timings=timings,
        ).as_dict()


def pipeline_result_to_question_map(pipeline_result: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    packets = (pipeline_result or {}).get("packets", {}) or {}
    out: Dict[Any, Any] = {}
    for qn, pkt in packets.items():
        if not isinstance(qn, int):
            continue
        text_blocks = pkt.get("text_blocks", []) or []
        segments = []
        for blk in text_blocks:
            bbox = blk.get("bbox") or [0, 0, 0, 0]
            segments.append(
                {
                    "segment_id": blk.get("block_id"),
                    "page": blk.get("page_number"),
                    "text": blk.get("text", ""),
                    "x1": bbox[0],
                    "y1": bbox[1],
                    "x2": bbox[2],
                    "y2": bbox[3],
                    "tables": [{}] if blk.get("is_table") else [],
                    "confidence": float(blk.get("ocr_confidence", blk.get("confidence", 0.0)) or 0.0),
                }
            )

        out[int(qn)] = {
            "question_number": int(qn),
            "segments": segments,
            "subquestions": {},
            "subanswers": pkt.get("subanswers", []),
            "page_refs": pkt.get("pages", []),
            "tables": [{"segment_id": sid} for sid in (pkt.get("table_segments", []) or [])],
            "table_segments": pkt.get("table_segments", []),
            "working_note_segments": pkt.get("working_note_segments", []),
            "segment_ids": pkt.get("segment_ids", []),
            "combined_text": pkt.get("combined_text", ""),
            "extracted_text": pkt.get("combined_text", ""),
            "subquestion_count": int(pkt.get("subquestion_count", 0) or 0),
            "mapping_confidence": float(pkt.get("mapping_confidence", 0.0) or 0.0),
            "mapping_trace": pkt.get("mapping_trace", []),
            "start_anchor": pkt.get("start_anchor"),
            "end_anchor": pkt.get("end_anchor"),
        }

    gate = (pipeline_result or {}).get("gate", {}) or {}
    meta = (packets.get("_meta", {}) if isinstance(packets, dict) else {}) or {}
    continuity = (pipeline_result or {}).get("continuity", {}) or {}
    out["_meta"] = {
        "pipeline": "universal_v2",
        "mapping_coverage": float(gate.get("mapping_coverage", meta.get("mapping_coverage", 0.0)) or 0.0),
        "packets_generated": int(meta.get("packets_generated", len([k for k in out.keys() if isinstance(k, int)])) or 0),
        "subpacket_count": int(meta.get("subpacket_count", 0) or 0),
        "low_confidence_questions": gate.get("low_confidence_questions", meta.get("low_confidence_questions", [])),
        "consistency_flags": gate.get("consistency_flags", meta.get("consistency_flags", [])),
        "mapped_question_ratio": float(gate.get("mapped_question_ratio", 0.0) or 0.0),
        "unresolved_questions": gate.get("unresolved_questions", []),
        "mapping_fail_reasons": gate.get("mapping_fail_reasons", []),
        "mapping_status": str(gate.get("mapping_status", "needs_review") or "needs_review"),
        "anchor_confidence_summary": gate.get("anchor_confidence_summary", {}),
        "table_confidence_summary": gate.get("table_confidence_summary", {}),
        "alignment_confidence_summary": gate.get("alignment_confidence_summary", {}),
        "continuity_confidence_summary": gate.get("continuity_confidence_summary", continuity.get("continuity_confidence_summary", {})),
        "orphan_block_count": int(gate.get("orphan_block_count", continuity.get("orphan_block_count", 0)) or 0),
        "orphan_block_ratio": float(gate.get("orphan_block_ratio", continuity.get("orphan_block_ratio", 0.0)) or 0.0),
        "semantic_attach_events": int(continuity.get("semantic_attach_events", 0) or 0),
        "table_continuity_events": int(continuity.get("table_continuity_events", 0) or 0),
        "continuity_resolved_blocks": continuity.get("resolved_blocks", []),
        "phase_timings": (pipeline_result or {}).get("phase_timings", {}),
    }
    return out


def run_universal_pipeline_v2(
    exam_id: str,
    exam_questions: List[Dict[str, Any]],
    answer_images: List[str],
    question_paper_pdf_bytes: Optional[bytes] = None,
    failed_chunks: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Any], Dict[int, Dict[str, Any]]]:
    engine = UniversalPipelineV2()
    pipeline_result = engine.run(
        exam_id=exam_id,
        exam_questions=exam_questions,
        answer_images=answer_images,
        question_paper_pdf_bytes=question_paper_pdf_bytes,
        failed_chunks=failed_chunks,
    )
    question_map = pipeline_result_to_question_map(pipeline_result)
    return pipeline_result, question_map


__all__ = ["UniversalPipelineV2", "run_universal_pipeline_v2", "pipeline_result_to_question_map"]
