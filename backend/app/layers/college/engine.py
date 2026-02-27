"""CollegePipelineV2 orchestrator: extraction-first, grading-last."""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Tuple

from app.config import logger

from .alignment import align_packets_to_blueprint
from .blueprint import assemble_blueprint
from .contracts import CollegePipelineResult
from .layout import detect_page_blocks
from .normalization import normalize_answer_pages
from .recovery import build_gate, compute_confidence_vectors, run_recovery
from .region_ocr import extract_region_text
from .packet_builder import build_packets
from .structuring import structure_aligned_answers


class CollegePipelineV2:
    """Strict college reconstruction pipeline with hard-stop gate outputs."""

    def __init__(self) -> None:
        self.blueprint_threshold = float(os.getenv("COLLEGE_V2_BLUEPRINT_HEALTH_THRESHOLD", "0.92"))
        self.mapped_ratio_min = float(os.getenv("MAPPED_QUESTION_RATIO_MIN", "0.85"))
        self.mapping_coverage_min = float(os.getenv("MAPPING_COVERAGE_GATE_MIN", "0.75"))
        self.unresolved_ratio_max = float(os.getenv("UNRESOLVED_RATIO_MAX", "0.10"))
        self.packet_conf_min = float(os.getenv("COLLEGE_V2_PACKET_CONF_MIN", "0.60"))

    def _phase_timer(self, phase_name: str, timings: Dict[str, float], start: float) -> None:
        timings[phase_name] = round(time.perf_counter() - start, 4)

    def run(
        self,
        exam_id: str,
        exam_questions: List[Dict[str, Any]],
        answer_images: List[str],
        question_paper_pdf_bytes: Optional[bytes] = None,
        failed_chunks: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        timings: Dict[str, float] = {}
        logger.info("[COLLEGE-V2] run start exam_id=%s pages=%s", exam_id, len(answer_images or []))

        # Phase 1: blueprint
        phase_start = time.perf_counter()
        blueprint_payload = assemble_blueprint(
            exam_questions=exam_questions,
            question_paper_pdf_bytes=question_paper_pdf_bytes,
            failed_chunks=failed_chunks,
            completeness_threshold=self.blueprint_threshold,
        )
        self._phase_timer("phase_1_blueprint", timings, phase_start)

        question_blueprint = blueprint_payload.get("question_blueprint", []) or []
        blueprint_health = blueprint_payload.get("blueprint_health", {}) or {}
        blueprint_blockers = blueprint_payload.get("blockers", []) or []

        expected_qids = sorted(
            {
                int(item.get("question_id"))
                for item in question_blueprint
                if item.get("question_id") is not None
            }
        )

        if not question_blueprint:
            gate = {
                "mapping_status": "failed",
                "mapping_fail_reasons": ["empty_blueprint"],
                "mapped_question_ratio": 0.0,
                "mapping_coverage": 0.0,
                "unresolved_questions": expected_qids,
                "low_confidence_questions": [],
                "consistency_flags": ["blueprint_gate_failed"],
                "anchor_confidence_summary": {"min": 0.0, "max": 0.0, "avg": 0.0},
                "table_confidence_summary": {"min": 0.0, "max": 0.0, "avg": 0.0},
                "alignment_confidence_summary": {"min": 0.0, "max": 0.0, "avg": 0.0},
            }
            return CollegePipelineResult(
                question_blueprint=question_blueprint,
                blueprint_health=blueprint_health,
                gate=gate,
                phase_timings=timings,
            ).as_dict()

        if blueprint_blockers:
            gate = {
                "mapping_status": "failed",
                "mapping_fail_reasons": list(blueprint_blockers),
                "mapped_question_ratio": 0.0,
                "mapping_coverage": 0.0,
                "unresolved_questions": expected_qids,
                "low_confidence_questions": [],
                "consistency_flags": ["blueprint_gate_failed"],
                "anchor_confidence_summary": {"min": 0.0, "max": 0.0, "avg": 0.0},
                "table_confidence_summary": {"min": 0.0, "max": 0.0, "avg": 0.0},
                "alignment_confidence_summary": {"min": 0.0, "max": 0.0, "avg": 0.0},
            }
            return CollegePipelineResult(
                question_blueprint=question_blueprint,
                blueprint_health=blueprint_health,
                gate=gate,
                phase_timings=timings,
            ).as_dict()

        # Phase 2: normalization
        phase_start = time.perf_counter()
        clean_pages, preprocess_metrics = normalize_answer_pages(answer_images or [])
        self._phase_timer("phase_2_normalization", timings, phase_start)
        if not clean_pages:
            gate = {
                "mapping_status": "failed",
                "mapping_fail_reasons": ["normalization_failed"],
                "mapped_question_ratio": 0.0,
                "mapping_coverage": 0.0,
                "unresolved_questions": expected_qids,
                "low_confidence_questions": [],
                "consistency_flags": ["normalization_gate_failed"],
                "anchor_confidence_summary": {"min": 0.0, "max": 0.0, "avg": 0.0},
                "table_confidence_summary": {"min": 0.0, "max": 0.0, "avg": 0.0},
                "alignment_confidence_summary": {"min": 0.0, "max": 0.0, "avg": 0.0},
            }
            return CollegePipelineResult(
                question_blueprint=question_blueprint,
                blueprint_health=blueprint_health,
                clean_pages_count=0,
                preprocess_metrics=preprocess_metrics,
                gate=gate,
                phase_timings=timings,
            ).as_dict()

        # Phase 3: layout
        phase_start = time.perf_counter()
        page_layout, layout_flags = detect_page_blocks(clean_pages)
        self._phase_timer("phase_3_layout", timings, phase_start)

        # Phase 4: region OCR
        phase_start = time.perf_counter()
        region_text = extract_region_text(clean_pages, page_layout)
        self._phase_timer("phase_4_region_ocr", timings, phase_start)

        # Phase 5: packet builder
        phase_start = time.perf_counter()
        packets = build_packets(region_text, question_blueprint)
        self._phase_timer("phase_5_packet_builder", timings, phase_start)

        # Phase 6: alignment
        phase_start = time.perf_counter()
        aligned_answers = align_packets_to_blueprint(question_blueprint, packets)
        self._phase_timer("phase_6_alignment", timings, phase_start)

        # Phase 7: structuring
        phase_start = time.perf_counter()
        structured_answers = structure_aligned_answers(aligned_answers)
        self._phase_timer("phase_7_structuring", timings, phase_start)

        # Phase 8: confidence + recovery
        phase_start = time.perf_counter()
        packets, aligned_answers, confidence_vectors = run_recovery(
            question_blueprint,
            packets,
            aligned_answers,
            region_text,
            packet_conf_min=self.packet_conf_min,
        )
        confidence_vectors = compute_confidence_vectors(aligned_answers)
        mapping_coverage = float((packets.get("_meta", {}) or {}).get("mapping_coverage", 0.0) or 0.0)
        gate = build_gate(
            expected_question_ids=expected_qids,
            aligned_answers=aligned_answers,
            confidence_vectors=confidence_vectors,
            mapping_coverage=mapping_coverage,
            mapped_ratio_min=self.mapped_ratio_min,
            mapping_coverage_min=self.mapping_coverage_min,
            unresolved_ratio_max=self.unresolved_ratio_max,
            confidence_min=self.packet_conf_min,
        )
        self._phase_timer("phase_8_confidence_recovery", timings, phase_start)

        # Phase 9 is grading; orchestrator only gates and prepares payload.
        final_output = []
        for row in structured_answers:
            qid = int(row.get("question_id") or 0)
            packet = next((a.get("packet") for a in aligned_answers if int(a.get("question_id") or 0) == qid), None)
            conf = float((packet or {}).get("mapping_confidence", 0.0) or 0.0)
            issues: List[str] = []
            if not packet:
                issues.append("missing_packet")
            elif conf < self.packet_conf_min:
                issues.append("low_mapping_confidence")
            final_output.append(
                {
                    "question_id": qid,
                    "expected": next((q for q in question_blueprint if int(q.get("question_id") or 0) == qid), {}),
                    "student_answer_structured": row.get("structured_answer", {}),
                    "confidence": round(conf, 4),
                    "issues": issues,
                    "aligned_by": row.get("aligned_by"),
                    "packet": packet,
                }
            )

        return CollegePipelineResult(
            question_blueprint=question_blueprint,
            blueprint_health=blueprint_health,
            clean_pages_count=len(clean_pages),
            preprocess_metrics=preprocess_metrics,
            page_layout=page_layout,
            layout_recovery_flags=layout_flags,
            region_text=region_text,
            packets=packets,
            aligned_answers=aligned_answers,
            structured_answers=structured_answers,
            confidence_vectors=confidence_vectors,
            final_output=final_output,
            gate=gate,
            phase_timings=timings,
        ).as_dict()


def pipeline_result_to_question_map(pipeline_result: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    """Convert CollegePipelineV2 output to grading question-map contract."""
    packets = (pipeline_result or {}).get("packets", {}) or {}
    out: Dict[Any, Any] = {}

    for qn, pkt in packets.items():
        if not isinstance(qn, int):
            continue
        text_blocks = pkt.get("text_blocks", []) or []
        segments = [
            {
                "segment_id": blk.get("block_id"),
                "page": blk.get("page_number"),
                "text": blk.get("text", ""),
                "x1": (blk.get("bbox") or [0, 0, 0, 0])[0],
                "y1": (blk.get("bbox") or [0, 0, 0, 0])[1],
                "x2": (blk.get("bbox") or [0, 0, 0, 0])[2],
                "y2": (blk.get("bbox") or [0, 0, 0, 0])[3],
                "tables": [{}] if blk.get("is_table") else [],
                "confidence": float(blk.get("confidence", 0.0) or 0.0),
            }
            for blk in text_blocks
        ]

        out[int(qn)] = {
            "question_number": int(qn),
            "segments": segments,
            "subquestions": {s.get("sub_id"): s.get("segment_ids", []) for s in (pkt.get("subanswers") or []) if s.get("sub_id")},
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

    out["_meta"] = {
        "pipeline": "college_v2",
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
        "phase_timings": (pipeline_result or {}).get("phase_timings", {}),
    }
    return out


def run_college_pipeline_v2(
    exam_id: str,
    exam_questions: List[Dict[str, Any]],
    answer_images: List[str],
    question_paper_pdf_bytes: Optional[bytes] = None,
    failed_chunks: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Any], Dict[int, Dict[str, Any]]]:
    engine = CollegePipelineV2()
    pipeline_result = engine.run(
        exam_id=exam_id,
        exam_questions=exam_questions,
        answer_images=answer_images,
        question_paper_pdf_bytes=question_paper_pdf_bytes,
        failed_chunks=failed_chunks,
    )
    question_map = pipeline_result_to_question_map(pipeline_result)
    return pipeline_result, question_map


__all__ = ["CollegePipelineV2", "run_college_pipeline_v2", "pipeline_result_to_question_map"]
