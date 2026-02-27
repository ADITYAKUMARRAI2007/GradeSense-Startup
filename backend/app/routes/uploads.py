"""File upload routes - question paper, model answer, student papers."""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from datetime import datetime, timezone
from typing import Optional, List
import uuid
import asyncio
import os
import pickle
import base64

from app.database import db, fs
from app.deps import get_current_user
from app.models.user import User
from app.services.gridfs_helpers import get_exam_model_answer_images, get_exam_question_paper_images
from app.services.file_processing import pdf_to_images
from app.services.student_detection import extract_student_info_from_paper, parse_student_from_filename, get_or_create_student
from app.services.score_normalization import normalize_submission_scores
from app.config import (
    COLLEGE_V2_HARD_STOP,
    UNIVERSAL_HARD_STOP,
    UNIVERSAL_PIPELINE_ENABLED,
    UNIVERSAL_PIPELINE_EXAM_TYPES,
    logger,
)
from app.utils.concurrency import conversion_semaphore
from app.utils.file_utils import convert_to_images, extract_zip_files, download_from_google_drive, extract_file_id_from_url
from app.utils.blueprint import (
    build_blueprint_freeze_payload,
    evaluate_blueprint_lock_readiness,
)

router = APIRouter(tags=["uploads"])


def _is_valid_answer_pdf(filename: str, payload: bytes) -> bool:
    name = str(filename or "").strip().lower()
    if not name.endswith(".pdf"):
        return False
    if not payload or not payload.startswith(b"%PDF"):
        return False
    blocked_name_tokens = ("resume", "cv", "curriculum_vitae", "curriculum-vitae")
    return not any(token in name for token in blocked_name_tokens)


def _blueprint_lock_error_for_upload(exam: dict, readiness: dict, context: str) -> dict:
    health = readiness.get("health") or {}
    return {
        "message": f"Cannot {context}: blueprint is not locked.",
        "required_action": "Review blueprint health, fix missing/duplicate questions, then lock blueprint.",
        "blueprint_status": exam.get("blueprint_status", "pending"),
        "blueprint_health": health,
        "missing_question_numbers": health.get("missing", []),
        "duplicate_question_numbers": health.get("duplicates", []),
        "lock_blockers": readiness.get("issues", []),
    }


async def _ensure_locked_blueprint_for_upload_or_raise(exam: dict, exam_id: str, context: str) -> dict:
    processing_state = str(exam.get("processing_state") or "idle").lower()
    if processing_state != "idle":
        raise HTTPException(
            status_code=409,
            detail=f"Exam is currently in '{processing_state}' state. Retry after current pipeline stage completes.",
        )

    if bool(exam.get("blueprint_locked")) or str(exam.get("blueprint_status", "pending")).lower() == "ready_locked":
        return exam

    # Removed 409 check - allow grading even during extraction
    # if exam.get("question_paper_processing") or str(exam.get("question_extraction_status", "")).lower() == "processing":
    #     raise HTTPException(
    #         status_code=409,
    #         detail="Question extraction is still running. Wait for completion before grading papers.",
    #     )

    readiness = evaluate_blueprint_lock_readiness(exam, questions=exam.get("questions") or [])
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
                **_blueprint_lock_error_for_upload(exam, readiness, context=context),
                "required_action": "Lock blueprint explicitly before uploading/grading college answer sheets.",
            },
        )
    if universal_active and UNIVERSAL_HARD_STOP:
        raise HTTPException(
            status_code=409,
            detail={
                **_blueprint_lock_error_for_upload(exam, readiness, context=context),
                "required_action": "Lock blueprint explicitly before uploading/grading universal answer sheets.",
            },
        )
    if not readiness.get("can_lock"):
        raise HTTPException(
            status_code=409,
            detail=_blueprint_lock_error_for_upload(exam, readiness, context=context),
        )

    health = readiness.get("health") or {}
    freeze_payload = build_blueprint_freeze_payload(exam)
    if int(freeze_payload.get("question_count", 0) or 0) <= 0:
        raise HTTPException(
            status_code=409,
            detail={
                **_blueprint_lock_error_for_upload(exam, readiness, context=context),
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


@router.post("/exams/{exam_id}/upload-model-answer")
async def upload_model_answer(
    exam_id: str,
    file: Optional[UploadFile] = File(None),
    link: Optional[str] = None,
    user: User = Depends(get_current_user)
):
    """Upload model answer (PDF/Word/Image/ZIP) or provide Google Drive link"""
    from app.services.extraction import auto_extract_questions, extract_model_answer_content
    from app.services.extraction import _process_model_answer_async

    await db.exams.update_one(
        {"exam_id": exam_id},
        {"$set": {"model_answer_processing": True}}
    )

    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can upload model answers")

    exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    file_bytes = None
    file_type = None

    if link:
        file_id = extract_file_id_from_url(link)
        if not file_id:
            raise HTTPException(status_code=400, detail="Invalid Google Drive link")
        try:
            file_bytes, mime_type = download_from_google_drive(file_id)
            file_type = mime_type.split('/')[-1] if '/' in mime_type else 'pdf'
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to download from link: {str(e)}")
    elif file:
        file_bytes = await file.read()
        file_ext = os.path.splitext(file.filename)[1].lower().replace('.', '')
        file_type = file_ext or file.content_type
    else:
        raise HTTPException(status_code=400, detail="Either file or link must be provided")

    file_size_mb = len(file_bytes) / (1024 * 1024)
    if len(file_bytes) > 30 * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File too large ({file_size_mb:.1f}MB). Maximum size is 30MB.")

    all_images = []
    if file_type in ['zip', 'application/zip', 'application/x-zip-compressed']:
        try:
            extracted_files = extract_zip_files(file_bytes)
            logger.info(f"Extracted {len(extracted_files)} files from ZIP")
            for filename, extracted_bytes, extracted_type in extracted_files:
                try:
                    async with conversion_semaphore:
                        file_images = await asyncio.to_thread(convert_to_images, extracted_bytes, extracted_type)
                    all_images.extend(file_images)
                except Exception as e:
                    logger.warning(f"Failed to process {filename}: {e}")
            if not all_images:
                raise HTTPException(status_code=400, detail="No valid files found in ZIP")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to process ZIP file: {str(e)}")
    else:
        try:
            async with conversion_semaphore:
                all_images = await asyncio.to_thread(convert_to_images, file_bytes, file_type)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to process file: {str(e)}")

    images = all_images
    file_id_str = str(uuid.uuid4())

    images_data = pickle.dumps(images)
    gridfs_id = fs.put(
        images_data,
        filename=f"model_answer_{exam_id}_{file_id_str}",
        content_type="application/python-pickle",
        exam_id=exam_id,
        file_type="model_answer"
    )

    await db.exam_files.update_one(
        {"exam_id": exam_id, "file_type": "model_answer"},
        {"$set": {
            "exam_id": exam_id,
            "file_type": "model_answer",
            "file_id": file_id_str,
            "gridfs_id": str(gridfs_id),
            "page_count": len(images),
            "uploaded_at": datetime.now(timezone.utc).isoformat()
        }},
        upsert=True
    )

    await db.exams.update_one(
        {"exam_id": exam_id},
        {"$set": {
            "model_answer_file_id": file_id_str,
            "model_answer_pages": len(images),
            "has_model_answer": True
        }}
    )

    await db.exams.update_one(
        {"exam_id": exam_id},
        {"$set": {
            "model_answer_processing": True,
            "model_answer_text_status": "processing",
            "question_extraction_status": "processing",
            "processing_state": "extracting",
            "processing_lock_at": datetime.now(timezone.utc).isoformat(),
            "processing_lock_owner": f"upload_model_answer:{exam_id}",
            "question_extraction_count": 0,
            "model_answer_text_chars": 0
        }}
    )

    asyncio.create_task(_process_model_answer_async(exam_id))

    return {
        "message": "✨ Model answer uploaded. Extraction is running in the background.",
        "pages": len(images),
        "processing": True
    }


@router.post("/exams/{exam_id}/upload-question-paper")
async def upload_question_paper(
    exam_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user)
):
    """Upload question paper (PDF/Word/Image/ZIP) and AUTO-EXTRACT questions"""
    from app.services.extraction import _process_question_paper_async
    from app.services.notifications import create_notification

    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can upload question papers")

    exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    file_bytes = await file.read()
    file_ext = os.path.splitext(file.filename)[1].lower().replace('.', '')
    file_type = file_ext or file.content_type

    file_size_mb = len(file_bytes) / (1024 * 1024)
    if len(file_bytes) > 30 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({file_size_mb:.1f}MB). Maximum size is 30MB. Try compressing the file or reducing quality."
        )

    all_images = []
    if file_type in ['zip', 'application/zip', 'application/x-zip-compressed']:
        try:
            extracted_files = extract_zip_files(file_bytes)
            logger.info(f"Extracted {len(extracted_files)} files from ZIP")
            for filename, extracted_bytes, extracted_type in extracted_files:
                try:
                    async with conversion_semaphore:
                        file_images = await asyncio.to_thread(convert_to_images, extracted_bytes, extracted_type)
                    all_images.extend(file_images)
                except Exception as e:
                    logger.warning(f"Failed to process {filename}: {e}")
            if not all_images:
                raise HTTPException(status_code=400, detail="No valid files found in ZIP")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to process ZIP file: {str(e)}")
    else:
        try:
            async with conversion_semaphore:
                all_images = await asyncio.to_thread(convert_to_images, file_bytes, file_type)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to process file: {str(e)}")

    images = all_images
    file_id_str = str(uuid.uuid4())

    images_data = pickle.dumps(images)
    gridfs_id = fs.put(
        images_data,
        filename=f"question_paper_{exam_id}_{file_id_str}",
        content_type="application/python-pickle",
        exam_id=exam_id,
        file_type="question_paper"
    )

    await db.exam_files.update_one(
        {"exam_id": exam_id, "file_type": "question_paper"},
        {"$set": {
            "exam_id": exam_id,
            "file_type": "question_paper",
            "file_id": file_id_str,
            "gridfs_id": str(gridfs_id),
            "page_count": len(images),
            "uploaded_at": datetime.now(timezone.utc).isoformat()
        }},
        upsert=True
    )

    # Preserve original question-paper PDF bytes for deterministic blueprint parsing.
    if file_type == "pdf":
        try:
            qp_pdf_gridfs_id = fs.put(
                file_bytes,
                filename=f"question_paper_pdf_{exam_id}_{file_id_str}.pdf",
                content_type="application/pdf",
                exam_id=exam_id,
                file_type="question_paper_pdf",
            )
            await db.exam_files.update_one(
                {"exam_id": exam_id, "file_type": "question_paper_pdf"},
                {"$set": {
                    "exam_id": exam_id,
                    "file_type": "question_paper_pdf",
                    "file_id": file_id_str,
                    "gridfs_id": str(qp_pdf_gridfs_id),
                    "uploaded_at": datetime.now(timezone.utc).isoformat(),
                }},
                upsert=True,
            )
        except Exception as e:
            logger.warning(f"Could not persist question paper PDF bytes for exam {exam_id}: {e}")

    await db.exams.update_one(
        {"exam_id": exam_id},
        {"$set": {
            "question_paper_file_id": file_id_str,
            "question_paper_pages": len(images),
            "has_question_paper": True
        }}
    )

    await db.exams.update_one(
        {"exam_id": exam_id},
        {"$set": {
            "question_paper_processing": True,
            "question_extraction_status": "processing",
            "processing_state": "extracting",
            "processing_lock_at": datetime.now(timezone.utc).isoformat(),
            "processing_lock_owner": f"upload_question_paper:{exam_id}",
            "blueprint_status": "extracting",
            "blueprint_locked": False,
            "blueprint_locked_at": None,
            "blueprint_health": None,
            "question_extraction_count": 0
        }}
    )

    await create_notification(
        user_id=user.user_id,
        notification_type="question_extraction_started",
        title="Question Paper Processing Started",
        message=f"Question paper uploaded for {exam.get('exam_name', 'exam')}. Extraction is running.",
        link=f"/teacher/review?exam={exam_id}",
    )

    asyncio.create_task(_process_question_paper_async(exam_id))

    return {
        "message": "✨ Question paper uploaded. Extraction is running in the background.",
        "pages": len(images),
        "processing": True
    }


@router.post("/exams/{exam_id}/upload-papers")
async def upload_student_papers(
    exam_id: str,
    files: List[UploadFile] = File(...),
    user: User = Depends(get_current_user)
):
    """Upload and grade student papers with background job processing"""
    from app.services.grading import process_grading_job_in_background
    from app.services.notifications import create_notification

    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can upload papers")

    exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    if exam.get("question_paper_processing") or str(exam.get("question_extraction_status", "")).lower() == "processing":
        raise HTTPException(
            status_code=400,
            detail="Question extraction is still running. Wait for completion before grading papers.",
        )
    if not (exam.get("questions") or []):
        raise HTTPException(
            status_code=400,
            detail="No rubric/questions found. Upload and extract the question paper before grading.",
        )
    exam = await _ensure_locked_blueprint_for_upload_or_raise(exam, exam_id, context="upload papers")

    job_id = f"job_{uuid.uuid4().hex[:12]}"

    files_data = []
    for file in files:
        file_bytes = await file.read()
        if not _is_valid_answer_pdf(file.filename or "", file_bytes):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid answer-sheet file '{file.filename}'. Only actual PDF answer sheets are accepted.",
            )
        files_data.append({
            "filename": file.filename,
            "content": file_bytes
        })

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
        }}
    )

    await create_notification(
        user_id=user.user_id,
        notification_type="grading_started",
        title="Grading Started",
        message=f"Grading job started for {len(files_data)} paper(s) in {exam.get('exam_name', 'exam')}.",
        link=f"/teacher/review?exam={exam_id}",
    )

    asyncio.create_task(process_grading_job_in_background(job_id, exam_id, files_data, exam, user.user_id))

    return {
        "job_id": job_id,
        "status": "pending",
        "total_papers": len(files_data),
        "message": f"Grading job started for {len(files_data)} papers. Use job_id to check progress."
    }


@router.post("/exams/{exam_id}/upload-more-papers")
async def upload_more_papers(
    exam_id: str,
    files: List[UploadFile] = File(...),
    user: User = Depends(get_current_user)
):
    """Upload additional student papers to an existing exam"""
    from app.services.answer_sheet_pipeline import pdf_to_clean_images
    from app.services.grading import grade_with_ai
    from app.services.extraction import get_exam_model_answer_text, get_exam_model_answer_map

    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can upload papers")

    exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    if exam.get("status") == "closed":
        raise HTTPException(status_code=400, detail="Cannot upload papers to closed exam")
    if exam.get("question_paper_processing") or str(exam.get("question_extraction_status", "")).lower() == "processing":
        raise HTTPException(
            status_code=400,
            detail="Question extraction is still running. Wait until extraction completes, then upload papers.",
        )
    exam = await _ensure_locked_blueprint_for_upload_or_raise(exam, exam_id, context="upload more papers")

    submissions = []
    errors = []

    logger.info(f"=== BATCH GRADING START === Received {len(files)} files for exam {exam_id}")
    for idx, file in enumerate(files):
        filename = file.filename
        logger.info(f"[File {idx + 1}/{len(files)}] START processing: {filename}")
        try:
            pdf_bytes = await file.read()
            logger.info(f"[File {idx + 1}/{len(files)}] Read {len(pdf_bytes)} bytes from {filename}")
            if not _is_valid_answer_pdf(filename, pdf_bytes):
                errors.append(
                    {
                        "filename": filename,
                        "error": "Invalid answer-sheet file. Only actual PDF answer sheets are accepted.",
                    }
                )
                continue

            file_size_mb = len(pdf_bytes) / (1024 * 1024)
            if len(pdf_bytes) > 30 * 1024 * 1024:
                errors.append({"filename": filename, "error": f"File too large ({file_size_mb:.1f}MB). Maximum size is 30MB."})
                continue

            try:
                async with conversion_semaphore:
                    images = await asyncio.to_thread(pdf_to_clean_images, pdf_bytes, 300)
            except Exception as clean_err:
                logger.warning(f"[File {idx + 1}/{len(files)}] Clean conversion failed for {filename}: {clean_err}")
                async with conversion_semaphore:
                    images = await asyncio.to_thread(pdf_to_images, pdf_bytes)

            if not images:
                errors.append({"filename": filename, "error": "Failed to extract images from PDF"})
                continue

            student_id, student_name = await extract_student_info_from_paper(images, filename)

            if not student_id or not student_name:
                filename_id, filename_name = parse_student_from_filename(filename)
                if not student_id and filename_id:
                    student_id = filename_id
                if not student_name and filename_name:
                    student_name = filename_name

                if not student_id and not student_name:
                    errors.append({"filename": filename, "error": "Could not extract student ID/name from paper or filename."})
                    continue

                if not student_id:
                    student_id = f"AUTO_{uuid.uuid4().hex[:6]}"
                if not student_name:
                    student_name = f"Student {student_id}"

            user_id, error = await get_or_create_student(
                student_id=student_id,
                student_name=student_name,
                batch_id=exam["batch_id"],
                teacher_id=user.user_id
            )

            if error:
                errors.append({"filename": filename, "student_id": student_id, "error": error})
                continue

            model_answer_imgs = await get_exam_model_answer_images(exam_id)
            model_answer_text = await get_exam_model_answer_text(exam_id)
            model_answer_map = await get_exam_model_answer_map(exam_id)

            questions_to_grade = exam.get("questions", []) or []
            if not questions_to_grade:
                errors.append(
                    {
                        "filename": filename,
                        "student_id": student_id,
                        "error": "No rubric/questions available. Upload and extract the question paper before grading.",
                    }
                )
                continue

            subject_name = None
            if exam.get("subject_id"):
                subject_doc = await db.subjects.find_one({"subject_id": exam["subject_id"]}, {"_id": 0, "name": 1})
                subject_name = subject_doc.get("name") if subject_doc else None

            scores = await grade_with_ai(
                images=images,
                model_answer_images=model_answer_imgs,
                questions=questions_to_grade,
                grading_mode=exam.get("grading_mode", "balanced"),
                total_marks=exam.get("total_marks", 100),
                model_answer_text=model_answer_text,
                model_answer_map=model_answer_map,
                subject_name=subject_name,
                exam_id=exam_id,
                exam_name=exam.get("exam_name"),
                exam_type=exam.get("exam_type"),
            )
            packet_meta = getattr(grade_with_ai, "last_packet_meta", {}) or {}
            grading_reference_mode = getattr(grade_with_ai, "last_grading_reference_mode", "rubric_only")
            mapping_status = str(packet_meta.get("mapping_status", "pass") or "pass")

            total_score = sum(s.obtained_marks for s in scores)
            percentage = (total_score / exam["total_marks"]) * 100 if exam["total_marks"] > 0 else 0

            submission_id = f"sub_{uuid.uuid4().hex[:8]}"
            normalized = normalize_submission_scores(
                {
                    "submission_id": submission_id,
                    "question_scores": [s.model_dump() for s in scores],
                    "total_score": total_score,
                    "percentage": round(percentage, 2),
                },
                exam,
                source="upload_more_papers",
            )

            pdf_gridfs_id = None
            images_gridfs_id = None

            try:
                pdf_gridfs_id = fs.put(pdf_bytes, filename=f"{submission_id}.pdf", submission_id=submission_id)
                images_data = pickle.dumps(images)
                images_gridfs_id = fs.put(images_data, filename=f"{submission_id}_images.pkl", submission_id=submission_id)
            except Exception as gridfs_err:
                logger.error(f"GridFS storage error: {gridfs_err}")

            submission = {
                "submission_id": submission_id,
                "exam_id": exam_id,
                "student_id": user_id,
                "student_name": student_name,
                "file_data": "" if pdf_gridfs_id else base64.b64encode(pdf_bytes).decode(),
                "pdf_gridfs_id": str(pdf_gridfs_id) if pdf_gridfs_id else None,
                "images_gridfs_id": str(images_gridfs_id) if images_gridfs_id else None,
                "file_images": images if not images_gridfs_id else [],
                "total_score": normalized["total_score"],
                "percentage": normalized["percentage"],
                "question_scores": normalized["question_scores"],
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
                "continuity_confidence_summary": packet_meta.get("continuity_confidence_summary", {}),
                "orphan_block_count": int(packet_meta.get("orphan_block_count", 0) or 0),
                "orphan_block_ratio": float(packet_meta.get("orphan_block_ratio", 0.0) or 0.0),
                "packets_generated": int(packet_meta.get("packets_generated", 0) or 0),
                "subpacket_count": int(packet_meta.get("subpacket_count", 0) or 0),
                "low_confidence_questions": packet_meta.get("low_confidence_questions", []),
                "consistency_flags": packet_meta.get("consistency_flags", []),
                "packet_trace_ref": packet_meta.get("pipeline"),
                "status": "needs_review" if mapping_status != "pass" else "ai_graded",
                "graded_at": datetime.now(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat()
            }

            await db.submissions.insert_one(submission)
            submissions.append({
                "submission_id": submission_id,
                "student_id": student_id,
                "student_name": student_name,
                "total_score": normalized["total_score"],
                "percentage": normalized["percentage"],
            })
            logger.info(f"✓ Successfully graded {filename} - Student: {student_name}, Score: {normalized['total_score']}/{exam['total_marks']}")

        except Exception as e:
            logger.error(f"✗ Error processing {filename}: {e}", exc_info=True)
            errors.append({"filename": filename, "error": str(e)})

    result = {"processed": len(submissions), "submissions": submissions}
    if errors:
        result["errors"] = errors

    return result
