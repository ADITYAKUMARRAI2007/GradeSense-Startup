"""Global search route."""

from fastapi import APIRouter, Depends

from app.database import db
from app.deps import get_current_user
from app.models.user import User

router = APIRouter(tags=["search"])


@router.post("/search")
async def global_search(query: str, user: User = Depends(get_current_user)):
    """Global search across exams, students, batches, submissions"""
    results = {
        "exams": [],
        "students": [],
        "batches": [],
        "submissions": []
    }

    if not query or len(query) < 2:
        return results

    search_regex = {"$regex": query, "$options": "i"}

    # Search exams
    if user.role == "teacher":
        exams = await db.exams.find(
            {"teacher_id": user.user_id, "exam_name": search_regex},
            {"_id": 0, "exam_id": 1, "exam_name": 1, "exam_date": 1, "status": 1}
        ).limit(10).to_list(10)
        results["exams"] = exams

        # Search students
        students = await db.users.find(
            {
                "teacher_id": user.user_id,
                "role": "student",
                "$or": [
                    {"name": search_regex},
                    {"student_id": search_regex},
                    {"email": search_regex}
                ]
            },
            {"_id": 0, "user_id": 1, "name": 1, "student_id": 1, "email": 1}
        ).limit(10).to_list(10)
        results["students"] = students

        # Search batches
        batches = await db.batches.find(
            {"teacher_id": user.user_id, "name": search_regex},
            {"_id": 0, "batch_id": 1, "name": 1}
        ).limit(10).to_list(10)
        results["batches"] = batches

        # Search submissions by student name
        submissions = await db.submissions.find(
            {"student_name": search_regex},
            {"_id": 0, "submission_id": 1, "student_name": 1, "exam_id": 1, "percentage": 1}
        ).limit(10).to_list(10)
        results["submissions"] = submissions

    elif user.role == "student":
        # Students can only search their own data
        exams = await db.submissions.find(
            {"student_id": user.user_id},
            {"_id": 0, "exam_id": 1, "submission_id": 1}
        ).limit(10).to_list(10)

        if exams:
            exam_ids = [e["exam_id"] for e in exams]
            exam_details = await db.exams.find(
                {"exam_id": {"$in": exam_ids}, "exam_name": search_regex},
                {"_id": 0, "exam_id": 1, "exam_name": 1, "exam_date": 1}
            ).to_list(10)
            results["exams"] = exam_details

    return results
