"""Subject routes."""

from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timezone
import uuid

from app.database import db
from app.deps import get_current_user
from app.models.user import User
from app.models.subject import SubjectCreate

router = APIRouter(tags=["subjects"])


@router.get("/subjects")
async def get_subjects(user: User = Depends(get_current_user)):
    """Get all subjects"""
    if user.role == "teacher":
        subjects = await db.subjects.find(
            {"teacher_id": user.user_id},
            {"_id": 0}
        ).to_list(100)
    else:
        # Students see subjects from their batches
        exams = await db.exams.find(
            {"batch_id": {"$in": user.batches}},
            {"subject_id": 1, "_id": 0}
        ).to_list(100)
        subject_ids = list(set(e["subject_id"] for e in exams))
        subjects = await db.subjects.find(
            {"subject_id": {"$in": subject_ids}},
            {"_id": 0}
        ).to_list(100)
    return subjects


@router.post("/subjects")
async def create_subject(subject: SubjectCreate, user: User = Depends(get_current_user)):
    """Create a new subject"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can create subjects")

    # Check for duplicate
    existing = await db.subjects.find_one({
        "name": subject.name,
        "teacher_id": user.user_id
    })
    if existing:
        raise HTTPException(status_code=400, detail="Subject already exists")

    subject_id = f"subj_{uuid.uuid4().hex[:8]}"
    new_subject = {
        "subject_id": subject_id,
        "name": subject.name,
        "teacher_id": user.user_id,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.subjects.insert_one(new_subject)
    return {"subject_id": subject_id, "name": subject.name}
