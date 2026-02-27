"""College_v3 pipeline orchestrator (Vision OCR, global spans, hybrid continuity)."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from app.config import logger
from app.utils.blueprint import compute_blueprint_health

from .anchor_detection import detect_anchors
from .answer_mapping import map_answers
from .global_span_builder import build_global_spans
from .question_blueprint import build_blueprint_from_spans
from .vision_ocr import ocr_pages


def _phase_timer(phase_name: str, timings: Dict[str, float], start: float) -> None:
    timings[phase_name] = round(time.perf_counter() - start, 4)


def _build_question_map(
    mapping: Dict[str, Any],
    expected_questions: List[int],
    answer_pages: List[Dict[str, Any]],
) -> Dict[int, Dict[str, Any]]:
    buckets: Dict[int, List[Dict[str, Any]]] = mapping.get("question_page_buckets", {}) or {}
    question_confidence: Dict[int, float] = mapping.get("question_confidence", {}) or {}
    out: Dict[int, Dict[str, Any]] = {}

    page_segment_index: List[Dict[str, Any]] = []

    for qn in expected_questions:
        entries = buckets.get(int(qn), [])
        segments: List[Dict[str, Any]] = []
        for idx, entry in enumerate(entries):
            seg_id = f"q{qn}_p{entry.get('page')}_{idx}"
            seg = {
                "segment_id": seg_id,
                "page": int(entry.get("page") or 1),
                "text": entry.get("text", "") or "",
                "x1": None,
                "y1": None,
                "x2": None,
                "y2": None,
                "tables": [],
            }
            segments.append(seg)
            page_segment_index.append({
                "segment_id": seg_id,
                "page": int(entry.get("page") or 1),
                "text": (entry.get("text", "") or "")[:600],
                "x1": None,
                "y1": None,
                "x2": None,
                "y2": None,
            })
        page_refs = sorted({int(e.get("page") or 1) for e in entries})
        combined_text = " ".join((e.get("text") or "").strip() for e in entries).strip()
        mapping_trace = [
            {
                "page": int(e.get("page") or 1),
                "attached_by": e.get("attached_by"),
                "continuity_score": float(e.get("continuity_score") or 0.0),
            }
            for e in entries
        ]
        out[int(qn)] = {
            "question_number": int(qn),
            "segments": segments,
            "subquestions": {},
            "subanswers": [],
            "page_refs": page_refs,
            "tables": [],
            "table_segments": [],
            "working_note_segments": [],
            "segment_ids": [s.get("segment_id") for s in segments if s.get("segment_id")],
            "combined_text": combined_text,
            "extracted_text": combined_text,
            "subquestion_count": 0,
            "mapping_confidence": float(question_confidence.get(int(qn), 0.0) or 0.0),
            "mapping_trace": mapping_trace,
            "start_anchor": None,
            "end_anchor": None,
        }

    assigned_pages = sorted({int(e.get("page") or 1) for entries in buckets.values() for e in entries})
    total_pages = len(answer_pages)
    mapping_coverage = len(assigned_pages) / float(total_pages) if total_pages else 0.0
    orphan_pages = mapping.get("orphan_pages", []) or []
    continuation_merges = mapping.get("continuation_merges", []) or []
    orphan_ratio = len(orphan_pages) / float(total_pages) if total_pages else 0.0

    out["_meta"] = {
        "pipeline": "college_v3",
        "mapping_status": mapping.get("mapping_status", "needs_review"),
        "mapping_fail_reasons": mapping.get("mapping_fail_reasons", []),
        "mapping_coverage": round(mapping_coverage, 4),
        "mapped_question_ratio": mapping.get("mapped_question_ratio", 0.0),
        "unresolved_questions": mapping.get("missing_questions", []),
        "packets_generated": len([k for k in out.keys() if isinstance(k, int)]),
        "subpacket_count": 0,
        "low_confidence_questions": mapping.get("low_confidence_questions", []),
        "consistency_flags": [],
        "page_segment_index": page_segment_index,
        "continuity_confidence": mapping.get("continuity_confidence", 0.0),
        "mapping_confidence": mapping.get("mapping_confidence", 0.0),
        "anchor_presence_weight": mapping.get("anchor_presence_weight", 0.0),
        "spatial_alignment_weight": mapping.get("spatial_alignment_weight", 0.0),
        "semantic_similarity_weight": mapping.get("semantic_similarity_weight", 0.0),
        "continuity_consistency": mapping.get("continuity_consistency", 0.0),
        "continuity_confidence_summary": {
            "avg": mapping.get("continuity_confidence", 0.0),
        },
        "orphan_block_count": len(orphan_pages),
        "orphan_block_ratio": round(orphan_ratio, 4),
        "semantic_attach_events": len(continuation_merges),
        "table_continuity_events": 0,
        "continuity_resolved_blocks": continuation_merges,
        "question_page_buckets": buckets,
        "answer_pages": answer_pages,
        "continuation_merges": continuation_merges,
    }
    return out


async def extract_college_v3_blueprint(question_paper_images: List[str]) -> Dict[str, Any]:
    """Run question paper OCR + global spans to extract blueprint for college_v3."""
    timings: Dict[str, float] = {}
    phase_start = time.perf_counter()
    blueprint_pages = ocr_pages(question_paper_images)
    _phase_timer("phase_1_qp_ocr", timings, phase_start)

    phase_start = time.perf_counter()
    anchors = detect_anchors(blueprint_pages)
    spans = build_global_spans(blueprint_pages, anchors, level_filter="question")
    _phase_timer("phase_2_span_build", timings, phase_start)

    phase_start = time.perf_counter()
    blueprint_payload = await build_blueprint_from_spans(spans)
    _phase_timer("phase_3_blueprint_llm", timings, phase_start)

    return {
        "questions": blueprint_payload.get("questions", []),
        "blueprint_pages": blueprint_pages,
        "global_anchor_list": anchors,
        "question_spans": spans,
        "blueprint_question_pages": blueprint_payload.get("blueprint_question_pages", {}),
        "blueprint_health": blueprint_payload.get("blueprint_health", {}),
        "blockers": blueprint_payload.get("blockers", []),
        "phase_timings": timings,
    }


def run_college_pipeline_v3(
    *,
    exam_id: str,
    exam_questions: List[Dict[str, Any]],
    answer_images: List[str],
    question_paper_pdf_bytes: Optional[bytes] = None,
    failed_chunks: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Any], Dict[int, Dict[str, Any]]]:
    """College v3 grading pipeline (mapping + gates)."""
    timings: Dict[str, float] = {}
    logger.info("[COLLEGE-V3] run start exam_id=%s pages=%s", exam_id, len(answer_images or []))

    expected_questions = sorted(
        {
            int(q.get("question_number"))
            for q in (exam_questions or [])
            if q.get("question_number") is not None and str(q.get("question_number", "")).isdigit()
        }
    )

    phase_start = time.perf_counter()
    answer_pages = ocr_pages(answer_images or [])
    _phase_timer("phase_1_answer_ocr", timings, phase_start)

    phase_start = time.perf_counter()
    mapping = map_answers(answer_pages, expected_questions)
    _phase_timer("phase_2_mapping", timings, phase_start)

    blueprint_health = compute_blueprint_health(
        exam_questions,
        expected_count=len(expected_questions) if expected_questions else None,
        failed_chunks=failed_chunks,
    )

    gate = {
        "mapping_status": mapping.get("mapping_status", "needs_review"),
        "mapping_fail_reasons": mapping.get("mapping_fail_reasons", []),
        "mapped_question_ratio": mapping.get("mapped_question_ratio", 0.0),
        "mapping_coverage": None,
        "unresolved_questions": mapping.get("missing_questions", []),
        "low_confidence_questions": mapping.get("low_confidence_questions", []),
        "continuity_confidence": mapping.get("continuity_confidence", 0.0),
        "mapping_confidence": mapping.get("mapping_confidence", 0.0),
        "orphan_pages": mapping.get("orphan_pages", []),
    }

    question_map = _build_question_map(mapping, expected_questions, answer_pages)
    gate["mapping_coverage"] = (question_map.get("_meta", {}) or {}).get("mapping_coverage", 0.0)

    pipeline_result = {
        "blueprint_health": blueprint_health,
        "answer_pages": answer_pages,
        "mapping": mapping,
        "gate": gate,
        "phase_timings": timings,
    }
    return pipeline_result, question_map


__all__ = [
    "extract_college_v3_blueprint",
    "run_college_pipeline_v3",
]
