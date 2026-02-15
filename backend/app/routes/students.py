"""Student management routes."""

from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timezone
from typing import Optional
import uuid

from app.database import db
from app.deps import get_current_user
from app.models.user import User, UserCreate
from app.utils.serialization import serialize_doc
from app.config import logger

router = APIRouter(tags=["students"])


@router.get("/students")
async def get_students(batch_id: Optional[str] = None, user: User = Depends(get_current_user)):
    """Get students managed by this teacher"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can view students")

    query = {"role": "student", "teacher_id": user.user_id}
    if batch_id:
        query["batches"] = batch_id

    students = await db.users.find(query, {"_id": 0}).to_list(500)
    return serialize_doc(students)


@router.get("/students/my-exams")
async def get_my_exams(user: User = Depends(get_current_user)):
    """Get exams assigned to the current student for submission"""
    if user.role != "student":
        raise HTTPException(status_code=403, detail="Only students can access this")

    # Find exams where this student is assigned and exam is in student-upload mode
    exams = await db.exams.find(
        {
            "students": user.user_id,
            "is_student_upload": True
        },
        {"_id": 0}
    ).to_list(100)

    # Enrich with submission status
    for exam in exams:
        submission = await db.submissions.find_one(
            {
                "exam_id": exam["exam_id"],
                "student_id": user.user_id
            },
            {"_id": 0, "submission_id": 1, "status": 1, "percentage": 1, "obtained_marks": 1, "total_marks": 1}
        )

        if submission:
            exam["submitted"] = True
            exam["submission_status"] = submission.get("status", "submitted")
            exam["score"] = submission.get("percentage")
            exam["submission_id"] = submission.get("submission_id")
        else:
            exam["submitted"] = False
            exam["submission_status"] = "pending"

    return serialize_doc(exams)


@router.get("/students/{student_user_id}")
async def get_student_detail(student_user_id: str, user: User = Depends(get_current_user)):
    """Get detailed student information with performance analytics"""
    try:
        student = await db.users.find_one(
            {"user_id": student_user_id},
            {"_id": 0}
        )
        if not student:
            raise HTTPException(status_code=404, detail="Student not found")

        # Get all submissions for this student
        submissions = await db.submissions.find(
            {"student_id": student_user_id},
            {"_id": 0, "file_data": 0, "file_images": 0}
        ).to_list(100)

        # Calculate overall stats
        if submissions:
            percentages = [s.get("percentage", 0) for s in submissions]
            avg_percentage = sum(percentages) / len(percentages)
            highest = max(percentages)
            lowest = min(percentages)

            # Trend calculation (last 5 vs previous 5)
            sorted_subs = sorted(submissions, key=lambda x: x.get("created_at", ""))
            if len(sorted_subs) >= 2:
                recent = sorted_subs[-min(5, len(sorted_subs)):]
                recent_avg = sum(s.get("percentage", 0) for s in recent) / len(recent)
                if len(sorted_subs) > 5:
                    older = sorted_subs[-min(10, len(sorted_subs)):-5]
                    older_avg = sum(s.get("percentage", 0) for s in older) / len(older) if older else recent_avg
                    trend = recent_avg - older_avg
                else:
                    trend = 0
            else:
                trend = 0
        else:
            avg_percentage = 0
            highest = 0
            lowest = 0
            trend = 0

        # Subject-wise performance
        subject_performance = {}
        for sub in submissions:
            exam = await db.exams.find_one({"exam_id": sub["exam_id"]}, {"_id": 0, "subject_id": 1})
            if exam:
                subj = await db.subjects.find_one({"subject_id": exam["subject_id"]}, {"_id": 0, "name": 1})
                subj_name = subj.get("name", "Unknown") if subj else "Unknown"
                if subj_name not in subject_performance:
                    subject_performance[subj_name] = {"scores": [], "total_exams": 0}
                subject_performance[subj_name]["scores"].append(sub.get("percentage", 0))
                subject_performance[subj_name]["total_exams"] += 1

        for subj_name, data in subject_performance.items():
            data["average"] = sum(data["scores"]) / len(data["scores"]) if data["scores"] else 0
            data["highest"] = max(data["scores"]) if data["scores"] else 0
            data["lowest"] = min(data["scores"]) if data["scores"] else 0

        # ====== TOPIC-BASED PERFORMANCE ANALYSIS ======
        topic_performance = {}

        for sub in submissions:
            exam = await db.exams.find_one({"exam_id": sub["exam_id"]}, {"_id": 0})
            if not exam:
                continue

            exam_name = exam.get("exam_name", "Unknown Exam")
            exam_date = sub.get("created_at", "")
            exam_questions = exam.get("questions", [])

            question_topics = {}
            for q in exam_questions:
                q_num = q.get("question_number")
                topics = q.get("topic_tags", [])
                if not topics:
                    subj = await db.subjects.find_one({"subject_id": exam.get("subject_id")}, {"_id": 0, "name": 1})
                    topics = [subj.get("name", "General")] if subj else ["General"]
                question_topics[q_num] = topics

            for qs in sub.get("question_scores", []):
                q_num = qs.get("question_number")
                pct = (qs["obtained_marks"] / qs["max_marks"]) * 100 if qs.get("max_marks", 0) > 0 else 0
                topics = question_topics.get(q_num, ["General"])

                for topic in topics:
                    if topic not in topic_performance:
                        topic_performance[topic] = []
                    topic_performance[topic].append({
                        "score": pct,
                        "exam_date": exam_date,
                        "exam_name": exam_name,
                        "question_number": q_num
                    })

        # Analyze topics
        weak_topics = []
        strong_topics = []

        for topic, performances in topic_performance.items():
            if len(performances) == 0:
                continue

            sorted_perfs = sorted(performances, key=lambda x: x.get("exam_date", ""))
            avg_score = sum(p["score"] for p in sorted_perfs) / len(sorted_perfs)

            topic_trend = 0
            trend_text = "stable"
            if len(sorted_perfs) >= 2:
                mid = len(sorted_perfs) // 2
                first_half_avg = sum(p["score"] for p in sorted_perfs[:mid]) / mid if mid > 0 else 0
                second_half_avg = sum(p["score"] for p in sorted_perfs[mid:]) / (len(sorted_perfs) - mid)
                topic_trend = second_half_avg - first_half_avg

                if topic_trend > 10:
                    trend_text = "improving"
                elif topic_trend < -10:
                    trend_text = "declining"
                else:
                    trend_text = "stable"

            topic_data = {
                "topic": topic,
                "avg_score": round(avg_score, 1),
                "total_attempts": len(sorted_perfs),
                "trend": round(topic_trend, 1),
                "trend_text": trend_text,
                "recent_score": round(sorted_perfs[-1]["score"], 1) if sorted_perfs else 0,
                "first_score": round(sorted_perfs[0]["score"], 1) if sorted_perfs else 0
            }

            if avg_score < 50:
                weak_topics.append(topic_data)
            elif avg_score >= 75:
                strong_topics.append(topic_data)

        weak_topics = sorted(weak_topics, key=lambda x: x["avg_score"])[:5]
        strong_topics = sorted(strong_topics, key=lambda x: -x["avg_score"])[:5]

        # Generate smart recommendations
        recommendations = []
        declining_topics = [t for t in weak_topics if t["trend_text"] == "declining"]
        if declining_topics:
            recommendations.append(f"⚠️ {declining_topics[0]['topic']} needs urgent attention - performance is declining")

        improving_weak = [t for t in weak_topics if t["trend_text"] == "improving"]
        if improving_weak:
            recommendations.append(f"📈 Great progress in {improving_weak[0]['topic']}! Keep practicing to master it")

        stable_weak = [t for t in weak_topics if t["trend_text"] == "stable" and t["total_attempts"] >= 2]
        if stable_weak:
            recommendations.append(f"💡 Focus more on {stable_weak[0]['topic']} - needs consistent practice")

        if strong_topics:
            recommendations.append(f"⭐ Excellent in {strong_topics[0]['topic']}! Consider helping peers")

        if not recommendations:
            recommendations = [
                "Complete more exams to get detailed topic insights",
                "Focus on understanding concepts deeply",
                "Practice regularly across all topics"
            ]

        return serialize_doc({
            "student": student,
            "stats": {
                "total_exams": len(submissions),
                "avg_percentage": round(avg_percentage, 1),
                "highest_score": highest,
                "lowest_score": lowest,
                "trend": round(trend, 1)
            },
            "subject_performance": subject_performance,
            "recent_submissions": submissions[-10:],
            "weak_topics": weak_topics,
            "strong_topics": strong_topics,
            "topic_performance": topic_performance,
            "recommendations": recommendations
        })
    except Exception as e:
        logger.error(f"Error fetching student detail {student_user_id}: {e}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/students")
async def create_student(student: UserCreate, user: User = Depends(get_current_user)):
    """Create a new student"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can create students")

    # Validate student ID format if provided
    if student.student_id:
        student_id = student.student_id.strip()
        if not (3 <= len(student_id) <= 20 and student_id.replace("-", "").isalnum()):
            raise HTTPException(
                status_code=400,
                detail="Student ID must be 3-20 alphanumeric characters (letters, numbers, hyphens allowed)"
            )

        # Check if student ID already exists
        existing_id = await db.users.find_one({"student_id": student_id, "role": "student"})
        if existing_id:
            raise HTTPException(
                status_code=400,
                detail=f"Student ID {student_id} already exists"
            )
    else:
        # Auto-generate student ID
        student_id = f"STU{uuid.uuid4().hex[:6].upper()}"

    # Check if email already exists
    existing = await db.users.find_one({"email": student.email})
    if existing:
        raise HTTPException(status_code=400, detail="Student with this email already exists")

    user_id = f"user_{uuid.uuid4().hex[:12]}"

    new_student = {
        "user_id": user_id,
        "email": student.email,
        "name": student.name,
        "role": "student",
        "student_id": student_id,
        "batches": student.batches,
        "teacher_id": user.user_id,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.users.insert_one(new_student)

    # Add student to batches
    for batch_id in student.batches:
        await db.batches.update_one(
            {"batch_id": batch_id},
            {"$addToSet": {"students": user_id}}
        )

    return {
        "user_id": user_id,
        "student_id": student_id,
        "email": student.email,
        "name": student.name,
        "batches": student.batches
    }


@router.put("/students/{student_user_id}")
async def update_student(student_user_id: str, student: UserCreate, user: User = Depends(get_current_user)):
    """Update student details"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can update students")

    result = await db.users.update_one(
        {"user_id": student_user_id, "role": "student"},
        {"$set": {
            "name": student.name,
            "email": student.email,
            "student_id": student.student_id,
            "batches": student.batches
        }}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Student not found")

    return {"message": "Student updated"}


@router.delete("/students/{student_user_id}")
async def delete_student(student_user_id: str, user: User = Depends(get_current_user)):
    """Delete a student"""
    result = await db.users.delete_one({
        "user_id": student_user_id,
        "teacher_id": user.user_id
    })
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Student not found")
    return {"message": "Student deleted"}


@router.get("/students/{student_id}/analytics")
async def get_student_analytics(
    student_id: str,
    user: User = Depends(get_current_user)
):
    """Get analytics for a specific student"""
    student = await db.users.find_one({"user_id": student_id}, {"_id": 0})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    # Get all submissions
    submissions = await db.submissions.find(
        {"student_id": student_id},
        {"_id": 0, "file_data": 0, "file_images": 0}
    ).to_list(100)

    # Calculate stats
    if submissions:
        percentages = [s.get("percentage", 0) for s in submissions]
        avg = sum(percentages) / len(percentages)
        highest = max(percentages)
        lowest = min(percentages)
    else:
        avg = highest = lowest = 0

    # Get exam details for each submission
    enriched_submissions = []
    for sub in submissions:
        exam = await db.exams.find_one({"exam_id": sub["exam_id"]}, {"_id": 0, "exam_name": 1, "subject_id": 1})
        if exam:
            sub["exam_name"] = exam.get("exam_name", "Unknown")
            subj = await db.subjects.find_one({"subject_id": exam.get("subject_id")}, {"_id": 0, "name": 1})
            sub["subject_name"] = subj.get("name", "Unknown") if subj else "Unknown"
        enriched_submissions.append(sub)

    return serialize_doc({
        "student": student,
        "stats": {
            "total_exams": len(submissions),
            "avg_percentage": round(avg, 1),
            "highest_score": highest,
            "lowest_score": lowest
        },
        "submissions": enriched_submissions
    })
