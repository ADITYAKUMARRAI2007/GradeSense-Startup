"""Analytics routes — teacher dashboard, class reports, topic mastery, insights, etc."""

import json
import re
import uuid
from typing import Optional, Dict, List
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException

from app.database import db
from app.config import logger, get_llm_api_key
from app.deps import get_current_user, get_admin_user
from app.models.user import User
from app.models.analytics import NaturalLanguageQuery
from app.services.analytics import extract_topic_from_rubric
from app.services.notifications import create_notification
from app.services.llm import LlmChat, UserMessage, ImageContent

router = APIRouter(tags=["analytics"])


# ============== DASHBOARD ==============

@router.get("/analytics/dashboard")
async def get_dashboard_analytics(user: User = Depends(get_current_user)):
    """Get dashboard analytics for teacher"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Teacher only")

    total_exams = await db.exams.count_documents({"teacher_id": user.user_id})
    total_batches = await db.batches.count_documents({"teacher_id": user.user_id})
    total_students = await db.users.count_documents({"teacher_id": user.user_id, "role": "student"})

    exams = await db.exams.find({"teacher_id": user.user_id}, {"exam_id": 1, "_id": 0}).to_list(100)
    exam_ids = [e["exam_id"] for e in exams]

    total_submissions = await db.submissions.count_documents({"exam_id": {"$in": exam_ids}})
    pending_reviews = await db.submissions.count_documents({
        "exam_id": {"$in": exam_ids},
        "status": "ai_graded"
    })
    pending_reeval = await db.re_evaluations.count_documents({
        "exam_id": {"$in": exam_ids},
        "status": "pending"
    })

    submissions = await db.submissions.find(
        {"exam_id": {"$in": exam_ids}},
        {"percentage": 1, "_id": 0}
    ).to_list(500)
    avg_score = sum(s.get("percentage", 0) for s in submissions) / len(submissions) if submissions else 0

    recent_submissions = await db.submissions.find(
        {"exam_id": {"$in": exam_ids}},
        {"_id": 0, "submission_id": 1, "student_name": 1, "exam_id": 1, "student_id": 1, "obtained_marks": 1, "total_marks": 1, "percentage": 1, "total_score": 1, "status": 1, "created_at": 1, "graded_at": 1}
    ).sort("graded_at", -1).limit(10).to_list(10)

    return {
        "stats": {
            "total_exams": total_exams,
            "total_batches": total_batches,
            "total_students": total_students,
            "total_submissions": total_submissions,
            "pending_reviews": pending_reviews,
            "pending_reeval": pending_reeval,
            "avg_score": round(avg_score, 1)
        },
        "recent_submissions": recent_submissions
    }


# ============== CLASS REPORT ==============

@router.get("/analytics/class-report")
async def get_class_report(
    batch_id: Optional[str] = None,
    subject_id: Optional[str] = None,
    exam_id: Optional[str] = None,
    user: User = Depends(get_current_user)
):
    """Get class report analytics"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Teacher only")

    exam_query = {"teacher_id": user.user_id}
    if batch_id:
        exam_query["batch_id"] = batch_id
    if subject_id:
        exam_query["subject_id"] = subject_id
    if exam_id:
        exam_query["exam_id"] = exam_id

    exams = await db.exams.find(exam_query, {"_id": 0}).to_list(100)
    exam_ids = [e["exam_id"] for e in exams]

    submissions = await db.submissions.find(
        {"exam_id": {"$in": exam_ids}},
        {"_id": 0}
    ).to_list(500)

    if not submissions:
        return {
            "overview": {
                "total_students": 0, "avg_score": 0, "highest_score": 0,
                "lowest_score": 0, "pass_percentage": 0
            },
            "score_distribution": [],
            "top_performers": [],
            "needs_attention": [],
            "question_analysis": []
        }

    percentages = [s["percentage"] for s in submissions]

    distribution = {
        "0-20": len([p for p in percentages if 0 <= p < 20]),
        "21-40": len([p for p in percentages if 20 <= p < 40]),
        "41-60": len([p for p in percentages if 40 <= p < 60]),
        "61-80": len([p for p in percentages if 60 <= p < 80]),
        "81-100": len([p for p in percentages if 80 <= p <= 100])
    }

    sorted_subs = sorted(submissions, key=lambda x: x["percentage"], reverse=True)
    top_performers = [
        {
            "name": s["student_name"],
            "student_id": s["student_id"],
            "score": s.get("obtained_marks") or s.get("total_score", 0),
            "percentage": s["percentage"]
        }
        for s in sorted_subs[:5]
    ]

    needs_attention = [
        {
            "name": s["student_name"],
            "student_id": s["student_id"],
            "score": s.get("obtained_marks") or s.get("total_score", 0),
            "percentage": s["percentage"]
        }
        for s in submissions if s["percentage"] < 40
    ][:10]

    question_analysis = []
    if submissions and submissions[0].get("question_scores"):
        num_questions = len(submissions[0]["question_scores"])
        for q_idx in range(num_questions):
            q_scores = []
            max_marks = 0
            for sub in submissions:
                if len(sub.get("question_scores", [])) > q_idx:
                    qs = sub["question_scores"][q_idx]
                    q_scores.append(qs["obtained_marks"])
                    max_marks = qs["max_marks"]
            if q_scores:
                avg = sum(q_scores) / len(q_scores)
                question_analysis.append({
                    "question": q_idx + 1,
                    "max_marks": max_marks,
                    "avg_score": round(avg, 2),
                    "percentage": round((avg / max_marks) * 100, 1) if max_marks > 0 else 0
                })

    return {
        "overview": {
            "total_students": len(submissions),
            "avg_score": round(sum(percentages) / len(percentages), 1),
            "highest_score": max(percentages),
            "lowest_score": min(percentages),
            "pass_percentage": round(len([p for p in percentages if p >= 40]) / len(percentages) * 100, 1)
        },
        "score_distribution": [{"range": k, "count": v} for k, v in distribution.items()],
        "top_performers": top_performers,
        "needs_attention": needs_attention,
        "question_analysis": question_analysis
    }


# ============== INSIGHTS ==============

@router.get("/analytics/insights")
async def get_class_insights(
    exam_id: Optional[str] = None,
    user: User = Depends(get_current_user)
):
    """Get AI-generated class insights"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Teacher only")

    exam_query = {"teacher_id": user.user_id}
    if exam_id:
        exam_query["exam_id"] = exam_id

    exams = await db.exams.find(exam_query, {"_id": 0}).to_list(10)
    exam_ids = [e["exam_id"] for e in exams]

    submissions = await db.submissions.find(
        {"exam_id": {"$in": exam_ids}},
        {"_id": 0, "question_scores": 1, "percentage": 1}
    ).to_list(200)

    if not submissions:
        return {
            "summary": "No submissions available for analysis.",
            "strengths": [], "weaknesses": [], "recommendations": []
        }

    question_stats = {}
    for sub in submissions:
        for qs in sub.get("question_scores", []):
            q_num = qs["question_number"]
            if q_num not in question_stats:
                question_stats[q_num] = {"scores": [], "max": qs["max_marks"]}
            question_stats[q_num]["scores"].append(qs["obtained_marks"])

    strengths = []
    weaknesses = []

    for q_num, stats in question_stats.items():
        avg = sum(stats["scores"]) / len(stats["scores"]) if stats["scores"] else 0
        pct = (avg / stats["max"]) * 100 if stats["max"] > 0 else 0
        if pct >= 70:
            strengths.append(f"Question {q_num}: {pct:.0f}% average")
        elif pct < 50:
            weaknesses.append(f"Question {q_num}: {pct:.0f}% average - needs attention")

    avg_class = sum(s["percentage"] for s in submissions) / len(submissions)

    recommendations = [
        "Review weak areas in upcoming classes",
        "Consider additional practice problems for struggling concepts",
        "Recognize top performers to encourage class participation"
    ]
    if avg_class < 50:
        recommendations.insert(0, "Class average is below 50% - consider remedial sessions")
    elif avg_class >= 75:
        recommendations.insert(0, "Excellent class performance! Consider advanced topics")

    return {
        "summary": f"Class average: {avg_class:.1f}%. Analyzed {len(submissions)} submissions across {len(exams)} exam(s).",
        "strengths": strengths,
        "weaknesses": weaknesses,
        "recommendations": recommendations
    }


# ============== MISCONCEPTIONS ==============

@router.get("/analytics/misconceptions")
async def get_misconceptions_analysis(
    exam_id: str,
    user: User = Depends(get_current_user)
):
    """AI-powered analysis of common misconceptions and why students fail"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Teacher only")

    exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    submissions = await db.submissions.find(
        {"exam_id": exam_id},
        {"_id": 0, "submission_id": 1, "student_name": 1, "question_scores": 1, "file_images": 1}
    ).to_list(100)

    if not submissions:
        return {"misconceptions": [], "question_insights": []}

    question_insights = []
    misconceptions = []

    for q_idx, question in enumerate(exam.get("questions", [])):
        q_num = question.get("question_number", q_idx + 1)
        q_scores = []
        wrong_answers = []

        for sub in submissions:
            for qs in sub.get("question_scores", []):
                if qs.get("question_number") == q_num:
                    pct = (qs["obtained_marks"] / qs["max_marks"]) * 100 if qs["max_marks"] > 0 else 0
                    q_scores.append(pct)
                    if pct < 60:
                        wrong_answers.append({
                            "student_name": sub["student_name"],
                            "submission_id": sub["submission_id"],
                            "obtained": qs["obtained_marks"],
                            "max": qs["max_marks"],
                            "feedback": qs.get("ai_feedback", ""),
                            "question_text": qs.get("question_text", "")
                        })

        if q_scores:
            avg_pct = sum(q_scores) / len(q_scores)
            fail_rate = len([s for s in q_scores if s < 60]) / len(q_scores) * 100

            question_insights.append({
                "question_number": q_num,
                "question_text": question.get("rubric", f"Question {q_num}"),
                "avg_percentage": round(avg_pct, 1),
                "fail_rate": round(fail_rate, 1),
                "total_students": len(q_scores),
                "failing_students": len(wrong_answers),
                "wrong_answers": wrong_answers[:5]
            })

            if fail_rate >= 30 and wrong_answers:
                misconceptions.append({
                    "question_number": q_num,
                    "fail_percentage": round(fail_rate, 1),
                    "affected_students": len(wrong_answers),
                    "sample_feedbacks": [wa["feedback"][:200] for wa in wrong_answers[:3] if wa["feedback"]]
                })

    ai_analysis = None
    if misconceptions:
        try:
            llm_key = get_llm_api_key()

            analysis_prompt = f"""Analyze these student misconceptions from exam "{exam.get('exam_name', 'Unknown')}":

{[{
    'question': m['question_number'],
    'fail_rate': f"{m['fail_percentage']}%",
    'sample_feedback': m['sample_feedbacks']
} for m in misconceptions[:5]]}

For each question with high failure rate, identify:
1. The likely conceptual confusion or mistake pattern
2. What concept students confused with another concept
3. A brief explanation of why this confusion happens

Return as JSON array with format:
[{{"question": 1, "confusion": "Students confused X with Y", "reason": "brief explanation", "recommendation": "teaching suggestion"}}]

Only return the JSON array, no other text."""

            chat = LlmChat(
                api_key=llm_key,
                session_id=f"misconceptions_{uuid.uuid4().hex[:8]}",
                system_message="You are an expert at analyzing student misconceptions and learning patterns."
            ).with_model("gemini", "gemini-2.5-flash").with_params(temperature=0)

            user_message = UserMessage(text=analysis_prompt)
            ai_response = await chat.send_message(user_message)

            try:
                cleaned = ai_response.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.split("```")[1]
                    if cleaned.startswith("json"):
                        cleaned = cleaned[4:]
                ai_analysis = json.loads(cleaned)
            except (json.JSONDecodeError, IndexError, ValueError):
                ai_analysis = None
        except Exception as e:
            logger.error(f"AI misconception analysis error: {e}")

    return {
        "exam_name": exam.get("exam_name"),
        "total_submissions": len(submissions),
        "misconceptions": misconceptions,
        "question_insights": sorted(question_insights, key=lambda x: x["fail_rate"], reverse=True),
        "ai_analysis": ai_analysis or []
    }


# ============== TOPIC MASTERY ==============

@router.get("/analytics/topic-mastery")
async def get_topic_mastery(
    exam_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    user: User = Depends(get_current_user)
):
    """Get topic-based mastery heatmap data"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Teacher only")

    exam_query = {"teacher_id": user.user_id}
    if exam_id:
        exam_query["exam_id"] = exam_id
    if batch_id:
        exam_query["batch_id"] = batch_id

    exams = await db.exams.find(exam_query, {"_id": 0}).to_list(50)
    if not exams:
        return {"topics": [], "students_by_topic": {}, "questions_by_topic": {}}

    exam_ids = [e["exam_id"] for e in exams]

    submissions = await db.submissions.find(
        {"exam_id": {"$in": exam_ids}},
        {"_id": 0, "student_id": 1, "student_name": 1, "exam_id": 1, "question_scores": 1}
    ).to_list(500)

    topic_data = {}
    questions_by_topic = {}

    for exam in exams:
        for question in exam.get("questions", []):
            q_num = question.get("question_number", 0)
            rubric = question.get("rubric", "")

            topics = question.get("topic_tags", [])

            if not topics:
                subject = None
                if exam.get("subject_id"):
                    subject_doc = await db.subjects.find_one({"subject_id": exam["subject_id"]}, {"_id": 0, "name": 1})
                    subject = subject_doc.get("name") if subject_doc else None
                extracted_topic = extract_topic_from_rubric(rubric, subject or "General")
                topics = [extracted_topic]

            for topic in topics:
                if topic not in topic_data:
                    topic_data[topic] = {"scores": [], "max_marks": 0, "students": {}, "questions": []}
                    questions_by_topic[topic] = []

                q_info = {
                    "exam_id": exam["exam_id"],
                    "exam_name": exam.get("exam_name", "Unknown"),
                    "question_number": q_num,
                    "rubric": rubric[:100] if rubric else f"Question {q_num}",
                    "max_marks": question.get("max_marks", 0)
                }
                if q_info not in topic_data[topic]["questions"]:
                    topic_data[topic]["questions"].append(q_info)

                for sub in submissions:
                    if sub["exam_id"] != exam["exam_id"]:
                        continue
                    for qs in sub.get("question_scores", []):
                        if qs.get("question_number") == q_num:
                            pct = (qs["obtained_marks"] / qs["max_marks"]) * 100 if qs["max_marks"] > 0 else 0
                            topic_data[topic]["scores"].append(pct)
                            topic_data[topic]["max_marks"] = max(topic_data[topic]["max_marks"], qs["max_marks"])

                            student_id = sub["student_id"]
                            student_name = sub["student_name"]
                            if student_id not in topic_data[topic]["students"]:
                                topic_data[topic]["students"][student_id] = {"name": student_name, "scores": []}
                            topic_data[topic]["students"][student_id]["scores"].append(pct)

    topics = []
    students_by_topic = {}

    for topic, data in topic_data.items():
        if not data["scores"]:
            continue

        avg = sum(data["scores"]) / len(data["scores"])

        if avg >= 70:
            level = "mastered"
            color = "green"
        elif avg >= 50:
            level = "developing"
            color = "amber"
        else:
            level = "critical"
            color = "red"

        struggling_students = []
        for student_id, student_data in data["students"].items():
            student_avg = sum(student_data["scores"]) / len(student_data["scores"])
            if student_avg < 50:
                struggling_students.append({
                    "student_id": student_id,
                    "name": student_data["name"],
                    "avg_score": round(student_avg, 1)
                })

        topics.append({
            "topic": topic,
            "avg_percentage": round(avg, 1),
            "level": level,
            "color": color,
            "sample_count": len(data["scores"]),
            "struggling_count": len(struggling_students),
            "question_count": len(data["questions"])
        })

        students_by_topic[topic] = sorted(struggling_students, key=lambda x: x["avg_score"])[:10]
        questions_by_topic[topic] = data["questions"]

    return {
        "topics": sorted(topics, key=lambda x: x["avg_percentage"]),
        "students_by_topic": students_by_topic,
        "questions_by_topic": questions_by_topic
    }


# ============== STUDENT DEEP DIVE ==============

@router.get("/analytics/student-deep-dive/{student_id}")
async def get_student_deep_dive(
    student_id: str,
    exam_id: Optional[str] = None,
    user: User = Depends(get_current_user)
):
    """Get detailed student analysis with AI-generated insights"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Teacher only")

    student = await db.users.find_one({"user_id": student_id}, {"_id": 0})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    sub_query = {"student_id": student_id}
    if exam_id:
        sub_query["exam_id"] = exam_id

    submissions = await db.submissions.find(sub_query, {"_id": 0}).to_list(20)

    if not submissions:
        return {
            "student": {"name": student.get("name", "Unknown"), "email": student.get("email", "")},
            "worst_questions": [],
            "performance_trend": [],
            "ai_analysis": None
        }

    all_question_scores = []
    for sub in submissions:
        exam = await db.exams.find_one({"exam_id": sub["exam_id"]}, {"_id": 0, "exam_name": 1, "model_answer_images": 1})
        for qs in sub.get("question_scores", []):
            pct = (qs["obtained_marks"] / qs["max_marks"]) * 100 if qs["max_marks"] > 0 else 0
            all_question_scores.append({
                "exam_name": exam.get("exam_name", "Unknown") if exam else "Unknown",
                "exam_id": sub["exam_id"],
                "submission_id": sub["submission_id"],
                "question_number": qs["question_number"],
                "question_text": qs.get("question_text", ""),
                "obtained_marks": qs["obtained_marks"],
                "max_marks": qs["max_marks"],
                "percentage": round(pct, 1),
                "ai_feedback": qs.get("ai_feedback", ""),
                "has_model_answer": bool(exam.get("model_answer_images") if exam else False)
            })

    worst_questions = sorted(all_question_scores, key=lambda x: x["percentage"])[:5]

    performance_trend = []
    for sub in sorted(submissions, key=lambda x: x.get("created_at", "")):
        exam = await db.exams.find_one({"exam_id": sub["exam_id"]}, {"_id": 0, "exam_name": 1})
        performance_trend.append({
            "exam_name": exam.get("exam_name", "Unknown") if exam else "Unknown",
            "percentage": sub["percentage"],
            "date": sub.get("created_at", "")
        })

    ai_analysis = None
    if worst_questions:
        try:
            llm_key = get_llm_api_key()

            analysis_prompt = f"""Analyze this student's performance and provide specific improvement guidance:

Student: {student.get('name', 'Unknown')}
Overall Average: {sum(s['percentage'] for s in submissions)/len(submissions):.1f}%

Worst Performing Questions:
{[{
    'exam': q['exam_name'],
    'question': q['question_number'],
    'score': f"{q['obtained_marks']}/{q['max_marks']} ({q['percentage']}%)",
    'feedback': q['ai_feedback'][:150]
} for q in worst_questions]}

Provide:
1. A brief summary of the student's main weaknesses
2. Specific study recommendations (2-3 points)
3. What concepts need review

Keep response concise (under 200 words). Format as JSON:
{{"summary": "...", "recommendations": ["...", "..."], "concepts_to_review": ["...", "..."]}}"""

            chat = LlmChat(
                api_key=llm_key,
                session_id=f"student_analysis_{uuid.uuid4().hex[:8]}",
                system_message="You are an expert educational analyst providing personalized student guidance."
            ).with_model("gemini", "gemini-2.5-flash").with_params(temperature=0)

            user_message = UserMessage(text=analysis_prompt)
            ai_response = await chat.send_message(user_message)

            try:
                cleaned = ai_response.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.split("```")[1]
                    if cleaned.startswith("json"):
                        cleaned = cleaned[4:]
                ai_analysis = json.loads(cleaned)
            except (json.JSONDecodeError, IndexError, ValueError):
                ai_analysis = {"summary": ai_response[:300]}
        except Exception as e:
            logger.error(f"AI student analysis error: {e}")

    return {
        "student": {
            "name": student.get("name", "Unknown"),
            "email": student.get("email", ""),
            "student_id": student_id
        },
        "overall_average": round(sum(s["percentage"] for s in submissions)/len(submissions), 1) if submissions else 0,
        "total_exams": len(submissions),
        "worst_questions": worst_questions,
        "performance_trend": performance_trend,
        "ai_analysis": ai_analysis
    }


# ============== GENERATE REVIEW PACKET ==============

@router.post("/analytics/generate-review-packet")
async def generate_review_packet(
    exam_id: str,
    user: User = Depends(get_current_user)
):
    """Generate AI-powered practice questions based on weak topics"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Teacher only")

    exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    submissions = await db.submissions.find(
        {"exam_id": exam_id},
        {"_id": 0, "question_scores": 1}
    ).to_list(100)

    if not submissions:
        raise HTTPException(status_code=400, detail="No submissions found for this exam")

    question_performance = {}
    for sub in submissions:
        for qs in sub.get("question_scores", []):
            q_num = qs["question_number"]
            if q_num not in question_performance:
                question_performance[q_num] = {"scores": [], "max": qs["max_marks"], "text": qs.get("question_text", "")}
            pct = (qs["obtained_marks"] / qs["max_marks"]) * 100 if qs["max_marks"] > 0 else 0
            question_performance[q_num]["scores"].append(pct)

    weak_questions = []
    for q_num, data in question_performance.items():
        avg = sum(data["scores"]) / len(data["scores"])
        if avg < 60:
            weak_questions.append({
                "question_number": q_num,
                "avg_percentage": round(avg, 1),
                "question_text": data["text"],
                "max_marks": data["max"]
            })

    if not weak_questions:
        return {"message": "No weak areas identified - all questions have good performance!", "practice_questions": []}

    try:
        llm_key = get_llm_api_key()

        subject = await db.subjects.find_one({"subject_id": exam.get("subject_id")}, {"_id": 0, "name": 1})
        subject_name = subject.get("name", "General") if subject else "General"

        generation_prompt = f"""Generate 5 practice questions for students based on these weak areas from a {subject_name} exam:

Exam: {exam.get('exam_name', 'Unknown')}
Weak Questions:
{[{
    'question': q['question_number'],
    'topic': q['question_text'][:100] if q['question_text'] else f"Question {q['question_number']}",
    'avg_score': f"{q['avg_percentage']}%",
    'max_marks': q['max_marks']
} for q in weak_questions[:5]]}

Generate 5 practice questions that:
1. Target the same concepts as the weak questions
2. Have varying difficulty levels
3. Include a mix of question types
4. Help students understand the underlying concepts

Return as JSON array:
[{{"question_number": 1, "question": "question text", "marks": 5, "topic": "topic being tested", "difficulty": "easy/medium/hard", "hint": "optional hint for students"}}]

Only return the JSON array."""

        chat = LlmChat(
            api_key=llm_key,
            session_id=f"review_packet_{uuid.uuid4().hex[:8]}",
            system_message="You are an expert educator creating practice questions to help students improve."
        ).with_model("gemini", "gemini-2.5-flash").with_params(temperature=0)

        user_message = UserMessage(text=generation_prompt)
        ai_response = await chat.send_message(user_message)

        try:
            cleaned = ai_response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
            practice_questions = json.loads(cleaned)
        except (json.JSONDecodeError, IndexError, ValueError):
            practice_questions = []

        return {
            "exam_name": exam.get("exam_name"),
            "subject": subject_name,
            "weak_areas_identified": len(weak_questions),
            "practice_questions": practice_questions,
            "generated_at": datetime.now(timezone.utc).isoformat()
        }

    except Exception as e:
        logger.error(f"Error generating review packet: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate practice questions")


# ============== BLUFF INDEX ==============

@router.get("/analytics/bluff-index/{exam_id}")
async def get_bluff_index(
    exam_id: str,
    user: User = Depends(get_current_user)
):
    """Detect students who write long but irrelevant answers"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Teacher only")

    exam = await db.exams.find_one(
        {"exam_id": exam_id, "teacher_id": user.user_id},
        {"_id": 0}
    )
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    submissions = await db.submissions.find(
        {"exam_id": exam_id},
        {"_id": 0, "student_id": 1, "student_name": 1, "question_scores": 1}
    ).to_list(1000)

    logger.info(f"Analyzing bluff index for {len(submissions)} submissions")

    bluff_candidates = []

    for submission in submissions:
        student_bluff_score = 0
        suspicious_answers = []

        for qs in submission.get("question_scores", []):
            answer_text = qs.get("answer_text", "")
            feedback = qs.get("ai_feedback", "")
            obtained = qs.get("obtained_marks", 0)
            max_marks = qs.get("max_marks", 1)
            percentage = (obtained / max_marks) * 100 if max_marks > 0 else 0

            if len(answer_text) > 100 and percentage < 40:
                if any(keyword in feedback.lower() for keyword in [
                    "irrelevant", "off-topic", "does not answer", "incorrect approach",
                    "vague", "unclear", "lacks understanding", "superficial"
                ]):
                    student_bluff_score += 1
                    suspicious_answers.append({
                        "question_number": qs.get("question_number"),
                        "answer_length": len(answer_text),
                        "score_percentage": round(percentage, 1),
                        "feedback_snippet": feedback[:150]
                    })

        if student_bluff_score >= 2:
            bluff_candidates.append({
                "student_id": submission["student_id"],
                "student_name": submission["student_name"],
                "bluff_score": student_bluff_score,
                "suspicious_answers": suspicious_answers
            })

    bluff_candidates.sort(key=lambda x: x["bluff_score"], reverse=True)

    return {
        "exam_id": exam_id,
        "exam_name": exam.get("exam_name", "Unknown"),
        "total_students": len(submissions),
        "bluff_candidates": bluff_candidates,
        "summary": f"Found {len(bluff_candidates)} students with potential bluffing patterns (long answers with low relevance)"
    }


# ============== SYLLABUS COVERAGE ==============

@router.get("/analytics/syllabus-coverage")
async def get_syllabus_coverage(
    batch_id: Optional[str] = None,
    subject_id: Optional[str] = None,
    user: User = Depends(get_current_user)
):
    """Syllabus Coverage Heatmap: Shows which topics have been tested and results"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Teacher only")

    exam_query = {"teacher_id": user.user_id}
    if batch_id:
        exam_query["batch_id"] = batch_id
    if subject_id:
        exam_query["subject_id"] = subject_id

    exams = await db.exams.find(exam_query, {"_id": 0}).to_list(100)

    if not exams:
        return {
            "tested_topics": [], "untested_topics": [],
            "coverage_percentage": 0, "topic_heatmap": []
        }

    subject = None
    if subject_id:
        subject = await db.subjects.find_one({"subject_id": subject_id}, {"_id": 0})

    tested_topics = {}

    for exam in exams:
        exam_id_val = exam["exam_id"]

        submissions = await db.submissions.find(
            {"exam_id": exam_id_val},
            {"_id": 0, "question_scores": 1}
        ).to_list(1000)

        for question in exam.get("questions", []):
            topics = question.get("topic_tags", [])
            if not topics:
                topics = [subject.get("name", "General")] if subject else ["General"]

            q_num = question.get("question_number")

            for topic in topics:
                if topic not in tested_topics:
                    tested_topics[topic] = {
                        "exam_count": 0, "question_count": 0,
                        "total_scores": [], "last_tested": None
                    }

                tested_topics[topic]["exam_count"] += 1
                tested_topics[topic]["question_count"] += 1
                tested_topics[topic]["last_tested"] = exam.get("created_at", "")

                for sub in submissions:
                    for qs in sub.get("question_scores", []):
                        if qs.get("question_number") == q_num:
                            percentage = (qs["obtained_marks"] / qs["max_marks"]) * 100 if qs.get("max_marks", 0) > 0 else 0
                            tested_topics[topic]["total_scores"].append(percentage)

    topic_heatmap = []
    for topic, data in tested_topics.items():
        avg_score = sum(data["total_scores"]) / len(data["total_scores"]) if data["total_scores"] else 0

        color = "grey"
        if avg_score > 0:
            if avg_score >= 70:
                color = "green"
            elif avg_score >= 50:
                color = "amber"
            else:
                color = "red"

        topic_heatmap.append({
            "topic": topic, "status": "tested",
            "exam_count": data["exam_count"], "question_count": data["question_count"],
            "avg_score": round(avg_score, 1), "last_tested": data["last_tested"],
            "color": color
        })

    coverage_percentage = 100

    return {
        "subject": subject.get("name") if subject else "All Subjects",
        "total_exams": len(exams),
        "tested_topics": sorted(topic_heatmap, key=lambda x: x["avg_score"]),
        "untested_topics": [],
        "coverage_percentage": coverage_percentage,
        "summary": f"Assessed {len(tested_topics)} topics across {len(exams)} exams"
    }


# ============== PEER GROUPS ==============

@router.get("/analytics/peer-groups")
async def get_peer_group_suggestions(
    batch_id: str,
    user: User = Depends(get_current_user)
):
    """Auto-suggest study pairs based on complementary strengths/weaknesses"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Teacher only")

    batch = await db.batches.find_one({"batch_id": batch_id}, {"_id": 0})
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    student_ids = batch.get("students", [])

    if len(student_ids) < 2:
        return {"suggestions": [], "summary": "Need at least 2 students to form peer groups"}

    student_profiles = {}

    for student_id in student_ids:
        student = await db.users.find_one({"user_id": student_id}, {"_id": 0, "name": 1})
        if not student:
            continue

        submissions = await db.submissions.find(
            {"student_id": student_id},
            {"_id": 0, "exam_id": 1, "question_scores": 1}
        ).to_list(1000)

        if not submissions:
            continue

        topic_performance = {}

        for sub in submissions:
            exam = await db.exams.find_one({"exam_id": sub["exam_id"]}, {"_id": 0, "questions": 1})
            if not exam:
                continue

            question_topics = {}
            for q in exam.get("questions", []):
                topics = q.get("topic_tags", ["General"])
                question_topics[q.get("question_number")] = topics

            for qs in sub.get("question_scores", []):
                q_num = qs.get("question_number")
                topics = question_topics.get(q_num, ["General"])
                percentage = (qs["obtained_marks"] / qs["max_marks"]) * 100 if qs.get("max_marks", 0) > 0 else 0

                for topic in topics:
                    if topic not in topic_performance:
                        topic_performance[topic] = []
                    topic_performance[topic].append(percentage)

        strengths = []
        weaknesses = []

        for topic, scores in topic_performance.items():
            avg = sum(scores) / len(scores)
            if avg >= 70:
                strengths.append(topic)
            elif avg < 50:
                weaknesses.append(topic)

        student_profiles[student_id] = {
            "name": student.get("name", "Unknown"),
            "strengths": strengths,
            "weaknesses": weaknesses
        }

    suggestions = []
    processed_pairs = set()

    for sid1, profile1 in student_profiles.items():
        for sid2, profile2 in student_profiles.items():
            if sid1 >= sid2:
                continue

            pair_key = tuple(sorted([sid1, sid2]))
            if pair_key in processed_pairs:
                continue

            complementary_topics = []

            for strength in profile1["strengths"]:
                if strength in profile2["weaknesses"]:
                    complementary_topics.append({
                        "topic": strength, "helper": profile1["name"], "learner": profile2["name"]
                    })

            for strength in profile2["strengths"]:
                if strength in profile1["weaknesses"]:
                    complementary_topics.append({
                        "topic": strength, "helper": profile2["name"], "learner": profile1["name"]
                    })

            if len(complementary_topics) >= 2:
                suggestions.append({
                    "student1": {"id": sid1, "name": profile1["name"], "strengths": profile1["strengths"], "weaknesses": profile1["weaknesses"]},
                    "student2": {"id": sid2, "name": profile2["name"], "strengths": profile2["strengths"], "weaknesses": profile2["weaknesses"]},
                    "complementary_topics": complementary_topics,
                    "synergy_score": len(complementary_topics)
                })
                processed_pairs.add(pair_key)

    suggestions.sort(key=lambda x: x["synergy_score"], reverse=True)

    return {
        "batch_id": batch_id,
        "batch_name": batch.get("name", "Unknown"),
        "total_students": len(student_profiles),
        "suggestions": suggestions[:10],
        "summary": f"Found {len(suggestions)} potential study pairs with complementary skills"
    }


@router.post("/analytics/send-peer-group-email")
async def send_peer_group_email(
    student1_id: str,
    student2_id: str,
    message: str,
    user: User = Depends(get_current_user)
):
    """Send notification to suggested peer group"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Teacher only")

    student1 = await db.users.find_one({"user_id": student1_id}, {"_id": 0, "email": 1, "name": 1})
    student2 = await db.users.find_one({"user_id": student2_id}, {"_id": 0, "email": 1, "name": 1})

    if not student1 or not student2:
        raise HTTPException(status_code=404, detail="Students not found")

    await create_notification(
        user_id=student1_id,
        notification_type="peer_group_suggestion",
        title="Study Partner Suggestion",
        message=f"Your teacher suggests studying with {student2.get('name')}. {message}"
    )

    await create_notification(
        user_id=student2_id,
        notification_type="peer_group_suggestion",
        title="Study Partner Suggestion",
        message=f"Your teacher suggests studying with {student1.get('name')}. {message}"
    )

    return {"success": True, "message": "Notifications sent to both students"}


# ============== NATURAL LANGUAGE QUERY (Ask Your Data) ==============

@router.post("/analytics/ask")
async def ask_your_data(
    request: NaturalLanguageQuery,
    user: User = Depends(get_current_user)
):
    """Natural Language Query: Ask questions in plain English and get visualizations"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Teacher only")

    logger.info(f"NL Query: '{request.query}' from user {user.user_id}")

    context_data = {}

    batches = await db.batches.find({"teacher_id": user.user_id}, {"_id": 0, "batch_id": 1, "name": 1}).to_list(100)
    context_data["batches"] = [{"id": b["batch_id"], "name": b["name"]} for b in batches]

    subjects = await db.subjects.find({"teacher_id": user.user_id}, {"_id": 0, "subject_id": 1, "name": 1}).to_list(100)
    context_data["subjects"] = [{"id": s["subject_id"], "name": s["name"]} for s in subjects]

    exam_query = {"teacher_id": user.user_id}
    if request.batch_id:
        exam_query["batch_id"] = request.batch_id
    if request.exam_id:
        exam_query["exam_id"] = request.exam_id
    if request.subject_id:
        exam_query["subject_id"] = request.subject_id

    exams = await db.exams.find(exam_query, {"_id": 0, "exam_id": 1, "exam_name": 1, "batch_id": 1, "subject_id": 1}).to_list(100)
    context_data["exams"] = [{"id": e["exam_id"], "name": e["exam_name"]} for e in exams]

    exam_ids = [e["exam_id"] for e in exams]
    if not exam_ids:
        return {"type": "error", "message": "No exams found. Please create and grade some exams first."}

    submissions = await db.submissions.find(
        {"exam_id": {"$in": exam_ids}},
        {"_id": 0, "submission_id": 1, "exam_id": 1, "student_id": 1, "student_name": 1, "total_score": 1, "percentage": 1, "question_scores": 1}
    ).to_list(1000)

    context_data["total_submissions"] = len(submissions)
    context_data["total_students"] = len(set(s["student_id"] for s in submissions))

    try:
        prompt = f"""
You are a data analyst for a teacher. Parse the natural language query and return a structured JSON response.

Teacher's Context:
- Batches: {', '.join([b['name'] for b in context_data['batches']])}
- Subjects: {', '.join([s['name'] for s in context_data['subjects']])}
- Total Students: {context_data['total_students']}
- Total Submissions: {context_data['total_submissions']}

Teacher's Query: "{request.query}"

Your task:
1. Understand the intent
2. Determine what data to show
3. Choose the best visualization type
4. Return ONLY valid JSON (no markdown, no explanations)

Available chart types: "bar", "table", "pie", "comparison"

Response Format (JSON only, no markdown):
{{
    "intent": "show_top_students | compare_groups | show_failures | show_distribution | other",
    "chart_type": "bar | table | pie | comparison",
    "data_query": {{
        "entity": "students | questions | topics",
        "filter": {{
            "subject": "Math" ,
            "question_number": 3,
            "performance": "failed | passed | top"
        }},
        "group_by": "batch | gender | topic",
        "limit": 5
    }},
    "chart_config": {{
        "title": "Top 5 Students in Math",
        "xAxis": "student_name",
        "yAxis": "score",
        "description": "Brief explanation of what this shows"
    }}
}}

If the query is unclear or impossible to answer, return:
{{
    "intent": "error",
    "chart_type": "error",
    "message": "Explanation of why this cannot be answered"
}}
"""

        chat = LlmChat(
            api_key=get_llm_api_key(),
            session_id=f"nl_query_{uuid.uuid4().hex[:8]}",
            system_message="You are a precise data analyst. Return ONLY valid JSON, no markdown formatting."
        ).with_model("gemini", "gemini-2.5-flash").with_params(temperature=0)

        user_message = UserMessage(text=prompt)
        response = await chat.send_message(user_message)
        response_text = response.strip()

        response_text = re.sub(r'^```json\s*', '', response_text)
        response_text = re.sub(r'\s*```$', '', response_text)

        query_intent = json.loads(response_text)

        if query_intent.get("intent") == "error":
            return {"type": "error", "message": query_intent.get("message", "Could not understand the query")}

    except Exception as e:
        logger.error(f"Error parsing NL query with AI: {e}")
        return {"type": "error", "message": f"Failed to parse query: {str(e)}"}

    try:
        data_query = query_intent.get("data_query", {})
        entity = data_query.get("entity", "students")
        filters = data_query.get("filter", {})
        limit = data_query.get("limit", 10)

        result_data = []

        if entity == "students":
            filtered_submissions = submissions

            if "subject" in filters:
                subject_name = filters["subject"]
                subject_doc = await db.subjects.find_one(
                    {"name": {"$regex": subject_name, "$options": "i"}, "teacher_id": user.user_id},
                    {"_id": 0, "subject_id": 1}
                )
                if subject_doc:
                    subject_exams = [e["exam_id"] for e in exams if e.get("subject_id") == subject_doc["subject_id"]]
                    filtered_submissions = [s for s in filtered_submissions if s["exam_id"] in subject_exams]

            if filters.get("performance") == "failed":
                filtered_submissions = [s for s in filtered_submissions if s["percentage"] < 50]
            elif filters.get("performance") == "passed":
                filtered_submissions = [s for s in filtered_submissions if s["percentage"] >= 50]
            elif filters.get("performance") == "top":
                filtered_submissions = sorted(filtered_submissions, key=lambda x: x["percentage"], reverse=True)[:limit]

            student_aggregates = {}
            for sub in filtered_submissions:
                sid = sub["student_id"]
                if sid not in student_aggregates:
                    student_aggregates[sid] = {"student_name": sub["student_name"], "total_score": 0, "count": 0, "percentages": []}
                student_aggregates[sid]["total_score"] += sub["total_score"]
                student_aggregates[sid]["count"] += 1
                student_aggregates[sid]["percentages"].append(sub["percentage"])

            for sid, data in student_aggregates.items():
                avg_percentage = sum(data["percentages"]) / len(data["percentages"]) if data["percentages"] else 0
                result_data.append({"student_name": data["student_name"], "avg_score": round(avg_percentage, 1), "exams_taken": data["count"]})

            result_data = sorted(result_data, key=lambda x: x["avg_score"], reverse=True)[:limit]

        elif entity == "questions":
            question_num = filters.get("question_number")

            if question_num:
                question_data = []
                for sub in submissions:
                    for qs in sub.get("question_scores", []):
                        if qs.get("question_number") == question_num:
                            percentage = (qs["obtained_marks"] / qs["max_marks"]) * 100 if qs.get("max_marks", 0) > 0 else 0
                            if filters.get("performance") == "failed" and percentage >= 50:
                                continue
                            question_data.append({
                                "student_name": sub["student_name"],
                                "score": qs["obtained_marks"],
                                "max_marks": qs["max_marks"],
                                "percentage": round(percentage, 1)
                            })
                result_data = sorted(question_data, key=lambda x: x["percentage"])[:limit]

        elif entity == "topics":
            topic_performance = {}

            for sub in submissions:
                exam = await db.exams.find_one({"exam_id": sub["exam_id"]}, {"_id": 0, "questions": 1})
                if not exam:
                    continue

                question_topics = {}
                for q in exam.get("questions", []):
                    topics = q.get("topic_tags", ["General"])
                    question_topics[q.get("question_number")] = topics

                for qs in sub.get("question_scores", []):
                    q_num = qs.get("question_number")
                    topics = question_topics.get(q_num, ["General"])
                    percentage = (qs["obtained_marks"] / qs["max_marks"]) * 100 if qs.get("max_marks", 0) > 0 else 0

                    for topic in topics:
                        if topic not in topic_performance:
                            topic_performance[topic] = []
                        topic_performance[topic].append(percentage)

            for topic, scores in topic_performance.items():
                avg = sum(scores) / len(scores) if scores else 0
                result_data.append({"topic": topic, "avg_score": round(avg, 1), "sample_size": len(scores)})

            result_data = sorted(result_data, key=lambda x: x["avg_score"], reverse=True)[:limit]

        chart_config = query_intent.get("chart_config", {})

        return {
            "type": query_intent.get("chart_type", "table"),
            "title": chart_config.get("title", "Query Results"),
            "description": chart_config.get("description", ""),
            "xAxis": chart_config.get("xAxis", "name"),
            "yAxis": chart_config.get("yAxis", "value"),
            "data": result_data,
            "query_intent": query_intent.get("intent", "unknown")
        }

    except Exception as e:
        logger.error(f"Error executing data query: {e}")
        return {"type": "error", "message": f"Failed to fetch data: {str(e)}"}


# ============== DASHBOARD SNAPSHOT & ACTIONABLE STATS ==============

@router.get("/dashboard/class-snapshot")
async def get_class_snapshot(
    batch_id: Optional[str] = None,
    user: User = Depends(get_current_user)
):
    """Get overall class performance snapshot for dashboard"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Teacher only")

    exam_query = {"teacher_id": user.user_id}
    if batch_id:
        exam_query["batch_id"] = batch_id

    exams = await db.exams.find(exam_query, {"_id": 0, "exam_id": 1, "exam_name": 1, "created_at": 1, "batch_id": 1}).to_list(100)

    if not exams:
        return {
            "batch_name": "No Batch Selected", "total_students": 0, "class_average": 0,
            "pass_rate": 0, "total_exams": 0, "recent_exam": None, "trend": 0,
            "top_performers": [], "struggling_students": []
        }

    exam_ids = [e["exam_id"] for e in exams]

    submissions = await db.submissions.find(
        {"exam_id": {"$in": exam_ids}},
        {"_id": 0, "student_id": 1, "student_name": 1, "percentage": 1, "created_at": 1, "exam_id": 1}
    ).to_list(10000)

    if not submissions:
        return {
            "batch_name": "No Data", "total_students": 0, "class_average": 0,
            "pass_rate": 0, "total_exams": len(exams),
            "recent_exam": exams[0].get("exam_name") if exams else None,
            "trend": 0, "top_performers": [], "struggling_students": []
        }

    total_students = len(set(s["student_id"] for s in submissions))
    class_average = sum(s["percentage"] for s in submissions) / len(submissions)
    pass_count = len([s for s in submissions if s["percentage"] >= 50])
    pass_rate = (pass_count / len(submissions)) * 100 if submissions else 0

    batch_name = "All Batches"
    if batch_id:
        batch = await db.batches.find_one({"batch_id": batch_id}, {"_id": 0, "name": 1})
        batch_name = batch.get("name") if batch else "Unknown Batch"

    recent_exam = max(exams, key=lambda x: x.get("created_at", ""))

    sorted_exams = sorted(exams, key=lambda x: x.get("created_at", ""), reverse=True)
    trend = 0

    if len(sorted_exams) >= 6:
        recent_exam_ids = [e["exam_id"] for e in sorted_exams[:3]]
        older_exam_ids = [e["exam_id"] for e in sorted_exams[3:6]]
        recent_subs = [s for s in submissions if s["exam_id"] in recent_exam_ids]
        older_subs = [s for s in submissions if s["exam_id"] in older_exam_ids]
        if recent_subs and older_subs:
            recent_avg = sum(s["percentage"] for s in recent_subs) / len(recent_subs)
            older_avg = sum(s["percentage"] for s in older_subs) / len(older_subs)
            trend = round(recent_avg - older_avg, 1)

    student_averages = {}
    for sub in submissions:
        sid = sub["student_id"]
        if sid not in student_averages:
            student_averages[sid] = {"name": sub["student_name"], "scores": []}
        student_averages[sid]["scores"].append(sub["percentage"])

    student_stats = []
    for sid, data in student_averages.items():
        avg = sum(data["scores"]) / len(data["scores"])
        student_stats.append({"student_id": sid, "student_name": data["name"], "average": round(avg, 1)})

    student_stats.sort(key=lambda x: x["average"], reverse=True)

    top_performers = student_stats[:3]
    struggling_students = [s for s in student_stats if s["average"] < 50][:3]

    return {
        "batch_name": batch_name, "total_students": total_students,
        "class_average": round(class_average, 1), "pass_rate": round(pass_rate, 1),
        "total_exams": len(exams), "recent_exam": recent_exam.get("exam_name", "Unknown"),
        "recent_exam_date": recent_exam.get("created_at", ""), "trend": trend,
        "top_performers": top_performers, "struggling_students": struggling_students
    }


@router.get("/dashboard/actionable-stats")
async def get_actionable_stats(
    batch_id: Optional[str] = None,
    user: User = Depends(get_current_user)
):
    """Get actionable insights for dashboard heads-up display"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Teacher only")

    exam_query = {"teacher_id": user.user_id}
    if batch_id:
        exam_query["batch_id"] = batch_id

    exams = await db.exams.find(exam_query, {"_id": 0}).to_list(100)

    if not exams:
        return {
            "action_required": {"pending_reviews": 0, "quality_concerns": 0, "total": 0, "papers": []},
            "performance": {"current_avg": 0, "previous_avg": 0, "trend": 0, "trend_direction": "stable"},
            "at_risk": {"count": 0, "students": [], "threshold": 40},
            "hardest_concept": None
        }

    exam_ids = [e["exam_id"] for e in exams]

    submissions = await db.submissions.find(
        {"exam_id": {"$in": exam_ids}},
        {"_id": 0, "submission_id": 1, "exam_id": 1, "student_id": 1, "student_name": 1, "percentage": 1, "total_score": 1, "created_at": 1, "status": 1, "question_scores": 1}
    ).to_list(10000)

    pending_reviews = len([s for s in submissions if s.get("status") == "pending"])

    quality_concerns = []
    for sub in submissions:
        if sub.get("percentage", 0) < 50:
            for qs in sub.get("question_scores", []):
                answer_text = qs.get("answer_text", "")
                obtained = qs.get("obtained_marks", 0)
                max_marks = qs.get("max_marks", 1)
                percentage = (obtained / max_marks) * 100 if max_marks > 0 else 0
                if len(answer_text) > 100 and percentage < 30:
                    quality_concerns.append({
                        "submission_id": sub["submission_id"],
                        "student_name": sub["student_name"],
                        "exam_id": sub["exam_id"]
                    })
                    break
    quality_concerns = quality_concerns[:10]

    sorted_exams = sorted(exams, key=lambda x: x.get("created_at", ""), reverse=True)
    current_avg = 0
    previous_avg = 0
    trend = 0

    if len(sorted_exams) >= 2:
        recent_exam_ids = [e["exam_id"] for e in sorted_exams[:2]]
        recent_subs = [s for s in submissions if s["exam_id"] in recent_exam_ids]
        if len(sorted_exams) >= 4:
            prev_exam_ids = [e["exam_id"] for e in sorted_exams[2:4]]
            prev_subs = [s for s in submissions if s["exam_id"] in prev_exam_ids]
            if recent_subs and prev_subs:
                current_avg = sum(s["percentage"] for s in recent_subs) / len(recent_subs)
                previous_avg = sum(s["percentage"] for s in prev_subs) / len(prev_subs)
                trend = current_avg - previous_avg
    elif submissions:
        current_avg = sum(s["percentage"] for s in submissions) / len(submissions)

    trend_direction = "up" if trend > 2 else "down" if trend < -2 else "stable"

    at_risk_students = {}
    if len(sorted_exams) >= 2:
        recent_exam_ids = [e["exam_id"] for e in sorted_exams[:2]]
        recent_subs = [s for s in submissions if s["exam_id"] in recent_exam_ids]
        for sub in recent_subs:
            if sub["percentage"] < 40:
                sid = sub["student_id"]
                if sid not in at_risk_students:
                    at_risk_students[sid] = {"student_id": sid, "student_name": sub["student_name"], "avg_score": sub["percentage"], "exams_failed": 1}
                else:
                    at_risk_students[sid]["exams_failed"] += 1

    at_risk_list = list(at_risk_students.values())
    at_risk_list.sort(key=lambda x: x["avg_score"])

    question_performance = {}
    for sub in submissions:
        for qs in sub.get("question_scores", []):
            q_key = f"{sub['exam_id']}_{qs.get('question_number')}"
            if q_key not in question_performance:
                question_performance[q_key] = {"exam_id": sub["exam_id"], "question_number": qs.get("question_number"), "total_attempts": 0, "total_score": 0, "max_marks": qs.get("max_marks", 0)}
            question_performance[q_key]["total_attempts"] += 1
            question_performance[q_key]["total_score"] += qs.get("obtained_marks", 0)

    question_stats = []
    for q_key, data in question_performance.items():
        if data["total_attempts"] > 0:
            avg_obtained = data["total_score"] / data["total_attempts"]
            success_rate = (avg_obtained / data["max_marks"]) * 100 if data["max_marks"] > 0 else 0
            exam = await db.exams.find_one({"exam_id": data["exam_id"]}, {"_id": 0, "exam_name": 1, "questions": 1})
            if exam:
                for q in exam.get("questions", []):
                    if q.get("question_number") == data["question_number"]:
                        question_stats.append({
                            "exam_id": data["exam_id"], "exam_name": exam.get("exam_name", "Unknown"),
                            "question_number": data["question_number"],
                            "topic": q.get("rubric", "")[:50] + "..." if len(q.get("rubric", "")) > 50 else q.get("rubric", "Unknown"),
                            "success_rate": round(success_rate, 1), "attempts": data["total_attempts"]
                        })
                        break

    valid_questions = [q for q in question_stats if q["attempts"] >= 5]
    hardest = min(valid_questions, key=lambda x: x["success_rate"]) if valid_questions else None

    return {
        "action_required": {"pending_reviews": pending_reviews, "quality_concerns": len(quality_concerns), "total": pending_reviews + len(quality_concerns), "papers": quality_concerns[:5]},
        "performance": {"current_avg": round(current_avg, 1), "previous_avg": round(previous_avg, 1), "trend": round(trend, 1), "trend_direction": trend_direction},
        "at_risk": {"count": len(at_risk_list), "students": at_risk_list[:5], "threshold": 40},
        "hardest_concept": hardest
    }
