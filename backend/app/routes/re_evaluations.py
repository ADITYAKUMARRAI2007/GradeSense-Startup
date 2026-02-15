"""Re-evaluation request routes."""

from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timezone
import uuid

from app.database import db
from app.deps import get_current_user
from app.models.user import User
from app.models.reevaluation import ReEvaluationCreate
from app.services.notifications import create_notification

router = APIRouter(tags=["re-evaluations"])


@router.get("/re-evaluations")
async def get_re_evaluations(user: User = Depends(get_current_user)):
    """Get re-evaluation requests"""
    if user.role == "teacher":
        exams = await db.exams.find({"teacher_id": user.user_id}, {"exam_id": 1, "_id": 0}).to_list(100)
        exam_ids = [e["exam_id"] for e in exams]
        requests = await db.re_evaluations.find(
            {"exam_id": {"$in": exam_ids}},
            {"_id": 0}
        ).to_list(100)
    else:
        requests = await db.re_evaluations.find(
            {"student_id": user.user_id},
            {"_id": 0}
        ).to_list(50)

    for req in requests:
        exam = await db.exams.find_one({"exam_id": req["exam_id"]}, {"_id": 0, "exam_name": 1})
        req["exam_name"] = exam.get("exam_name", "Unknown") if exam else "Unknown"

    return requests


@router.post("/re-evaluations")
async def create_re_evaluation(
    request: ReEvaluationCreate,
    user: User = Depends(get_current_user)
):
    """Create re-evaluation request"""
    submission = await db.submissions.find_one({"submission_id": request.submission_id}, {"_id": 0})
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    exam = await db.exams.find_one({"exam_id": submission["exam_id"]}, {"_id": 0})

    request_id = f"reeval_{uuid.uuid4().hex[:8]}"
    new_request = {
        "request_id": request_id,
        "submission_id": request.submission_id,
        "student_id": user.user_id,
        "student_name": user.name,
        "exam_id": submission["exam_id"],
        "questions": request.questions,
        "reason": request.reason,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    await db.re_evaluations.insert_one(new_request)

    if exam:
        await create_notification(
            user_id=exam["teacher_id"],
            notification_type="re_evaluation_request",
            title="New Re-evaluation Request",
            message=f"{user.name} requested re-evaluation for {exam.get('exam_name', 'exam')}",
            link="/teacher/re-evaluations"
        )

    return {"request_id": request_id, "status": "pending"}


@router.put("/re-evaluations/{request_id}")
async def update_re_evaluation(
    request_id: str,
    updates: dict,
    user: User = Depends(get_current_user)
):
    """Update re-evaluation request (teacher response)"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can respond")

    re_eval = await db.re_evaluations.find_one({"request_id": request_id}, {"_id": 0})
    if not re_eval:
        raise HTTPException(status_code=404, detail="Re-evaluation request not found")

    await db.re_evaluations.update_one(
        {"request_id": request_id},
        {"$set": {
            "status": updates.get("status", "resolved"),
            "response": updates.get("response", ""),
            "responded_at": datetime.now(timezone.utc).isoformat()
        }}
    )

    await create_notification(
        user_id=re_eval["student_id"],
        notification_type="re_evaluation_response",
        title="Re-evaluation Response",
        message=f"Teacher responded to your re-evaluation request",
        link="/student/re-evaluation"
    )

    return {"message": "Re-evaluation updated"}
