"""Submission routes - CRUD, approve, review."""

from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timezone
from typing import Optional, List
import asyncio
import pickle
import base64

from bson import ObjectId

from app.database import db, fs
from app.deps import get_current_user
from app.models.user import User
from app.utils.serialization import serialize_doc
from app.config import logger

router = APIRouter(tags=["submissions"])


@router.get("/submissions")
async def get_submissions(
    exam_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    status: Optional[str] = None,
    user: User = Depends(get_current_user)
):
    """Get submissions"""
    if user.role == "teacher":
        exam_query = {"teacher_id": user.user_id, "status": "completed"}
        if batch_id:
            exam_query["batch_id"] = batch_id
        if exam_id:
            exam_query["exam_id"] = exam_id

        exams = await db.exams.find(exam_query, {"exam_id": 1, "_id": 0}).to_list(100)
        exam_ids = [e["exam_id"] for e in exams]

        query = {"exam_id": {"$in": exam_ids}}
        if status:
            query["status"] = status

        submissions = await db.submissions.find(
            query,
            {"_id": 0, "file_data": 0, "file_images": 0}
        ).to_list(500)
    else:
        published_exams = await db.exams.find(
            {"results_published": True},
            {"_id": 0, "exam_id": 1}
        ).to_list(1000)

        published_exam_ids = [e["exam_id"] for e in published_exams]

        submissions = await db.submissions.find(
            {
                "student_id": user.user_id,
                "exam_id": {"$in": published_exam_ids}
            },
            {"_id": 0, "file_data": 0, "file_images": 0}
        ).to_list(100)

    for sub in submissions:
        exam = await db.exams.find_one({"exam_id": sub["exam_id"]}, {"_id": 0, "exam_name": 1, "subject_id": 1, "batch_id": 1})
        if exam:
            sub["exam_name"] = exam.get("exam_name", "Unknown")
            subject = await db.subjects.find_one({"subject_id": exam.get("subject_id")}, {"_id": 0, "name": 1})
            sub["subject_name"] = subject.get("name", "Unknown") if subject else "Unknown"
            batch = await db.batches.find_one({"batch_id": exam.get("batch_id")}, {"_id": 0, "name": 1})
            sub["batch_name"] = batch.get("name", "Unknown") if batch else "Unknown"

    return serialize_doc(submissions)


@router.get("/submissions/{submission_id}")
async def get_submission(
    submission_id: str,
    include_images: bool = True,
    user: User = Depends(get_current_user)
):
    """Get submission details with PDF data and full question text"""
    try:
        projection = {"_id": 0}
        if not include_images:
            projection["file_images"] = 0
            projection["file_data"] = 0

        submission = await db.submissions.find_one(
            {"submission_id": submission_id},
            projection
        )

        if not submission:
            raise HTTPException(status_code=404, detail="Submission not found")

        # Retrieve images/PDF from GridFS if available
        if include_images:
            if submission.get("pdf_gridfs_id") and not submission.get("file_data"):
                try:
                    pdf_oid = ObjectId(submission["pdf_gridfs_id"])
                    if fs.exists(pdf_oid):
                        pdf_out = fs.get(pdf_oid)
                        submission["file_data"] = base64.b64encode(pdf_out.read()).decode()
                except Exception as e:
                    logger.error(f"Error retrieving PDF from GridFS: {e}")

            if submission.get("images_gridfs_id"):
                try:
                    images_oid = ObjectId(submission["images_gridfs_id"])
                    if fs.exists(images_oid):
                        grid_out = fs.get(images_oid)
                        submission["file_images"] = pickle.loads(grid_out.read())
                        logger.info(f"Retrieved {len(submission['file_images'])} images from GridFS")
                except Exception as e:
                    logger.error(f"Error retrieving images from GridFS: {e}")

            if submission.get("annotated_images_gridfs_id"):
                try:
                    annotated_oid = ObjectId(submission["annotated_images_gridfs_id"])
                    if fs.exists(annotated_oid):
                        grid_out = fs.get(annotated_oid)
                        submission["annotated_images"] = pickle.loads(grid_out.read())
                        logger.info(f"Retrieved {len(submission['annotated_images'])} annotated images from GridFS")
                except Exception as e:
                    logger.error(f"Error retrieving annotated images from GridFS: {e}")

        # Get exam to check visibility settings for students
        exam = await db.exams.find_one(
            {"exam_id": submission["exam_id"]},
            {"_id": 0, "questions": 1, "results_published": 1, "student_visibility": 1}
        )

        # For students, enforce visibility settings
        if user.role == "student":
            if not exam or not exam.get("results_published"):
                raise HTTPException(status_code=403, detail="Results not yet published")

            visibility = exam.get("student_visibility", {})

            if not visibility.get("show_answer_sheet", True):
                submission["file_images"] = []
                submission.pop("file_data", None)

        # Enrich with full question text from exam
        if exam and exam.get("questions"):
            question_map = {q["question_number"]: q for q in exam["questions"]}

            for qs in submission.get("question_scores", []):
                q_num = qs.get("question_number")
                if q_num in question_map:
                    question_data = question_map[q_num]
                    qs["question_text"] = question_data.get("rubric", "")
                    qs["sub_questions"] = question_data.get("sub_questions", [])

        # For students, handle question paper and model answer visibility
        if user.role == "student" and include_images and exam:
            visibility = exam.get("student_visibility", {})

            if visibility.get("show_question_paper", True):
                exam_file = await db.exam_files.find_one(
                    {"exam_id": submission["exam_id"]},
                    {"_id": 0, "question_paper_gridfs_id": 1, "gridfs_id": 1}
                )
                if exam_file:
                    file_id_str = exam_file.get("question_paper_gridfs_id") or exam_file.get("gridfs_id")
                    if file_id_str:
                        try:
                            file_oid = ObjectId(file_id_str)
                            if fs.exists(file_oid):
                                grid_out = fs.get(file_oid)
                                images_list = pickle.loads(grid_out.read())
                                submission["question_paper_images"] = images_list
                        except Exception as e:
                            logger.error(f"Error retrieving question paper for student: {e}")
                            submission["question_paper_images"] = []

            if visibility.get("show_model_answer", False):
                exam_file = await db.exam_files.find_one(
                    {"exam_id": submission["exam_id"]},
                    {"_id": 0, "model_answer_gridfs_id": 1}
                )
                if exam_file and exam_file.get("model_answer_gridfs_id"):
                    try:
                        file_oid = ObjectId(exam_file["model_answer_gridfs_id"])
                        if fs.exists(file_oid):
                            grid_out = fs.get(file_oid)
                            images_list = pickle.loads(grid_out.read())
                            submission["model_answer_images"] = images_list
                    except Exception as e:
                        logger.error(f"Error retrieving model answer for student: {e}")
                        submission["model_answer_images"] = []

        elif user.role == "teacher" and include_images:
            exam_file = await db.exam_files.find_one(
                {"exam_id": submission["exam_id"]},
                {"_id": 0, "question_paper_gridfs_id": 1, "gridfs_id": 1}
            )
            if exam_file:
                file_id_str = exam_file.get("question_paper_gridfs_id") or exam_file.get("gridfs_id")
                if file_id_str:
                    try:
                        file_oid = ObjectId(file_id_str)
                        if fs.exists(file_oid):
                            grid_out = fs.get(file_oid)
                            images_list = pickle.loads(grid_out.read())
                            submission["question_paper_images"] = images_list
                    except Exception as e:
                        logger.error(f"Error retrieving question paper: {e}")
                        submission["question_paper_images"] = []

        # Fetch images from separate collection if they exist
        if include_images and submission.get("has_images"):
            submission_images = await db.submission_images.find_one(
                {"submission_id": submission_id},
                {"_id": 0, "file_images": 1, "annotated_images": 1}
            )
            if submission_images:
                submission["file_images"] = submission_images.get("file_images", [])
                submission["annotated_images"] = submission_images.get("annotated_images", [])
            else:
                submission["file_images"] = []
                submission["annotated_images"] = []
        elif not include_images:
            submission.pop("file_images", None)
            submission.pop("annotated_images", None)

        return serialize_doc(submission)

    except Exception as e:
        logger.error(f"Error fetching submission {submission_id}: {e}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/submissions/{submission_id}")
async def update_submission(
    submission_id: str,
    updates: dict,
    user: User = Depends(get_current_user)
):
    """Update submission scores and feedback"""
    from app.services.grading import track_teacher_edits, calculate_edit_distance

    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can update submissions")

    original_submission = await db.submissions.find_one({"submission_id": submission_id}, {"_id": 0})
    if not original_submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    question_scores = updates.get("question_scores", [])
    total_score = sum(qs.get("obtained_marks", 0) for qs in question_scores)

    exam = await db.exams.find_one(
        {"exam_id": original_submission["exam_id"]},
        {"_id": 0, "total_marks": 1, "teacher_id": 1}
    )
    total_marks = exam.get("total_marks", 100) if exam else 100
    percentage = (total_score / total_marks) * 100 if total_marks > 0 else 0

    asyncio.create_task(track_teacher_edits(
        submission_id=submission_id,
        exam_id=original_submission["exam_id"],
        teacher_id=exam.get("teacher_id", user.user_id) if exam else user.user_id,
        original_scores=original_submission.get("question_scores", []),
        new_scores=question_scores
    ))

    await db.submissions.update_one(
        {"submission_id": submission_id},
        {"$set": {
            "question_scores": question_scores,
            "total_score": total_score,
            "percentage": round(percentage, 2),
            "status": "teacher_reviewed"
        }}
    )

    return {"message": "Submission updated", "total_score": total_score, "percentage": percentage}


@router.put("/submissions/{submission_id}/unapprove")
async def unapprove_submission(submission_id: str, user: User = Depends(get_current_user)):
    """Revert a submission back to pending review status"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can unapprove submissions")

    submission = await db.submissions.find_one({"submission_id": submission_id}, {"_id": 0})
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    await db.submissions.update_one(
        {"submission_id": submission_id},
        {"$set": {"status": "pending_review", "is_reviewed": False}}
    )

    return {"message": "Submission reverted to pending review"}


@router.delete("/submissions/{submission_id}")
async def delete_submission(submission_id: str, user: User = Depends(get_current_user)):
    """Delete a specific submission (student paper)"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can delete submissions")

    submission = await db.submissions.find_one({"submission_id": submission_id}, {"_id": 0})
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    exam = await db.exams.find_one({
        "exam_id": submission["exam_id"],
        "teacher_id": user.user_id
    }, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=403, detail="You don't have permission to delete this submission")

    await db.submissions.delete_one({"submission_id": submission_id})
    await db.re_evaluations.delete_many({"submission_id": submission_id})

    return {"message": "Submission deleted successfully"}


@router.get("/exams/{exam_id}/submissions")
async def get_exam_submissions(exam_id: str, user: User = Depends(get_current_user)):
    """Get all submissions for a specific exam"""
    try:
        if user.role != "teacher":
            raise HTTPException(status_code=403, detail="Only teachers can view submissions")

        exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id}, {"_id": 0})
        if not exam:
            raise HTTPException(status_code=404, detail="Exam not found")

        submissions = await db.submissions.find(
            {"exam_id": exam_id},
            {"_id": 0, "file_data": 0, "file_images": 0}
        ).to_list(1000)

        return serialize_doc(submissions)
    except Exception as e:
        logger.error(f"Error fetching submissions for exam {exam_id}: {e}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/exams/{exam_id}/bulk-approve")
async def bulk_approve_submissions(exam_id: str, user: User = Depends(get_current_user)):
    """Mark all submissions in an exam as reviewed"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can approve submissions")

    exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    result = await db.submissions.update_many(
        {"exam_id": exam_id, "status": {"$ne": "teacher_reviewed"}},
        {"$set": {"status": "teacher_reviewed", "is_reviewed": True}}
    )

    return {"message": f"Approved {result.modified_count} submissions"}
