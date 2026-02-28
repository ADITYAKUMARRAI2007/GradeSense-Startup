"""Grading routes - start grading, job status, cancel, regrade."""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from datetime import datetime, timezone
from typing import List
import uuid
import asyncio
import pickle
import json

from bson import ObjectId

from app.database import db, fs
from app.deps import get_current_user
from app.models.user import User
from app.utils.serialization import serialize_doc
from app.services.gridfs_helpers import get_exam_model_answer_images
from app.services.score_normalization import normalize_submission_scores
from app.config import (
    COLLEGE_V2_HARD_STOP,
    UNIVERSAL_HARD_STOP,
    UNIVERSAL_PIPELINE_ENABLED,
    UNIVERSAL_PIPELINE_EXAM_TYPES,
    logger,
)
from app.utils.blueprint import (
    build_blueprint_freeze_payload,
    evaluate_blueprint_lock_readiness,
)

router = APIRouter(tags=["grading"])


def _is_valid_answer_pdf(filename: str, payload: bytes) -> bool:
    name = str(filename or "").strip().lower()
    if not name.endswith(".pdf"):
        return False
    if not payload or not payload.startswith(b"%PDF"):
        return False
    blocked_name_tokens = ("resume", "cv", "curriculum_vitae", "curriculum-vitae")
    return not any(token in name for token in blocked_name_tokens)


def _format_blueprint_lock_failure(exam: dict, readiness: dict, context: str) -> dict:
    health = readiness.get("health") or {}
    issues = readiness.get("issues") or []
    return {
        "message": (
            f"Cannot start {context}: blueprint is not locked. "
            "Fix blueprint health, lock blueprint, then retry."
        ),
        "required_action": "Review blueprint health, fix missing/duplicate questions, then lock blueprint.",
        "blueprint_status": exam.get("blueprint_status", "pending"),
        "blueprint_health": health,
        "missing_question_numbers": health.get("missing", []),
        "duplicate_question_numbers": health.get("duplicates", []),
        "lock_blockers": issues,
    }


async def _ensure_locked_blueprint_or_raise(exam: dict, exam_id: str, context: str) -> dict:
    processing_state = str(exam.get("processing_state") or "idle").lower()
    if processing_state != "idle":
        raise HTTPException(
            status_code=409,
            detail=f"Exam is currently in '{processing_state}' state. Retry after current pipeline stage completes.",
        )

    status = str(exam.get("blueprint_status", "pending")).lower()
    if bool(exam.get("blueprint_locked")) or status == "ready_locked":
        return exam

    # Removed 409 check - allow grading even during extraction
    # extraction_status = str(exam.get("question_extraction_status", "")).lower()
    # if exam.get("question_paper_processing") or extraction_status == "processing":
    #     raise HTTPException(
    #         status_code=409,
    #         detail="Question paper extraction is still in progress. Wait until it finishes, then grade.",
    #     )

    readiness = evaluate_blueprint_lock_readiness(exam, questions=exam.get("questions") or [])
    health = readiness.get("health") or {}
    exam_type = str(exam.get("exam_type", "") or "").lower()
    universal_active = bool(
        UNIVERSAL_PIPELINE_ENABLED
        and exam_type in set(UNIVERSAL_PIPELINE_EXAM_TYPES)
        and exam_type != "upsc"
    )
    if exam_type == "college" and COLLEGE_V2_HARD_STOP:
        raise HTTPException(
            status_code=409,
            detail={
                **_format_blueprint_lock_failure(exam, readiness, context=context),
                "required_action": "Lock blueprint explicitly from exam settings before grading college papers.",
            },
        )
    if universal_active and UNIVERSAL_HARD_STOP:
        raise HTTPException(
            status_code=409,
            detail={
                **_format_blueprint_lock_failure(exam, readiness, context=context),
                "required_action": "Lock blueprint explicitly before running universal grading.",
            },
        )

    if not readiness.get("can_lock"):
        raise HTTPException(
            status_code=409,
            detail=_format_blueprint_lock_failure(exam, readiness, context=context),
        )

    freeze_payload = build_blueprint_freeze_payload(exam)
    if int(freeze_payload.get("question_count", 0) or 0) <= 0:
        raise HTTPException(
            status_code=409,
            detail={
                **_format_blueprint_lock_failure(exam, readiness, context=context),
                "required_action": "Blueprint has no valid normalized questions. Re-extract questions before grading.",
            },
        )

    now = datetime.now(timezone.utc).isoformat()
    current_version = int(exam.get("blueprint_version", 0) or 0)
    new_version = current_version + 1

    lock_result = await db.exams.update_one(
        {
            "exam_id": exam_id,
            "blueprint_version": current_version,
            "$or": [{"blueprint_locked": {"$exists": False}}, {"blueprint_locked": False}],
        },
        {"$set": {
            "blueprint_status": "ready_locked",
            "blueprint_locked": True,
            "blueprint_locked_at": now,
            "blueprint_version": new_version,
            "blueprint_health": health,
            "question_structure_v2": freeze_payload["question_structure_v2"],
            "active_structure_hash": freeze_payload["structure_hash"],
            "effective_total_marks": freeze_payload["effective_total_marks"],
            "or_groups_map": freeze_payload["or_groups_map"],
            "attempt_rules": freeze_payload["attempt_rules"],
            "structure_confidence": freeze_payload["structure_confidence"],
            "locked_at": now,
        }},
    )

    if lock_result.modified_count == 0:
        latest_exam = await db.exams.find_one({"exam_id": exam_id}, {"_id": 0})
        if latest_exam and (bool(latest_exam.get("blueprint_locked")) or str(latest_exam.get("blueprint_status", "")).lower() == "ready_locked"):
            return latest_exam
        raise HTTPException(status_code=409, detail=f"Could not lock blueprint for {context}; exam state changed.")

    snapshot_doc = {
        "exam_id": exam_id,
        "blueprint_version": new_version,
        "structure_hash": freeze_payload["structure_hash"],
        "question_count": freeze_payload["question_count"],
        "effective_total_marks": freeze_payload["effective_total_marks"],
        "or_groups_map": freeze_payload["or_groups_map"],
        "attempt_rules": freeze_payload["attempt_rules"],
        "locked_at": now,
        "question_structure_v2": freeze_payload["question_structure_v2"],
        "validation_report": {"health": health},
        "structure_confidence": freeze_payload["structure_confidence"],
        "model_name": exam.get("model_name"),
        "prompt_version": exam.get("prompt_version"),
        "pipeline_version": exam.get("pipeline_version"),
        "extraction_hash": exam.get("extraction_hash"),
        "created_at": now,
    }
    snapshot_write = await db.exam_blueprint_versions.update_one(
        {"exam_id": exam_id, "blueprint_version": new_version},
        {"$setOnInsert": snapshot_doc},
        upsert=True,
    )
    if snapshot_write.upserted_id is not None:
        logger.info(
            "BLUEPRINT_VERSION_CREATED exam_id=%s version=%s structure_hash=%s",
            exam_id,
            new_version,
            freeze_payload["structure_hash"],
        )

    realign_update = await db.submissions.update_many(
        {
            "exam_id": exam_id,
            "$or": [
                {"blueprint_version_used": {"$exists": False}},
                {"blueprint_version_used": {"$ne": new_version}},
            ],
        },
        {"$set": {"realign_required": True}},
    )
    if int(realign_update.modified_count or 0) > 0:
        logger.info(
            "REALIGN_REQUIRED exam_id=%s version=%s affected_submissions=%s",
            exam_id,
            new_version,
            int(realign_update.modified_count or 0),
        )

    logger.info("OR_RULES_FROZEN exam_id=%s version=%s", exam_id, new_version)
    logger.info("BLUEPRINT_LOCKED exam_id=%s version=%s source=auto", exam_id, new_version)
    latest_exam = await db.exams.find_one({"exam_id": exam_id}, {"_id": 0})
    return latest_exam or exam


@router.post("/exams/{exam_id}/grade-papers-bg")
async def grade_papers_background(
    exam_id: str,
    files: List[UploadFile] = File(...),
    user: User = Depends(get_current_user)
):
    """Start background grading job using in-memory file bytes"""
    from app.services.grading import process_grading_job_in_background

    try:
        logger.info(f"=== GRADE PAPERS BG START === User: {user.user_id}, Exam: {exam_id}, Files: {len(files)}")

        if user.role != "teacher":
            raise HTTPException(status_code=403, detail="Only teachers can upload papers")

        exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id}, {"_id": 0})
        if not exam:
            raise HTTPException(status_code=404, detail="Exam not found")
        
        extraction_processing = bool(exam.get("question_paper_processing")) or (
            str(exam.get("question_extraction_status", "")).lower() == "processing"
        )
        if extraction_processing:
            raise HTTPException(
                status_code=409,
                detail="Question paper extraction is still in progress. Wait until it finishes, then grade.",
            )

        if not exam.get("questions"):
            raise HTTPException(
                status_code=400,
                detail="No extracted questions found. Upload/extract question paper first.",
            )
        exam = await _ensure_locked_blueprint_or_raise(exam, exam_id, context="grading")

        job_id = f"job_{uuid.uuid4().hex[:12]}"

        files_data = []
        for file in files:
            file_bytes = await file.read()
            if not file_bytes:
                continue
            if not _is_valid_answer_pdf(file.filename or "", file_bytes):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid answer-sheet file '{file.filename}'. Only actual PDF answer sheets are accepted.",
                )
            files_data.append({"filename": file.filename, "content": file_bytes})

        if not files_data:
            raise HTTPException(status_code=400, detail="No valid PDF files uploaded")

        job_record = {
            "job_id": job_id,
            "exam_id": exam_id,
            "teacher_id": user.user_id,
            "status": "pending",
            "total_papers": len(files_data),
            "processed_papers": 0,
            "successful": 0,
            "failed": 0,
            "submissions": [],
            "errors": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }

        await db.grading_jobs.insert_one(job_record)
        await db.exams.update_one(
            {"exam_id": exam_id},
            {"$set": {
                "status": "processing",
                "processing_state": "grading",
                "processing_lock_at": datetime.now(timezone.utc).isoformat(),
                "processing_lock_owner": f"grading_job:{job_id}",
            }},
        )

        asyncio.create_task(process_grading_job_in_background(job_id, exam_id, files_data, exam, user.user_id))

        return {
            "job_id": job_id,
            "status": "pending",
            "total_papers": len(files_data),
            "message": f"Grading job started for {len(files_data)} papers. Use job_id to check progress."
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"=== GRADE PAPERS BG ERROR === {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to start grading job: {str(e)}")


@router.get("/grading-jobs/{job_id}")
async def get_grading_job_status(job_id: str, user: User = Depends(get_current_user)):
    """Poll grading job status"""
    job = await db.grading_jobs.find_one({"job_id": job_id}, {"_id": 0})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if user.role == "teacher" and job["teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return serialize_doc(job)


# ---------------------------------------------------------------------------
# simple grading endpoint (question-paper + answer-sheet -> per-question scores)
# ---------------------------------------------------------------------------

@router.post("/simple/grade")
async def simple_grade(
    question_paper: UploadFile = File(...),
    answer_sheet: UploadFile = File(...),
    question_meta: str = Form(None),
    user: User = Depends(get_current_user),
):
    """Minimal grading path used for simplified workflows.

    Accepts two PDFs and an optional JSON blob (as form field) containing
    question metadata keyed by question number.  Returns an array of
    question-specific scores and feedback.
    """
    # only teachers currently allowed to grade
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can grade")

    qp_bytes = await question_paper.read()
    ans_bytes = await answer_sheet.read()
    try:
        meta_obj = json.loads(question_meta) if question_meta else {}
    except Exception:
        raise HTTPException(status_code=400, detail="question_meta must be valid JSON")

    from app.services.simple_pipeline import run_simple_pipeline

    try:
        results = run_simple_pipeline(qp_bytes, ans_bytes, question_meta=meta_obj)
        return {"question_results": results}
    except Exception as e:
        logger.error("simple_grade failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Grading failed: {e}")


@router.post("/grading-jobs/{job_id}/cancel")
async def cancel_grading_job(job_id: str, user: User = Depends(get_current_user)):
    """Cancel an ongoing grading job"""
    job = await db.grading_jobs.find_one({"job_id": job_id}, {"_id": 0})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if user.role == "teacher" and job["teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    if job["status"] in ["queued", "processing"]:
        await db.grading_jobs.update_one(
            {"job_id": job_id},
            {"$set": {"status": "cancelled", "error": "Cancelled by user"}}
        )
        logger.info(f"Grading job {job_id} cancelled by user {user.user_id}")
        return {"message": "Job cancelled successfully", "job_id": job_id}
    else:
        return {"message": f"Job already {job['status']}", "job_id": job_id}


@router.post("/exams/{exam_id}/regrade-all")
async def regrade_all_submissions(exam_id: str, user: User = Depends(get_current_user)):
    """Regrade all submissions for an exam with current settings"""
    from app.services.grading import grade_with_ai
    from app.services.extraction import get_exam_model_answer_text, get_exam_model_answer_map
    from app.services.annotation import generate_annotated_images_with_vision_ocr, generate_annotated_images

    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can regrade exams")

    exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    exam = await _ensure_locked_blueprint_or_raise(exam, exam_id, context="regrading")

    submissions = await db.submissions.find({"exam_id": exam_id}, {"_id": 0}).to_list(1000)

    if not submissions:
        return {"message": "No submissions to regrade", "regraded_count": 0}

    model_answer_imgs = await get_exam_model_answer_images(exam_id)

    subject_name = None
    if exam.get("subject_id"):
        subject_doc = await db.subjects.find_one({"subject_id": exam["subject_id"]}, {"_id": 0, "name": 1})
        subject_name = subject_doc.get("name") if subject_doc else None

    model_answer_text = await get_exam_model_answer_text(exam_id)
    model_answer_map = await get_exam_model_answer_map(exam_id)

    regraded_count = 0
    errors = []

    for submission in submissions:
        try:
            latest_blueprint_version = int(exam.get("blueprint_version", 0) or 0)
            submission_version_raw = submission.get("blueprint_version_used")
            submission_version = None
            try:
                if submission_version_raw is not None:
                    submission_version = int(submission_version_raw)
            except Exception:
                submission_version = None
            if submission_version is not None and submission_version != latest_blueprint_version:
                logger.warning(
                    "BLUEPRINT_VERSION_MISMATCH submission=%s exam_id=%s submission_version=%s latest_version=%s",
                    submission.get("submission_id"),
                    exam_id,
                    submission_version,
                    latest_blueprint_version,
                )
                await db.submissions.update_one(
                    {"submission_id": submission["submission_id"]},
                    {"$set": {"realign_required": True}},
                )
                logger.info(
                    "REALIGN_REQUIRED submission=%s exam_id=%s from_version=%s to_version=%s",
                    submission.get("submission_id"),
                    exam_id,
                    submission_version,
                    latest_blueprint_version,
                )

            answer_images = submission.get("answer_images") or submission.get("file_images")
            if not answer_images and submission.get("images_gridfs_id"):
                try:
                    img_oid = ObjectId(submission["images_gridfs_id"])
                    if fs.exists(img_oid):
                        grid_out = fs.get(img_oid)
                        answer_images = pickle.loads(grid_out.read())
                except Exception as img_err:
                    logger.error(f"Error retrieving answer images from GridFS for regrade: {img_err}")
            if not answer_images:
                logger.warning(f"Submission {submission['submission_id']} has no answer images, skipping")
                continue

            scores = await grade_with_ai(
                images=answer_images,
                model_answer_images=model_answer_imgs,
                questions=exam.get("questions", []),
                grading_mode=exam.get("grading_mode", "balanced"),
                total_marks=exam.get("total_marks", 100),
                model_answer_text=model_answer_text,
                model_answer_map=model_answer_map,
                subject_name=subject_name,
                exam_id=exam_id,
                exam_name=exam.get("exam_name"),
                exam_type=exam.get("exam_type"),
                skip_cache=True
            )
            packet_meta = getattr(grade_with_ai, "last_packet_meta", {}) or {}
            grading_reference_mode = getattr(grade_with_ai, "last_grading_reference_mode", "rubric_only")
            mapping_status = str(packet_meta.get("mapping_status", "pass") or "pass")

            try:
                annotated_images = await generate_annotated_images_with_vision_ocr(
                    answer_images, scores, use_vision_ocr=True, dense_red_pen=False
                )
            except Exception as ann_error:
                logger.warning(f"Regrade annotation generation failed, using margin annotations: {ann_error}")
                annotated_images = generate_annotated_images(answer_images, scores)

            annotated_images_gridfs_id = None
            try:
                annotated_data = pickle.dumps(annotated_images)
                annotated_images_gridfs_id = fs.put(
                    annotated_data,
                    filename=f"{submission['submission_id']}_annotated_regrade.pkl",
                    submission_id=submission["submission_id"]
                )
            except Exception as gridfs_err:
                logger.error(f"GridFS storage error for regrade annotations: {gridfs_err}")

            score_payload = [s.model_dump() for s in scores]
            normalized = normalize_submission_scores(
                {
                    "submission_id": submission["submission_id"],
                    "question_scores": score_payload,
                },
                exam,
                source="regrade",
            )
            total_score = normalized["total_score"]
            exam_total_marks = exam.get("total_marks", 100)
            percentage = normalized["percentage"]

            # Ensure submission reflects current exam totals and obtained marks
            exam_total_marks = exam.get("total_marks", 100)

            await db.submissions.update_one(
                {"submission_id": submission["submission_id"]},
                {"$set": {
                    "question_scores": normalized["question_scores"],
                    "total_score": total_score,
                    "obtained_marks": total_score,
                    "total_marks": exam_total_marks,
                    "percentage": percentage,
                    "graded_at": datetime.now(timezone.utc).isoformat(),
                    "regraded_at": datetime.now(timezone.utc).isoformat(),
                    "grading_mode_used": exam.get("grading_mode", "balanced"),
                    "grading_state": "done" if mapping_status == "pass" else "blocked",
                    "blueprint_version_used": int(packet_meta.get("blueprint_version_used", exam.get("blueprint_version", 0) or 0) or 0),
                    "grading_contract_version": packet_meta.get("grading_contract_version"),
                    "structure_confidence": float(packet_meta.get("structure_confidence", 0.0) or 0.0),
                    "alignment_confidence": float(packet_meta.get("alignment_confidence", 0.0) or 0.0),
                    "grading_confidence": float(packet_meta.get("grading_confidence", 0.0) or 0.0),
                    "overall_confidence": float(packet_meta.get("overall_confidence", 0.0) or 0.0),
                    "alignment_status": "pass" if mapping_status == "pass" else "needs_review",
                    "alignment_coverage": float(packet_meta.get("mapping_coverage", 0.0) or 0.0),
                    "question_coverage_map": packet_meta.get("question_coverage_map", {}),
                    "unmapped_answers": packet_meta.get("unmapped_answers", []),
                    "duplicate_answers": packet_meta.get("duplicate_answers", []),
                    "realign_required": False,
                    "objective_key_flags": packet_meta.get("objective_key_flags", {}),
                    "model_name": packet_meta.get("model_name"),
                    "prompt_version": packet_meta.get("prompt_version"),
                    "pipeline_version": packet_meta.get("pipeline_version"),
                    "grading_reference_mode": grading_reference_mode,
                    "mapping_status": mapping_status,
                    "mapped_question_ratio": float(packet_meta.get("mapped_question_ratio", 0.0) or 0.0),
                    "mapping_coverage": float(packet_meta.get("mapping_coverage", 0.0) or 0.0),
                    "unresolved_questions": packet_meta.get("unresolved_questions", []),
                    "mapping_fail_reasons": packet_meta.get("mapping_fail_reasons", []),
                    "anchor_confidence_summary": packet_meta.get("anchor_confidence_summary", {}),
                    "table_confidence_summary": packet_meta.get("table_confidence_summary", {}),
                    "alignment_confidence_summary": packet_meta.get("alignment_confidence_summary", {}),
                    "packets_generated": int(packet_meta.get("packets_generated", 0) or 0),
                    "subpacket_count": int(packet_meta.get("subpacket_count", 0) or 0),
                    "low_confidence_questions": packet_meta.get("low_confidence_questions", []),
                    "consistency_flags": packet_meta.get("consistency_flags", []),
                    "packet_trace_ref": packet_meta.get("pipeline"),
                    "status": "needs_review" if mapping_status != "pass" else "ai_graded",
                    "annotated_images_gridfs_id": str(annotated_images_gridfs_id) if annotated_images_gridfs_id else None,
                    "annotated_images": annotated_images if not annotated_images_gridfs_id else []
                }}
            )

            regraded_count += 1
            logger.info(f"Regraded submission {submission['submission_id']}: {total_score}/{exam_total_marks}")

        except Exception as e:
            logger.error(f"Error regrading submission {submission['submission_id']}: {str(e)}")
            errors.append({"submission_id": submission["submission_id"], "error": str(e)})

    return {
        "message": f"Regraded {regraded_count} submissions",
        "regraded_count": regraded_count,
        "total_submissions": len(submissions),
        "errors": errors[:5] if errors else []
    }


@router.post("/exams/{exam_id}/grade-student-submissions")
async def grade_student_submissions(exam_id: str, user: User = Depends(get_current_user)):
    """Trigger grading for all submitted student answers"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can grade")

    exam = await db.exams.find_one({"exam_id": exam_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    if exam["teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Not your exam")

    if exam.get("exam_mode") != "student_upload":
        raise HTTPException(status_code=400, detail="Not a student-upload exam")
    exam = await _ensure_locked_blueprint_or_raise(exam, exam_id, context="student submission grading")

    submissions = await db.student_submissions.find(
        {"exam_id": exam_id, "status": "submitted"},
        {"_id": 0}
    ).to_list(1000)

    if not submissions:
        raise HTTPException(status_code=400, detail="No submissions to grade")

    job_id = f"job_{uuid.uuid4().hex[:12]}"

    tasks_created = []
    for submission in submissions:
        task_id = f"task_{uuid.uuid4().hex[:12]}"

        task_doc = {
            "task_id": task_id,
            "type": "grade_paper",
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "exam_id": exam_id,
                "student_id": submission["student_id"],
                "student_name": submission["student_name"],
                "grading_mode": exam["grading_mode"],
                "questions": exam["questions"],
                "answer_file_ref": submission["answer_file_ref"],
            },
            "result": None
        }

        await db.tasks.insert_one(task_doc)
        tasks_created.append(task_id)

    job_doc = {
        "job_id": job_id,
        "exam_id": exam_id,
        "teacher_id": user.user_id,
        "status": "processing",
        "progress": 0,
        "total_papers": len(submissions),
        "processed_papers": 0,
        "successful": 0,
        "failed": 0,
        "submissions": [],
        "errors": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "task_ids": tasks_created
    }

    await db.grading_jobs.insert_one(job_doc)

    await db.exams.update_one(
        {"exam_id": exam_id},
        {"$set": {"status": "grading", "grading_job_id": job_id}}
    )

    logger.info(f"Created grading job {job_id} for {len(submissions)} student submissions")

    return {
        "job_id": job_id,
        "message": f"Grading started for {len(submissions)} submissions",
        "total_papers": len(submissions)
    }
