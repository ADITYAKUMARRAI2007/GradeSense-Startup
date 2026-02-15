"""Grading routes - start grading, job status, cancel, regrade."""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from datetime import datetime, timezone
from typing import List
import uuid
import asyncio
import pickle

from bson import ObjectId

from app.database import db, fs
from app.deps import get_current_user
from app.models.user import User
from app.utils.serialization import serialize_doc
from app.services.gridfs_helpers import get_exam_model_answer_images
from app.config import logger

router = APIRouter(tags=["grading"])


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

        job_id = f"job_{uuid.uuid4().hex[:12]}"

        files_data = []
        for file in files:
            file_bytes = await file.read()
            if not file_bytes:
                continue
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
        await db.exams.update_one({"exam_id": exam_id}, {"$set": {"status": "processing"}})

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
    from app.services.extraction import get_exam_model_answer_text
    from app.services.annotation import generate_annotated_images_with_vision_ocr, generate_annotated_images

    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can regrade exams")

    exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    submissions = await db.submissions.find({"exam_id": exam_id}, {"_id": 0}).to_list(1000)

    if not submissions:
        return {"message": "No submissions to regrade", "regraded_count": 0}

    model_answer_imgs = await get_exam_model_answer_images(exam_id)

    subject_name = None
    if exam.get("subject_id"):
        subject_doc = await db.subjects.find_one({"subject_id": exam["subject_id"]}, {"_id": 0, "name": 1})
        subject_name = subject_doc.get("name") if subject_doc else None

    model_answer_text = await get_exam_model_answer_text(exam_id)

    regraded_count = 0
    errors = []

    for submission in submissions:
        try:
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
                subject_name=subject_name,
                exam_name=exam.get("exam_name"),
                exam_type=getattr(user, "exam_type", None),
                skip_cache=True
            )

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

            total_score = sum(s.obtained_marks for s in scores)
            exam_total_marks = exam.get("total_marks", 100)
            percentage = round((total_score / exam_total_marks) * 100, 2) if exam_total_marks > 0 else 0

            await db.submissions.update_one(
                {"submission_id": submission["submission_id"]},
                {"$set": {
                    "question_scores": [s.model_dump() for s in scores],
                    "total_score": total_score,
                    "percentage": percentage,
                    "graded_at": datetime.now(timezone.utc).isoformat(),
                    "regraded_at": datetime.now(timezone.utc).isoformat(),
                    "grading_mode_used": exam.get("grading_mode", "balanced"),
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
