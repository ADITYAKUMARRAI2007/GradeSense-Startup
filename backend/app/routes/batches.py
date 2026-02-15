"""Batch routes."""

from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timezone
from typing import Optional
import uuid

from app.database import db
from app.deps import get_current_user
from app.models.user import User
from app.models.batch import BatchCreate
from app.utils.serialization import serialize_doc

router = APIRouter(tags=["batches"])


@router.get("/batches")
async def get_batches(user: User = Depends(get_current_user)):
    """Get all batches for current teacher"""
    if user.role == "teacher":
        batches = await db.batches.find(
            {"teacher_id": user.user_id},
            {"_id": 0}
        ).to_list(100)

        # Enrich with student count
        for batch in batches:
            student_count = await db.users.count_documents({
                "batches": batch["batch_id"],
                "role": "student"
            })
            batch["student_count"] = student_count
    else:
        batches = await db.batches.find(
            {"students": user.user_id},
            {"_id": 0}
        ).to_list(100)
    return serialize_doc(batches)


@router.get("/batches/{batch_id}")
async def get_batch(batch_id: str, user: User = Depends(get_current_user)):
    """Get batch details with students"""
    batch = await db.batches.find_one(
        {"batch_id": batch_id},
        {"_id": 0}
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    # Get students in this batch
    students = await db.users.find(
        {"batches": batch_id, "role": "student"},
        {"_id": 0, "user_id": 1, "name": 1, "email": 1, "student_id": 1}
    ).to_list(500)

    batch["students_list"] = students
    batch["student_count"] = len(students)

    # Get exams for this batch
    exams = await db.exams.find(
        {"batch_id": batch_id},
        {"_id": 0, "exam_id": 1, "exam_name": 1, "status": 1}
    ).to_list(100)
    batch["exams"] = exams

    return batch


@router.post("/batches")
async def create_batch(batch: BatchCreate, user: User = Depends(get_current_user)):
    """Create a new batch"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can create batches")

    # Check for duplicate name
    existing = await db.batches.find_one({
        "name": batch.name,
        "teacher_id": user.user_id
    })
    if existing:
        raise HTTPException(status_code=400, detail="A batch with this name already exists")

    batch_id = f"batch_{uuid.uuid4().hex[:8]}"
    new_batch = {
        "batch_id": batch_id,
        "name": batch.name,
        "teacher_id": user.user_id,
        "students": [],
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.batches.insert_one(new_batch)
    new_batch.pop("_id", None)
    return new_batch


@router.put("/batches/{batch_id}")
async def update_batch(batch_id: str, batch: BatchCreate, user: User = Depends(get_current_user)):
    """Update batch name"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can update batches")

    # Check for duplicate name (excluding current batch)
    existing = await db.batches.find_one({
        "name": batch.name,
        "teacher_id": user.user_id,
        "batch_id": {"$ne": batch_id}
    })
    if existing:
        raise HTTPException(status_code=400, detail="A batch with this name already exists")

    result = await db.batches.update_one(
        {"batch_id": batch_id, "teacher_id": user.user_id},
        {"$set": {"name": batch.name}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Batch not found")
    return {"message": "Batch updated"}


@router.delete("/batches/{batch_id}")
async def delete_batch(batch_id: str, user: User = Depends(get_current_user)):
    """Delete a batch (only if empty)"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can delete batches")

    # Check if batch has students
    student_count = await db.users.count_documents({
        "batches": batch_id,
        "role": "student"
    })
    if student_count > 0:
        raise HTTPException(status_code=400, detail=f"Cannot delete batch with {student_count} students. Remove students first.")

    # Check if batch has exams
    exam_count = await db.exams.count_documents({"batch_id": batch_id})
    if exam_count > 0:
        raise HTTPException(status_code=400, detail=f"Cannot delete batch with {exam_count} exams. Delete exams first.")

    result = await db.batches.delete_one({
        "batch_id": batch_id,
        "teacher_id": user.user_id
    })
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Batch not found")
    return {"message": "Batch deleted"}


@router.put("/batches/{batch_id}/close")
async def close_batch(batch_id: str, user: User = Depends(get_current_user)):
    """Close/archive a batch"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can close batches")

    batch = await db.batches.find_one({"batch_id": batch_id, "teacher_id": user.user_id}, {"_id": 0})
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    await db.batches.update_one(
        {"batch_id": batch_id},
        {"$set": {
            "status": "closed",
            "closed_at": datetime.now(timezone.utc).isoformat()
        }}
    )

    return {"message": "Batch closed successfully"}


@router.put("/batches/{batch_id}/reopen")
async def reopen_batch(batch_id: str, user: User = Depends(get_current_user)):
    """Reopen a closed batch"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can reopen batches")

    batch = await db.batches.find_one({"batch_id": batch_id, "teacher_id": user.user_id}, {"_id": 0})
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    await db.batches.update_one(
        {"batch_id": batch_id},
        {"$set": {
            "status": "active",
            "reopened_at": datetime.now(timezone.utc).isoformat()
        }}
    )

    return {"message": "Batch reopened successfully"}


@router.post("/batches/{batch_id}/students")
async def add_student_to_batch(batch_id: str, data: dict, user: User = Depends(get_current_user)):
    """Add an existing student to a batch"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can manage batch students")

    batch = await db.batches.find_one({"batch_id": batch_id, "teacher_id": user.user_id}, {"_id": 0})
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    if batch.get("status") == "closed":
        raise HTTPException(status_code=400, detail="Cannot add students to a closed batch")

    student_id = data.get("student_id")
    if not student_id:
        raise HTTPException(status_code=400, detail="Student ID is required")

    # Verify student exists and belongs to teacher
    student = await db.users.find_one({"user_id": student_id, "teacher_id": user.user_id, "role": "student"}, {"_id": 0})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    # Check if student is already in batch
    student_batches = student.get("batches", [])
    if batch_id in student_batches:
        raise HTTPException(status_code=400, detail="Student is already in this batch")

    # Add batch to student's batches
    await db.users.update_one(
        {"user_id": student_id},
        {"$addToSet": {"batches": batch_id}}
    )

    return {"message": "Student added to batch successfully"}


@router.delete("/batches/{batch_id}/students/{student_id}")
async def remove_student_from_batch(batch_id: str, student_id: str, user: User = Depends(get_current_user)):
    """Remove a student from a batch"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can manage batch students")

    batch = await db.batches.find_one({"batch_id": batch_id, "teacher_id": user.user_id}, {"_id": 0})
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    if batch.get("status") == "closed":
        raise HTTPException(status_code=400, detail="Cannot remove students from a closed batch")

    # Verify student exists
    student = await db.users.find_one({"user_id": student_id, "teacher_id": user.user_id, "role": "student"}, {"_id": 0})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    # Check if student is in the batch
    student_batches = student.get("batches", [])
    if batch_id not in student_batches:
        raise HTTPException(status_code=400, detail="Student is not in this batch")

    # Remove batch from student's batches
    await db.users.update_one(
        {"user_id": student_id},
        {"$pull": {"batches": batch_id}}
    )

    return {"message": "Student removed from batch successfully"}


@router.get("/batches/{batch_id}/stats")
async def get_batch_stats(batch_id: str, user: User = Depends(get_current_user)):
    """Get batch statistics"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can view batch stats")

    batch = await db.batches.find_one({"batch_id": batch_id, "teacher_id": user.user_id}, {"_id": 0})
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    # Get students
    students = await db.users.find(
        {"batches": batch_id, "role": "student"},
        {"_id": 0, "user_id": 1, "name": 1}
    ).to_list(500)

    # Get exams
    exams = await db.exams.find(
        {"batch_id": batch_id},
        {"_id": 0, "exam_id": 1, "exam_name": 1, "total_marks": 1}
    ).to_list(100)

    exam_ids = [e["exam_id"] for e in exams]

    # Get submissions
    submissions = await db.submissions.find(
        {"exam_id": {"$in": exam_ids}},
        {"_id": 0, "student_id": 1, "percentage": 1, "exam_id": 1}
    ).to_list(10000)

    # Calculate stats
    total_students = len(students)
    total_exams = len(exams)
    total_submissions = len(submissions)

    avg_percentage = 0
    if submissions:
        avg_percentage = sum(s.get("percentage", 0) for s in submissions) / len(submissions)

    return {
        "batch_id": batch_id,
        "batch_name": batch.get("name"),
        "total_students": total_students,
        "total_exams": total_exams,
        "total_submissions": total_submissions,
        "avg_percentage": round(avg_percentage, 1)
    }


@router.get("/batches/{batch_id}/students")
async def get_batch_students(batch_id: str, user: User = Depends(get_current_user)):
    """Get students in a batch with their performance"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can view batch students")

    batch = await db.batches.find_one({"batch_id": batch_id, "teacher_id": user.user_id}, {"_id": 0})
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    students = await db.users.find(
        {"batches": batch_id, "role": "student"},
        {"_id": 0}
    ).to_list(500)

    # Get exam IDs for this batch
    exams = await db.exams.find(
        {"batch_id": batch_id},
        {"_id": 0, "exam_id": 1}
    ).to_list(100)
    exam_ids = [e["exam_id"] for e in exams]

    # Enrich with performance data
    for student in students:
        subs = await db.submissions.find(
            {"student_id": student["user_id"], "exam_id": {"$in": exam_ids}},
            {"_id": 0, "percentage": 1}
        ).to_list(100)

        if subs:
            percentages = [s.get("percentage", 0) for s in subs]
            student["avg_percentage"] = round(sum(percentages) / len(percentages), 1)
            student["exams_taken"] = len(subs)
        else:
            student["avg_percentage"] = 0
            student["exams_taken"] = 0

    return serialize_doc(students)
