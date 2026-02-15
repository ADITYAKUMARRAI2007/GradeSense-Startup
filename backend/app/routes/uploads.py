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
from app.config import logger
from app.utils.concurrency import conversion_semaphore
from app.utils.file_utils import convert_to_images, extract_zip_files, download_from_google_drive, extract_file_id_from_url

router = APIRouter(tags=["uploads"])


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
            "question_extraction_count": 0
        }}
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

    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can upload papers")

    exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    job_id = f"job_{uuid.uuid4().hex[:12]}"

    files_data = []
    for file in files:
        file_bytes = await file.read()
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
        {"$set": {"status": "processing"}}
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
    from app.services.grading import grade_with_ai
    from app.services.extraction import get_exam_model_answer_text

    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can upload papers")

    exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    if exam.get("status") == "closed":
        raise HTTPException(status_code=400, detail="Cannot upload papers to closed exam")

    submissions = []
    errors = []

    logger.info(f"=== BATCH GRADING START === Received {len(files)} files for exam {exam_id}")
    for idx, file in enumerate(files):
        filename = file.filename
        logger.info(f"[File {idx + 1}/{len(files)}] START processing: {filename}")
        try:
            pdf_bytes = await file.read()
            logger.info(f"[File {idx + 1}/{len(files)}] Read {len(pdf_bytes)} bytes from {filename}")

            file_size_mb = len(pdf_bytes) / (1024 * 1024)
            if len(pdf_bytes) > 30 * 1024 * 1024:
                errors.append({"filename": filename, "error": f"File too large ({file_size_mb:.1f}MB). Maximum size is 30MB."})
                continue

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

            subject_name = None
            if exam.get("subject_id"):
                subject_doc = await db.subjects.find_one({"subject_id": exam["subject_id"]}, {"_id": 0, "name": 1})
                subject_name = subject_doc.get("name") if subject_doc else None

            scores = await grade_with_ai(
                images=images,
                model_answer_images=model_answer_imgs,
                questions=exam.get("questions", []),
                grading_mode=exam.get("grading_mode", "balanced"),
                total_marks=exam.get("total_marks", 100),
                model_answer_text=model_answer_text,
                subject_name=subject_name,
                exam_name=exam.get("exam_name")
            )

            total_score = sum(s.obtained_marks for s in scores)
            percentage = (total_score / exam["total_marks"]) * 100 if exam["total_marks"] > 0 else 0

            submission_id = f"sub_{uuid.uuid4().hex[:8]}"

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
                "total_score": total_score,
                "percentage": round(percentage, 2),
                "question_scores": [s.model_dump() for s in scores],
                "status": "ai_graded",
                "graded_at": datetime.now(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat()
            }

            await db.submissions.insert_one(submission)
            submissions.append({
                "submission_id": submission_id,
                "student_id": student_id,
                "student_name": student_name,
                "total_score": total_score,
                "percentage": percentage
            })
            logger.info(f"✓ Successfully graded {filename} - Student: {student_name}, Score: {total_score}/{exam['total_marks']}")

        except Exception as e:
            logger.error(f"✗ Error processing {filename}: {e}", exc_info=True)
            errors.append({"filename": filename, "error": str(e)})

    result = {"processed": len(submissions), "submissions": submissions}
    if errors:
        result["errors"] = errors

    return result
