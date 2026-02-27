"""Debug and maintenance routes."""

from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import datetime, timezone, timedelta
import os
import pickle

from bson import ObjectId

from app.database import db, fs
from app.deps import get_current_user
from app.models.user import User
from app.services.score_normalization import normalize_submission_scores
from app.utils.ocr_provider import get_ocr_provider
from app.config import (
    logger,
)

router = APIRouter(tags=["debug"])

from fastapi import Request


@router.get("/debug/headers")
async def debug_headers(request: Request):
    """Return selected request headers (for diagnosing proxy / devtunnel forwarding)."""
    headers = {
        "origin": request.headers.get("origin"),
        "referer": request.headers.get("referer"),
        "host": request.headers.get("host"),
        "x-forwarded-for": request.headers.get("x-forwarded-for"),
        "x-forwarded-proto": request.headers.get("x-forwarded-proto"),
        "user-agent": request.headers.get("user-agent")
    }
    # indicate whether session cookie arrived (do NOT echo cookie value)
    headers["session_token_cookie_present"] = bool(request.cookies.get("session_token"))
    return {"client": request.client.host if request.client else None, "headers": headers}


@router.post("/debug/force-reextract/{exam_id}")
async def force_reextract_questions(exam_id: str, user: User = Depends(get_current_user)):
    """Force complete re-extraction of ALL questions - deletes old and extracts fresh."""
    from app.services.extraction import auto_extract_questions
    try:
        exam = await db.exams.find_one({"exam_id": exam_id}, {"_id": 0})
        if not exam:
            raise HTTPException(status_code=404, detail="Exam not found")
        
        delete_result = await db.questions.delete_many({"exam_id": exam_id})
        print(f"\n{'='*70}")
        print(f"[FORCE-REEXTRACT] Deleted {delete_result.deleted_count} old questions for {exam_id}")
        
        await db.exams.update_one(
            {"exam_id": exam_id},
            {"$set": {
                "questions": [],
                "questions_count": 0,
                "extraction_source": None,
                "question_extraction_status": "pending",
                "blueprint_status": "pending",
                "blueprint_locked_at": None,
                "blueprint_health": None,
            }}
        )
        
        result = await auto_extract_questions(exam_id, force=True)
        print(f"[FORCE-REEXTRACT] Extraction complete: {result}")
        print(f"{'='*70}\n")
        
        return {
            "success": result.get("success", False),
            "message": result.get("message", ""),
            "deleted_count": delete_result.deleted_count,
            "extracted_count": result.get("count", 0),
            "questions": result.get("count", 0)
        }
    except Exception as e:
        logger.error(f"Force reextraction error: {e}")
        return {"success": False, "message": str(e)}


@router.post("/debug/exams/{exam_id}/backfill-marks")
async def backfill_exam_marks(
    exam_id: str,
    dry_run: bool = Query(False, description="If true, only report changes without writing"),
    user: User = Depends(get_current_user)
):
    """Repair broken score metadata (max marks/totals) for submissions in one exam."""
    exam = await db.exams.find_one(
        {"exam_id": exam_id},
        {"_id": 0, "exam_id": 1, "teacher_id": 1, "questions": 1, "total_marks": 1}
    )
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    if user.role != "admin" and exam.get("teacher_id") != user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    submissions = await db.submissions.find(
        {"exam_id": exam_id},
        {"_id": 0, "submission_id": 1, "question_scores": 1, "total_score": 1, "percentage": 1}
    ).to_list(5000)

    processed_submissions = len(submissions)
    updated_submissions = 0
    updated_questions = 0
    updated_sub_questions = 0
    sample_updated_submission_ids = []

    for submission in submissions:
        normalized = normalize_submission_scores(submission, exam, source="backfill")
        if not normalized["changed"]:
            continue

        updated_submissions += 1
        updated_questions += normalized["updated_questions"]
        updated_sub_questions += normalized["updated_sub_questions"]

        if len(sample_updated_submission_ids) < 20:
            sample_updated_submission_ids.append(submission["submission_id"])

        if not dry_run:
            await db.submissions.update_one(
                {"submission_id": submission["submission_id"]},
                {"$set": {
                    "question_scores": normalized["question_scores"],
                    "total_score": normalized["total_score"],
                    "percentage": normalized["percentage"],
                }}
            )

    return {
        "exam_id": exam_id,
        "processed_submissions": processed_submissions,
        "updated_submissions": updated_submissions,
        "updated_questions": updated_questions,
        "updated_sub_questions": updated_sub_questions,
        "dry_run": dry_run,
        "sample_updated_submission_ids": sample_updated_submission_ids,
    }


@router.get("/debug/exam-questions/{exam_id}")
async def debug_exam_questions(exam_id: str, user: User = Depends(get_current_user)):
    """Debug endpoint to see ALL questions in database for this exam."""
    try:
        db_questions = await db.questions.find({"exam_id": exam_id}, {"_id": 0}).to_list(1000)
        exam = await db.exams.find_one({"exam_id": exam_id}, {"_id": 0, "questions": 1})
        exam_questions = exam.get("questions", []) if exam else []
        
        db_q_numbers = [q.get("question_number") for q in db_questions]
        exam_q_numbers = [q.get("question_number") for q in exam_questions]
        
        return {
            "exam_id": exam_id,
            "database_count": len(db_questions),
            "database_questions": db_q_numbers,
            "database_details": db_questions,
            "exam_count": len(exam_questions),
            "exam_questions": exam_q_numbers,
            "exam_details": exam_questions
        }
    except Exception as e:
        logger.error(f"Debug questions error: {e}")
        return {"error": str(e)}


@router.post("/debug/cleanup")
async def debug_cleanup():
    """EMERGENCY CLEANUP: Cancel all stuck jobs and tasks."""
    try:
        jobs_result = await db.grading_jobs.update_many(
            {"status": {"$in": ["processing", "pending"]}},
            {"$set": {"status": "failed", "error": "Emergency cleanup - manually cancelled", "updated_at": datetime.now(timezone.utc).isoformat()}}
        )
        tasks_result = await db.tasks.update_many(
            {"status": {"$in": ["pending", "processing", "claimed"]}},
            {"$set": {"status": "cancelled"}}
        )
        return {
            "success": True,
            "jobs_cancelled": jobs_result.modified_count,
            "tasks_cancelled": tasks_result.modified_count,
            "message": f"Cleaned up {jobs_result.modified_count} jobs and {tasks_result.modified_count} tasks"
        }
    except Exception as e:
        logger.error(f"Cleanup error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/debug/status")
async def debug_status():
    """Debug endpoint to check worker status, database connectivity, and job queue."""
    debug_info = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "db_name": os.environ.get('DB_NAME', 'NOT_SET'),
            "mongo_url_configured": "MONGO_URL" in os.environ,
            "worker_integrated": True,
        },
        "database": {"connection": "Unknown", "collections": []},
        "jobs": {"pending": 0, "processing": 0, "completed_last_hour": 0, "failed_last_hour": 0, "recent_jobs": []},
        "tasks": {"pending": 0, "processing": 0, "recent_tasks": []}
    }
    
    try:
        await db.command("ping")
        debug_info["database"]["connection"] = "Connected ✅"
        collections = await db.list_collection_names()
        debug_info["database"]["collections"] = collections[:10]
        
        one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        debug_info["jobs"]["pending"] = await db.grading_jobs.count_documents({"status": "pending"})
        debug_info["jobs"]["processing"] = await db.grading_jobs.count_documents({"status": "processing"})
        debug_info["jobs"]["completed_last_hour"] = await db.grading_jobs.count_documents({"status": "completed", "updated_at": {"$gte": one_hour_ago}})
        debug_info["jobs"]["failed_last_hour"] = await db.grading_jobs.count_documents({"status": "failed", "updated_at": {"$gte": one_hour_ago}})
        
        recent_jobs = await db.grading_jobs.find({}, {"_id": 0, "job_id": 1, "status": 1, "total_papers": 1, "processed_papers": 1, "created_at": 1}).sort([("created_at", -1)]).limit(5).to_list(5)
        debug_info["jobs"]["recent_jobs"] = [{"job_id": j.get("job_id"), "status": j.get("status"), "progress": f"{j.get('processed_papers', 0)}/{j.get('total_papers', 0)}"} for j in recent_jobs]
        
        debug_info["tasks"]["pending"] = await db.tasks.count_documents({"status": "pending"})
        debug_info["tasks"]["processing"] = await db.tasks.count_documents({"status": "processing"})
        
    except Exception as e:
        debug_info["error"] = f"Error: {str(e)}"
    
    return debug_info


@router.get("/debug/ocr-structure")
async def debug_ocr_structure(
    submission_id: str,
    user: User = Depends(get_current_user),
):
    """Inspect OCR providers and structured answer segmentation for a submission."""
    from app.layers.ai_structured.engine import preflight_submission_mapping as ai_preflight

    try:
        preflight = await ai_preflight(submission_id=submission_id, user_id=user.user_id)
        preflight["pipeline"] = "ai_structured"
        preflight["debug_view"] = "ocr_structure"
        return preflight
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI-structured debug failed: {exc}")

    submission = await db.submissions.find_one(
        {"submission_id": submission_id},
        {"_id": 0, "submission_id": 1, "exam_id": 1, "file_images": 1, "images_gridfs_id": 1},
    )
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    images = submission.get("file_images") or []
    if not images and submission.get("images_gridfs_id"):
        try:
            images_oid = ObjectId(submission["images_gridfs_id"])
            if fs.exists(images_oid):
                images = pickle.loads(fs.get(images_oid).read())
        except Exception as e:
            logger.error(f"OCR debug image load failed: {e}")

    if not images:
        return {
            "submission_id": submission_id,
            "error": "No submission images available",
            "per_page": [],
            "question_map": {},
        }

    exam = await db.exams.find_one(
        {"exam_id": submission.get("exam_id")},
        {"_id": 0, "questions": 1},
    )
    expected_questions = []
    for q in (exam or {}).get("questions", []):
        try:
            expected_questions.append(int(q.get("question_number")))
        except Exception:
            continue
    expected_questions = sorted(set(expected_questions))

    ocr = get_ocr_provider()
    per_page = []
    segments_by_page = []
    words_by_page = []
    widths = []

    for page_idx, img in enumerate(images):
        res = ocr.detect(img)
        words = res.get("words", []) or []
        lines = res.get("lines", []) or []
        tables = res.get("tables", []) or []
        segments = build_page_segments(words=words, tables=tables, page=page_idx + 1)
        segments_by_page.append(segments)
        words_by_page.append(words)
        widths.append(float(res.get("width", 1000)))
        per_page.append({
            "page": page_idx + 1,
            "provider": res.get("provider"),
            "fallback_used": res.get("fallback_used", False),
            "words": len(words),
            "lines": len(lines),
            "segments": len(segments),
            "tables": len(tables),
            "metrics": res.get("metrics", {}),
        })

    question_map = map_segments_to_questions(
        segments_by_page=segments_by_page,
        words_by_page=words_by_page,
        expected_questions=expected_questions,
        page_widths=widths,
    )
    mapper_page_metrics = {
        int(item.get("page")): item
        for item in ((question_map.get("_meta", {}) or {}).get("per_page", []) or [])
        if isinstance(item, dict) and str(item.get("page", "")).isdigit()
    }
    for pm in per_page:
        enrich = mapper_page_metrics.get(int(pm.get("page", 0)))
        if not enrich:
            continue
        pm["labels_detected"] = int(enrich.get("labels_detected", 0))
        pm["questions_assigned"] = enrich.get("questions_assigned", [])
        pm["questions_assigned_count"] = int(enrich.get("questions_assigned_count", 0))
        pm["sparse"] = bool(enrich.get("sparse", False))

    coverage = sorted([int(k) for k in question_map.keys() if isinstance(k, int)])
    missing = sorted(set(expected_questions) - set(coverage))

    compact_map = {}
    anchor_trace = {}
    packet_trace = {}
    for qn in coverage:
        qd = question_map.get(qn, {})
        compact_map[str(qn)] = {
            "question_number": int(qn),
            "segment_ids": qd.get("segment_ids", []),
            "combined_text_preview": (qd.get("combined_text", "") or "")[:800],
            "page_refs": qd.get("page_refs", []),
            "segment_count": len(qd.get("segments", [])),
            "extracted_text_preview": (qd.get("extracted_text", "") or "")[:800],
            "subquestions": {k: len(v) for k, v in (qd.get("subquestions") or {}).items()},
            "subquestion_count": int(qd.get("subquestion_count", 0) or 0),
            "subanswers": [
                {
                    "sub_id": s.get("sub_id"),
                    "segment_ids": s.get("segment_ids", []),
                    "page_refs": s.get("page_refs", []),
                    "mapping_confidence": float(s.get("mapping_confidence", 0.0) or 0.0),
                }
                for s in (qd.get("subanswers") or [])
            ],
            "table_segments": qd.get("table_segments", []),
            "working_note_segments": qd.get("working_note_segments", []),
            "mapping_confidence": float(qd.get("mapping_confidence", 0.0) or 0.0),
            "mapping_trace": qd.get("mapping_trace", []),
            "start_anchor": qd.get("start_anchor"),
            "end_anchor": qd.get("end_anchor"),
            "sample_segments": [
                {
                    "segment_id": s.get("segment_id"),
                    "page": s.get("page"),
                    "text": (s.get("text", "") or "")[:160],
                }
                for s in (qd.get("segments") or [])[:6]
            ],
        }
        anchor_trace[str(qn)] = {
            "start_anchor": qd.get("start_anchor"),
            "end_anchor": qd.get("end_anchor"),
        }
        packet_trace[str(qn)] = qd.get("mapping_trace", [])

    return {
        "submission_id": submission_id,
        "pages": len(images),
        "expected_questions": expected_questions,
        "detected_questions": coverage,
        "missing_questions": missing,
        "mapping_coverage": float((question_map.get("_meta", {}) or {}).get("mapping_coverage", 0.0) or 0.0),
        "packets_generated": int((question_map.get("_meta", {}) or {}).get("packets_generated", len(coverage)) or len(coverage)),
        "subpacket_count": int((question_map.get("_meta", {}) or {}).get("subpacket_count", 0) or 0),
        "low_confidence_questions": (question_map.get("_meta", {}) or {}).get("low_confidence_questions", []),
        "consistency_flags": (question_map.get("_meta", {}) or {}).get("consistency_flags", []),
        "unresolved_segments": {
            "count": int((question_map.get("_meta", {}) or {}).get("unassigned_region_count", 0) or 0),
            "index_size": len((question_map.get("_meta", {}) or {}).get("page_segment_index", []) or []),
        },
        "anchor_trace": anchor_trace,
        "packet_trace": packet_trace,
        "per_page": per_page,
        "question_map": compact_map,
    }


@router.get("/debug/packet-pipeline/{submission_id}")
async def debug_packet_pipeline(
    submission_id: str,
    user: User = Depends(get_current_user),
):
    """Run full packet pipeline and return stage summaries for one submission."""
    from app.layers.ai_structured.engine import preflight_submission_mapping as ai_preflight

    try:
        preflight = await ai_preflight(submission_id=submission_id, user_id=user.user_id)
        return {
            "submission_id": submission_id,
            "exam_id": preflight.get("exam_id"),
            "pipeline": "ai_structured",
            "mapping_status": preflight.get("mapping_status"),
            "mapping_coverage": preflight.get("mapping_coverage"),
            "mapped_question_ratio": preflight.get("mapped_question_ratio"),
            "unresolved_questions": preflight.get("unresolved_questions", []),
            "fail_reasons": preflight.get("fail_reasons", []),
            "question_coverage_map": preflight.get("question_coverage_map", {}),
            "unmapped_answers": preflight.get("unmapped_answers", []),
            "duplicate_answers": preflight.get("duplicate_answers", []),
            "orphan_pages": preflight.get("orphan_pages", []),
            "answers": preflight.get("answers", []),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI-structured debug failed: {exc}")

    submission = await db.submissions.find_one(
        {"submission_id": submission_id},
        {"_id": 0, "submission_id": 1, "exam_id": 1, "file_images": 1, "images_gridfs_id": 1},
    )
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    images = submission.get("file_images") or []
    if not images and submission.get("images_gridfs_id"):
        try:
            images_oid = ObjectId(submission["images_gridfs_id"])
            if fs.exists(images_oid):
                images = pickle.loads(fs.get(images_oid).read())
        except Exception as e:
            logger.error(f"Packet pipeline image load failed: {e}")

    if not images:
        return {
            "submission_id": submission_id,
            "error": "No submission images available",
        }

    exam = await db.exams.find_one(
        {"exam_id": submission.get("exam_id")},
        {"_id": 0, "exam_id": 1, "exam_type": 1, "questions": 1, "blueprint_health": 1},
    )
    questions = (exam or {}).get("questions", []) or []
    question_paper_pdf_bytes = await get_exam_question_paper_pdf_bytes(submission.get("exam_id"))
    exam_type = str((exam or {}).get("exam_type", "") or "").lower()
    use_universal_v2 = bool(
        False
    )
    use_aws_pipeline = bool(
        exam_type != "upsc"
    )
    use_college_v2 = bool(
        COLLEGE_V2_PIPELINE_ENABLED
        and exam_type != "upsc"
        and not use_universal_v2
        and not use_aws_pipeline
    )

    question_map = None
    if use_universal_v2:
        pipeline, question_map = run_universal_pipeline_v2(
            exam_id=submission.get("exam_id") or "unknown_exam",
            exam_questions=questions,
            answer_images=images,
            question_paper_pdf_bytes=question_paper_pdf_bytes or None,
            failed_chunks=((exam.get("blueprint_health") or {}).get("failed_chunks") or []),
        )
    elif use_aws_pipeline:
        pipeline, question_map = run_aws_pipeline_v3(
            exam_id=submission.get("exam_id") or "unknown_exam",
            exam_questions=questions,
            answer_images=images,
        )
    elif use_college_v2:
        pipeline, question_map = run_college_pipeline_v3(
            exam_id=submission.get("exam_id") or "unknown_exam",
            exam_questions=questions,
            answer_images=images,
            question_paper_pdf_bytes=question_paper_pdf_bytes or None,
            failed_chunks=((exam.get("blueprint_health") or {}).get("failed_chunks") or []),
        )
    else:
        pipeline = run_answer_packet_pipeline(
            answer_images=images,
            questions=questions,
            question_paper_pdf_bytes=question_paper_pdf_bytes or None,
        )

    packets = pipeline.get("packets", {}) or (question_map or {})
    packet_meta = packets.get("_meta", {}) if isinstance(packets, dict) else {}
    gate_meta = (pipeline.get("gate") or {}) if isinstance(pipeline, dict) else {}
    packet_summary = {}
    for qn, pkt in packets.items():
        if not isinstance(qn, int):
            continue
        packet_summary[str(qn)] = {
            "question_id": int(qn),
            "pages": pkt.get("pages", pkt.get("page_refs", [])) if isinstance(pkt, dict) else [],
            "segment_count": len((pkt.get("segment_ids", []) or [])) if isinstance(pkt, dict) else 0,
            "subquestion_count": int(pkt.get("subquestion_count", 0) or 0),
            "table_segments": pkt.get("table_segments", []) if isinstance(pkt, dict) else [],
            "working_note_segments": pkt.get("working_note_segments", []) if isinstance(pkt, dict) else [],
            "mapping_confidence": float(pkt.get("mapping_confidence", 0.0) or 0.0) if isinstance(pkt, dict) else 0.0,
            "mapping_trace": pkt.get("mapping_trace", []) if isinstance(pkt, dict) else [],
            "start_anchor": pkt.get("start_anchor") if isinstance(pkt, dict) else None,
            "end_anchor": pkt.get("end_anchor") if isinstance(pkt, dict) else None,
            "combined_text_preview": (pkt.get("combined_text", "") or "")[:600] if isinstance(pkt, dict) else "",
        }

    final_output = []
    for row in pipeline.get("final_output", []) or []:
        final_output.append(
            {
                "question_id": int(row.get("question_id", 0) or 0),
                "confidence": float(row.get("confidence", 0.0) or 0.0),
                "issues": row.get("issues", []),
                "aligned_by": row.get("aligned_by"),
                "structured_counts": {
                    "accounts": len(
                        (row.get("student_answer_structured") or {}).get("accounts", [])
                        or (row.get("student_answer_structured") or {}).get("ledger_accounts", [])
                    ),
                    "journal_entries": len((row.get("student_answer_structured") or {}).get("journal_entries", [])),
                    "calculations": len(
                        (row.get("student_answer_structured") or {}).get("calculations", [])
                        or (row.get("student_answer_structured") or {}).get("working_formulas", [])
                    ),
                    "totals": len((row.get("student_answer_structured") or {}).get("totals", [])),
                    "reasoning": len(
                        (row.get("student_answer_structured") or {}).get("reasoning", [])
                        or (row.get("student_answer_structured") or {}).get("reasoning_steps", [])
                    ),
                },
            }
        )

    return {
        "submission_id": submission_id,
        "exam_id": submission.get("exam_id"),
        "pipeline": (
            "universal_v2"
            if use_universal_v2
            else ("aws_textract_v3" if use_aws_pipeline else ("college_v3" if use_college_v2 else "legacy_packet"))
        ),
        "aws_raw_layer": (
            {
                "raw_layer_ref": (exam or {}).get("raw_layer_ref"),
                "raw_layer_version": (exam or {}).get("raw_layer_version"),
                "blueprint_spans_raw": (exam or {}).get("blueprint_spans_raw"),
                "blueprint_spans_structured": (exam or {}).get("blueprint_spans_structured"),
                "missing_questions": (exam or {}).get("missing_questions"),
                "uncertain_questions": (exam or {}).get("uncertain_questions"),
                "span_structuring_errors": (exam or {}).get("span_structuring_errors"),
            }
            if use_aws_pipeline
            else None
        ),
        "blueprint_count": len(pipeline.get("question_blueprint", []) or []),
        "layout_pages": len(pipeline.get("page_layout", []) or []),
        "region_count": len(pipeline.get("region_text", []) or []),
        "mapping_status": gate_meta.get("mapping_status", "pass"),
        "mapping_coverage": float(gate_meta.get("mapping_coverage", packet_meta.get("mapping_coverage", 0.0)) or 0.0),
        "mapped_question_ratio": float(gate_meta.get("mapped_question_ratio", 0.0) or 0.0),
        "mapping_fail_reasons": gate_meta.get("mapping_fail_reasons", []),
        "unresolved_questions": gate_meta.get("unresolved_questions", []),
        "packets_generated": int(packet_meta.get("packets_generated", 0) or 0),
        "subpacket_count": int(packet_meta.get("subpacket_count", 0) or 0),
        "low_confidence_questions": gate_meta.get("low_confidence_questions", packet_meta.get("low_confidence_questions", [])),
        "consistency_flags": gate_meta.get("consistency_flags", packet_meta.get("consistency_flags", [])),
        "anchor_confidence_summary": gate_meta.get("anchor_confidence_summary", {}),
        "table_confidence_summary": gate_meta.get("table_confidence_summary", {}),
        "alignment_confidence_summary": gate_meta.get("alignment_confidence_summary", {}),
        "continuity_confidence_summary": gate_meta.get("continuity_confidence_summary", packet_meta.get("continuity_confidence_summary", {})),
        "orphan_block_count": int(gate_meta.get("orphan_block_count", packet_meta.get("orphan_block_count", 0)) or 0),
        "orphan_block_ratio": float(gate_meta.get("orphan_block_ratio", packet_meta.get("orphan_block_ratio", 0.0)) or 0.0),
        "semantic_attach_events": int(packet_meta.get("semantic_attach_events", 0) or 0),
        "table_continuity_events": int(packet_meta.get("table_continuity_events", 0) or 0),
        "continuity_decisions": packet_meta.get("continuity_resolved_blocks", []),
        "confidence_vectors": pipeline.get("confidence_vectors", []),
        "phase_timings": pipeline.get("phase_timings", {}),
        "layout_recovery_flags": pipeline.get("layout_recovery_flags", []),
        "packet_summary": packet_summary,
        "final_output": final_output,
    }


@router.get("/debug/grading-audit/{submission_id}")
async def debug_grading_audit(
    submission_id: str,
    user: User = Depends(get_current_user),
):
    """Return packet-first extraction and confidence traces for grading audit."""
    from app.layers.ai_structured.engine import preflight_submission_mapping as ai_preflight

    try:
        preflight = await ai_preflight(submission_id=submission_id, user_id=user.user_id)
        return {
            "submission_id": submission_id,
            "exam_id": preflight.get("exam_id"),
            "pipeline": "ai_structured",
            "mapping_status": preflight.get("mapping_status"),
            "mapping_coverage": preflight.get("mapping_coverage"),
            "mapped_question_ratio": preflight.get("mapped_question_ratio"),
            "question_packets": {},
            "question_coverage_map": preflight.get("question_coverage_map", {}),
            "unmapped_answers": preflight.get("unmapped_answers", []),
            "duplicate_answers": preflight.get("duplicate_answers", []),
            "orphan_pages": preflight.get("orphan_pages", []),
            "aligned_answers": preflight.get("answers", []),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI-structured debug failed: {exc}")

    submission = await db.submissions.find_one(
        {"submission_id": submission_id},
        {"_id": 0, "submission_id": 1, "exam_id": 1, "file_images": 1, "images_gridfs_id": 1, "question_scores": 1},
    )
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    images = submission.get("file_images") or []
    if not images and submission.get("images_gridfs_id"):
        try:
            images_oid = ObjectId(submission["images_gridfs_id"])
            if fs.exists(images_oid):
                images = pickle.loads(fs.get(images_oid).read())
        except Exception as e:
            logger.error(f"Audit image load failed: {e}")

    if not images:
        return {
            "submission_id": submission_id,
            "error": "No submission images available",
            "question_packets": {},
        }

    exam = await db.exams.find_one(
        {"exam_id": submission.get("exam_id")},
        {"_id": 0, "exam_id": 1, "exam_type": 1, "questions": 1, "blueprint_health": 1},
    )
    expected_questions = []
    for q in (exam or {}).get("questions", []):
        try:
            expected_questions.append(int(q.get("question_number")))
        except Exception:
            continue
    expected_questions = sorted(set(expected_questions))
    exam_type = str((exam or {}).get("exam_type", "") or "").lower()
    use_universal_v2 = bool(
        UNIVERSAL_PIPELINE_ENABLED
        and exam_type in set(UNIVERSAL_PIPELINE_EXAM_TYPES)
        and exam_type != "upsc"
    )
    use_aws_pipeline = bool(
        AWS_PIPELINE_ENABLED
        and exam_type in set(AWS_PIPELINE_EXAM_TYPES)
        and exam_type != "upsc"
        and not use_universal_v2
    )
    use_college_v2 = bool(
        COLLEGE_V2_PIPELINE_ENABLED
        and exam_type != "upsc"
        and not use_universal_v2
        and not use_aws_pipeline
    )

    question_paper_pdf_bytes = await get_exam_question_paper_pdf_bytes(submission.get("exam_id"))
    if use_universal_v2:
        pipeline, question_map = run_universal_pipeline_v2(
            exam_id=submission.get("exam_id") or "unknown_exam",
            exam_questions=(exam or {}).get("questions", []) or [],
            answer_images=images,
            question_paper_pdf_bytes=question_paper_pdf_bytes or None,
            failed_chunks=((exam.get("blueprint_health") or {}).get("failed_chunks") or []),
        )
        per_page = (
            pipeline.get("preprocess_metrics", [])
            if isinstance(pipeline, dict)
            else []
        )
        gate = (pipeline.get("gate") or {}) if isinstance(pipeline, dict) else {}
        aligned_answers = (pipeline.get("aligned_answers") or []) if isinstance(pipeline, dict) else []
    elif use_aws_pipeline:
        pipeline, question_map = run_aws_pipeline_v3(
            exam_id=submission.get("exam_id") or "unknown_exam",
            exam_questions=(exam or {}).get("questions", []) or [],
            answer_images=images,
        )
        per_page = []
        gate = (pipeline.get("gate") or {}) if isinstance(pipeline, dict) else {}
        aligned_answers = []
    elif use_college_v2:
        pipeline, question_map = run_college_pipeline_v3(
            exam_id=submission.get("exam_id") or "unknown_exam",
            exam_questions=(exam or {}).get("questions", []) or [],
            answer_images=images,
            question_paper_pdf_bytes=question_paper_pdf_bytes or None,
            failed_chunks=((exam.get("blueprint_health") or {}).get("failed_chunks") or []),
        )
        per_page = (
            pipeline.get("preprocess_metrics", [])
            if isinstance(pipeline, dict)
            else []
        )
        gate = (pipeline.get("gate") or {}) if isinstance(pipeline, dict) else {}
        aligned_answers = (pipeline.get("aligned_answers") or []) if isinstance(pipeline, dict) else []
    else:
        ocr = get_ocr_provider()
        segments_by_page = []
        words_by_page = []
        widths = []
        per_page = []

        for page_idx, img in enumerate(images):
            res = ocr.detect(img)
            words = res.get("words", []) or []
            lines = res.get("lines", []) or []
            tables = res.get("tables", []) or []
            segments = build_page_segments(words=words, tables=tables, page=page_idx + 1)
            segments_by_page.append(segments)
            words_by_page.append(words)
            widths.append(float(res.get("width", 1000)))
            per_page.append(
                {
                    "page": page_idx + 1,
                    "provider": res.get("provider"),
                    "fallback_used": bool(res.get("fallback_used", False)),
                    "words": len(words),
                    "lines": len(lines),
                    "segments": len(segments),
                    "tables": len(tables),
                }
            )

        question_map = map_segments_to_questions(
            segments_by_page=segments_by_page,
            words_by_page=words_by_page,
            expected_questions=expected_questions,
            page_widths=widths,
        )
        gate = {}
        aligned_answers = []

    packets = {}
    detected_questions = sorted([int(k) for k in question_map.keys() if isinstance(k, int)])
    for qn in detected_questions:
        qd = question_map.get(qn, {})
        packets[str(qn)] = {
            "question_number": int(qn),
            "segment_ids": qd.get("segment_ids", []),
            "page_refs": qd.get("page_refs", []),
            "subquestion_count": int(qd.get("subquestion_count", 0) or 0),
            "subanswers": qd.get("subanswers", []),
            "table_segments": qd.get("table_segments", []),
            "working_note_segments": qd.get("working_note_segments", []),
            "mapping_confidence": float(qd.get("mapping_confidence", 0.0) or 0.0),
            "mapping_trace": qd.get("mapping_trace", []),
            "start_anchor": qd.get("start_anchor"),
            "end_anchor": qd.get("end_anchor"),
            "combined_text_preview": (qd.get("combined_text", "") or "")[:1000],
        }

    meta = question_map.get("_meta", {}) or {}
    return {
        "submission_id": submission_id,
        "exam_id": submission.get("exam_id"),
        "pipeline": (
            "universal_v2"
            if use_universal_v2
            else ("aws_textract_v3" if use_aws_pipeline else ("college_v3" if use_college_v2 else "legacy_mapper"))
        ),
        "expected_questions": expected_questions,
        "detected_questions": detected_questions,
        "missing_questions": sorted(set(expected_questions) - set(detected_questions)),
        "mapping_status": gate.get("mapping_status", meta.get("mapping_status", "pass")),
        "mapping_fail_reasons": gate.get("mapping_fail_reasons", meta.get("mapping_fail_reasons", [])),
        "mapping_coverage": float(gate.get("mapping_coverage", meta.get("mapping_coverage", 0.0)) or 0.0),
        "mapped_question_ratio": float(gate.get("mapped_question_ratio", meta.get("mapped_question_ratio", 0.0)) or 0.0),
        "packets_generated": int(meta.get("packets_generated", len(detected_questions)) or len(detected_questions)),
        "subpacket_count": int(meta.get("subpacket_count", 0) or 0),
        "low_confidence_questions": gate.get("low_confidence_questions", meta.get("low_confidence_questions", [])),
        "consistency_flags": gate.get("consistency_flags", meta.get("consistency_flags", [])),
        "anchor_confidence_summary": gate.get("anchor_confidence_summary", meta.get("anchor_confidence_summary", {})),
        "table_confidence_summary": gate.get("table_confidence_summary", meta.get("table_confidence_summary", {})),
        "alignment_confidence_summary": gate.get("alignment_confidence_summary", meta.get("alignment_confidence_summary", {})),
        "continuity_confidence_summary": gate.get("continuity_confidence_summary", meta.get("continuity_confidence_summary", {})),
        "orphan_block_count": int(gate.get("orphan_block_count", meta.get("orphan_block_count", 0)) or 0),
        "orphan_block_ratio": float(gate.get("orphan_block_ratio", meta.get("orphan_block_ratio", 0.0)) or 0.0),
        "semantic_attach_events": int(meta.get("semantic_attach_events", 0) or 0),
        "table_continuity_events": int(meta.get("table_continuity_events", 0) or 0),
        "continuity_decisions": meta.get("continuity_resolved_blocks", []),
        "question_packets": packets,
        "aligned_answers": [
            {
                "question_id": int(row.get("question_id", 0) or 0),
                "packet_id": row.get("packet_id") or ((row.get("packet") or {}).get("packet_id")),
                "aligned_by": row.get("aligned_by"),
                "alignment_confidence": float(row.get("alignment_confidence", 0.0) or 0.0),
            }
            for row in (aligned_answers or [])
        ],
        "question_scores_count": len(submission.get("question_scores") or []),
        "per_page": per_page,
    }
