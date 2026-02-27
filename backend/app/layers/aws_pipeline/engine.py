"""AWS Textract pipeline orchestrator (raw freeze, span evidence, UUID mapping)."""

from __future__ import annotations

import time
import base64
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

from app.config import logger
from app.database import db
from app.utils.blueprint import compute_blueprint_health

from PIL import Image

from .s3_storage import upload_pdf_to_s3
from .textract_client import start_document_analysis, poll_document_analysis
from .text_reconstruction import rebuild_page_text
from .layout_segmentation import build_span_graph
from .raw_layer import save_raw_textract_layer, load_raw_textract_layer
from .blueprint_builder import build_span_evidence, build_blueprint_from_spans
from .answer_extractor import extract_answer_pages
from .answer_mapper import map_answers

LAYOUT_SEGMENTATION_VERSION = 2


def _phase_timer(phase_name: str, timings: Dict[str, float], start: float) -> None:
    timings[phase_name] = round(time.perf_counter() - start, 4)


def _build_question_map(
    mapping: Dict[str, Any],
    question_blueprint: List[Dict[str, Any]],
    answer_pages: List[Dict[str, Any]],
) -> Dict[Any, Dict[str, Any]]:
    buckets_by_uuid: Dict[str, List[Dict[str, Any]]] = mapping.get("question_page_buckets", {}) or {}
    out: Dict[Any, Dict[str, Any]] = {}

    for q in question_blueprint or []:
        q_uuid = q.get("question_uuid")
        q_num = q.get("question_number")
        entries = buckets_by_uuid.get(q_uuid, []) if q_uuid else []
        segments: List[Dict[str, Any]] = []
        for idx, entry in enumerate(entries):
            seg_id = f"{q_uuid}_p{entry.get('page')}_{idx}"
            seg = {
                "segment_id": seg_id,
                "page": int(entry.get("page") or 1),
                "text": entry.get("text", "") or "",
                "tables": [],
                "x1": None,
                "y1": None,
                "x2": None,
                "y2": None,
            }
            segments.append(seg)
        combined_text = " ".join((e.get("text") or "").strip() for e in entries).strip()
        out[q_num] = {
            "question_number": q_num,
            "question_uuid": q_uuid,
            "segments": segments,
            "subquestions": {},
            "subanswers": [],
            "page_refs": sorted({int(e.get("page") or 1) for e in entries}),
            "tables": [],
            "table_segments": [],
            "working_note_segments": [],
            "segment_ids": [s.get("segment_id") for s in segments if s.get("segment_id")],
            "combined_text": combined_text,
            "extracted_text": combined_text,
            "subquestion_count": 0,
            "mapping_confidence": mapping.get("mapping_confidence", 0.0),
            "mapping_trace": [
                {
                    "page": int(e.get("page") or 1),
                    "attached_by": e.get("attached_by"),
                    "continuity_score": float(e.get("continuity_score") or 0.0),
                }
                for e in entries
            ],
            "start_anchor": None,
            "end_anchor": None,
        }

    total_pages = len(answer_pages)
    assigned_pages = sorted({int(e.get("page") or 1) for entries in buckets_by_uuid.values() for e in entries})
    mapping_coverage = len(assigned_pages) / float(total_pages) if total_pages else 0.0

    out["_meta"] = {
        "pipeline": "aws_textract_v3",
        "mapping_status": mapping.get("mapping_status", "partial"),
        "mapping_fail_reasons": mapping.get("mapping_fail_reasons", []),
        "mapping_coverage": round(mapping_coverage, 4),
        "mapped_question_ratio": mapping.get("mapping_confidence", 0.0),
        "unresolved_questions": [],
        "packets_generated": len([k for k in out.keys() if k != "_meta"]),
        "subpacket_count": 0,
        "low_confidence_questions": [],
        "consistency_flags": [],
        "page_segment_index": [],
        "continuity_confidence": mapping.get("continuity_confidence", 0.0),
        "mapping_confidence": mapping.get("mapping_confidence", 0.0),
        "orphan_block_count": len(mapping.get("orphan_pages", []) or []),
        "orphan_block_ratio": 0.0,
        "orphan_pages": mapping.get("orphan_pages", []),
        "question_page_buckets": buckets_by_uuid,
        "answer_pages": answer_pages,
        "continuation_merges": mapping.get("continuation_merges", []),
    }
    return out


async def extract_aws_blueprint(*, exam_id: str, question_paper_pdf_bytes: bytes) -> Dict[str, Any]:
    timings: Dict[str, float] = {}
    phase_start = time.perf_counter()

    if not question_paper_pdf_bytes:
        return {
            "questions": [],
            "blueprint_status": "draft_partial",
            "message": "Missing question paper PDF bytes",
            "blueprint_health": {},
            "phase_timings": {},
        }

    existing_exam = await db.exams.find_one(
        {"exam_id": exam_id},
        {
            "_id": 0,
            "blueprint_spans_raw": 1,
            "page_texts": 1,
            "anchors_detected": 1,
            "textract_job_id": 1,
            "layout_segmentation_version": 1,
        },
    ) or {}
    cached_spans = existing_exam.get("blueprint_spans_raw") or []
    cached_has_graph = any((span.get("span_graph") or span.get("span_type")) for span in cached_spans)
    cached_layout_version = int(existing_exam.get("layout_segmentation_version") or 0)
    cache_valid = cached_spans and cached_has_graph and cached_layout_version >= LAYOUT_SEGMENTATION_VERSION
    if cache_valid:
        logger.info("[AWS] Using cached raw spans for exam %s", exam_id)
        spans_with_evidence = cached_spans
        page_texts = existing_exam.get("page_texts", []) or []
        anchors = existing_exam.get("anchors_detected", []) or []
        job_id = existing_exam.get("textract_job_id")
        spans = [
            {k: v for k, v in span.items() if k != "span_evidence"}
            for span in spans_with_evidence
        ]
    elif cached_spans:
        logger.info(
            "[AWS] Rebuilding spans from raw layer for exam %s (cache graph=%s version=%s)",
            exam_id,
            cached_has_graph,
            cached_layout_version,
        )
        raw_layer = await load_raw_textract_layer(exam_id)
        raw_lines = raw_layer.get("raw_line_positions") or []
        raw_pages = raw_layer.get("raw_page_text") or []
        job_id = raw_layer.get("textract_job_id") or existing_exam.get("textract_job_id")
        span_graph = build_span_graph(line_positions=raw_lines)
        spans = span_graph.get("spans", [])
        anchors = span_graph.get("anchors", [])
        spans_with_evidence = build_span_evidence(spans)
        page_texts = raw_pages or existing_exam.get("page_texts", []) or []
        logger.info("SPAN_EVIDENCE_CREATED exam_id=%s spans=%s", exam_id, len(spans_with_evidence))
    else:
        s3_info = upload_pdf_to_s3(exam_id=exam_id, pdf_bytes=question_paper_pdf_bytes, prefix="textract/question_paper")
        job_id = start_document_analysis(bucket=s3_info["bucket"], key=s3_info["key"])
        resp = poll_document_analysis(job_id)

        if resp.get("status") not in ("SUCCEEDED", "PARTIAL_SUCCESS"):
            return {
                "questions": [],
                "blueprint_status": "draft_partial",
                "message": resp.get("error") or "Textract failed",
                "blueprint_health": {},
                "phase_timings": {},
            }

        blocks = resp.get("blocks") or []
        rebuild = rebuild_page_text(blocks)
        page_texts = rebuild.get("page_texts", [])
        line_positions = rebuild.get("line_positions", [])
        tables = rebuild.get("tables", {})

        span_graph = build_span_graph(line_positions=line_positions)
        spans = span_graph.get("spans", [])
        anchors = span_graph.get("anchors", [])

        await save_raw_textract_layer(
            exam_id=exam_id,
            blocks=blocks,
            page_texts=page_texts,
            tables=tables,
            anchors=anchors,
            line_positions=line_positions,
            textract_job_id=job_id,
        )

        spans_with_evidence = build_span_evidence(spans)
        logger.info("SPAN_EVIDENCE_CREATED exam_id=%s spans=%s", exam_id, len(spans_with_evidence))
    _phase_timer("phase_1_textract", timings, phase_start)

    phase_start = time.perf_counter()
    blueprint_payload = await build_blueprint_from_spans(spans)
    logger.info("BLUEPRINT_DERIVED_FROM_RAW exam_id=%s", exam_id)
    _phase_timer("phase_2_blueprint_llm", timings, phase_start)

    questions = blueprint_payload.get("questions") or []
    health = compute_blueprint_health(questions)
    numbering_gaps = blueprint_payload.get("numbering_gaps", []) or []
    uncertain = [q for q in questions if q.get("source") == "fallback_span"]

    blueprint_status = "draft_complete"
    if numbering_gaps or uncertain or not questions:
        blueprint_status = "draft_partial"
        logger.info("BLUEPRINT_PARTIAL_CREATED exam_id=%s", exam_id)

    return {
        "questions": questions,
        "blueprint_status": blueprint_status,
        "blueprint_pages": page_texts,
        "global_anchor_list": anchors,
        "blueprint_spans_raw": spans_with_evidence,
        "blueprint_spans_structured": blueprint_payload.get("blueprint_spans_structured", []),
        "missing_questions": numbering_gaps,
        "uncertain_questions": [q.get("question_uuid") for q in uncertain],
        "numbering_gaps": numbering_gaps,
        "duplicate_numbers": blueprint_payload.get("duplicate_numbers", []),
        "probable_optional_groups": blueprint_payload.get("probable_optional_groups", []),
        "anchor_confidence_map": {
            str((a.get("text_snippet") or a.get("text") or f"anchor_{idx}")): a.get("confidence")
            for idx, a in enumerate(anchors or [])
            if (a.get("text_snippet") or a.get("text"))
        },
        "span_previews": [s.get("preview_text") for s in spans_with_evidence],
        "blueprint_health": health,
        "span_structuring_errors": blueprint_payload.get("span_structuring_errors", []),
        "textract_job_id": job_id,
        "page_texts": page_texts,
        "anchors_detected": anchors,
        "spans_built": spans_with_evidence,
        "phase_timings": timings,
        "layout_segmentation_version": LAYOUT_SEGMENTATION_VERSION,
    }


def _images_to_pdf_bytes(images: List[str]) -> bytes:
    if not images:
        return b""
    pil_images: List[Image.Image] = []
    for img_b64 in images:
        raw = base64.b64decode(img_b64)
        pil = Image.open(BytesIO(raw)).convert("RGB")
        pil_images.append(pil)
    first, rest = pil_images[0], pil_images[1:]
    buf = BytesIO()
    first.save(buf, format="PDF", save_all=True, append_images=rest)
    return buf.getvalue()


def run_aws_pipeline_v3(
    *,
    exam_id: str,
    exam_questions: List[Dict[str, Any]],
    answer_pdf_bytes: Optional[bytes] = None,
    answer_images: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], Dict[Any, Dict[str, Any]]]:
    timings: Dict[str, float] = {}
    logger.info("[AWS] run start exam_id=%s", exam_id)

    phase_start = time.perf_counter()
    # Extract answers
    if not answer_pdf_bytes and answer_images:
        answer_pdf_bytes = _images_to_pdf_bytes(answer_images)

    if answer_pdf_bytes:
        answer_payload = extract_answer_pages(exam_id=exam_id, pdf_bytes=answer_pdf_bytes)
    else:
        answer_payload = {"status": "failed", "answer_pages": [], "answer_anchors": []}
    _phase_timer("phase_1_answer_extract", timings, phase_start)

    answer_pages = answer_payload.get("answer_pages", [])
    answer_anchors = answer_payload.get("answer_anchors", [])

    phase_start = time.perf_counter()
    mapping = map_answers(
        answer_pages=answer_pages,
        answer_anchors=answer_anchors,
        question_blueprint=exam_questions,
    )
    _phase_timer("phase_2_mapping", timings, phase_start)

    gate = {
        "mapping_status": mapping.get("mapping_status", "partial"),
        "mapping_fail_reasons": mapping.get("mapping_fail_reasons", []),
        "mapping_confidence": mapping.get("mapping_confidence", 0.0),
        "continuity_confidence": mapping.get("continuity_confidence", 0.0),
        "orphan_pages": mapping.get("orphan_pages", []),
    }

    question_map = _build_question_map(mapping, exam_questions, answer_pages)

    pipeline_result = {
        "answer_pages": answer_pages,
        "mapping": mapping,
        "gate": gate,
        "phase_timings": timings,
    }

    return pipeline_result, question_map


__all__ = ["extract_aws_blueprint", "run_aws_pipeline_v3"]
