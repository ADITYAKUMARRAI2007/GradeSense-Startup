"""Student portal routes — student dashboard, topic drilldown, journey, ask-ai, study materials."""

import json
import re
import uuid
from typing import Optional, Dict, List
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.database import db
from app.config import logger, get_llm_api_key
from app.deps import get_current_user
from app.models.user import User
from app.services.analytics import extract_topic_from_rubric
from app.services.llm import LlmChat, UserMessage, ImageContent

router = APIRouter(tags=["student_portal"])


# ============== STUDENT DASHBOARD ==============

@router.get("/analytics/student-dashboard")
async def get_student_dashboard(user: User = Depends(get_current_user)):
    """Get student's personal dashboard analytics"""
    if user.role != "student":
        raise HTTPException(status_code=403, detail="Only students can access this")

    published_exams = await db.exams.find(
        {"results_published": True},
        {"_id": 0, "exam_id": 1}
    ).to_list(1000)
    published_exam_ids = [e["exam_id"] for e in published_exams]

    submissions = await db.submissions.find(
        {"student_id": user.user_id, "exam_id": {"$in": published_exam_ids}},
        {"_id": 0}
    ).to_list(100)

    if not submissions:
        return {
            "stats": {"total_exams": 0, "avg_percentage": 0, "rank": "N/A", "improvement": 0},
            "recent_results": [], "subject_performance": [],
            "recommendations": ["Complete your first exam to see analytics!"],
            "weak_areas": [], "strong_areas": [],
            "weak_topics": [], "strong_topics": []
        }

    percentages = [s.get("percentage", 0) for s in submissions]

    recent = sorted(submissions, key=lambda x: x.get("graded_at", x.get("created_at", "")), reverse=True)[:5]
    recent_results = []
    for r in recent:
        exam = await db.exams.find_one({"exam_id": r["exam_id"]}, {"_id": 0, "exam_name": 1, "subject_id": 1})
        subject = await db.subjects.find_one({"subject_id": exam.get("subject_id")}, {"_id": 0, "name": 1}) if exam else None
        recent_results.append({
            "exam_name": exam.get("exam_name", "Unknown") if exam else "Unknown",
            "subject": subject.get("name", "Unknown") if subject else "Unknown",
            "score": f"{r.get('obtained_marks', 0)}/{r.get('total_marks', 100)}",
            "percentage": r.get("percentage", 0),
            "date": r.get("graded_at", r.get("created_at", ""))
        })

    subject_perf = {}
    for sub in submissions:
        exam = await db.exams.find_one({"exam_id": sub["exam_id"]}, {"_id": 0, "subject_id": 1})
        if exam:
            subj = await db.subjects.find_one({"subject_id": exam.get("subject_id")}, {"_id": 0, "name": 1})
            subj_name = subj.get("name", "Unknown") if subj else "Unknown"
            if subj_name not in subject_perf:
                subject_perf[subj_name] = []
            subject_perf[subj_name].append(sub["percentage"])

    subject_performance = [
        {"subject": name, "average": round(sum(scores)/len(scores), 1), "exams": len(scores)}
        for name, scores in subject_perf.items()
    ]

    # ====== TOPIC-BASED PERFORMANCE ANALYSIS FOR STUDENTS ======
    topic_performance = {}

    for sub in submissions:
        exam = await db.exams.find_one({"exam_id": sub["exam_id"]}, {"_id": 0})
        if not exam:
            continue

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
                    "feedback": qs.get("ai_feedback", "")[:150]
                })

    weak_topics = []
    strong_topics = []

    for topic, performances in topic_performance.items():
        if len(performances) == 0:
            continue

        sorted_perfs = sorted(performances, key=lambda x: x.get("exam_date", ""))
        avg_score = sum(p["score"] for p in sorted_perfs) / len(sorted_perfs)

        trend = 0
        trend_text = "stable"
        if len(sorted_perfs) >= 2:
            mid = len(sorted_perfs) // 2
            first_half_avg = sum(p["score"] for p in sorted_perfs[:mid]) / mid if mid > 0 else 0
            second_half_avg = sum(p["score"] for p in sorted_perfs[mid:]) / (len(sorted_perfs) - mid)
            trend = second_half_avg - first_half_avg

            if trend > 10:
                trend_text = "improving"
            elif trend < -10:
                trend_text = "declining"

        topic_data = {
            "topic": topic,
            "avg_score": round(avg_score, 1),
            "total_attempts": len(sorted_perfs),
            "trend": round(trend, 1),
            "trend_text": trend_text,
            "recent_score": round(sorted_perfs[-1]["score"], 1) if sorted_perfs else 0,
            "feedback": sorted_perfs[-1].get("feedback", "") if sorted_perfs else ""
        }

        if avg_score < 50:
            weak_topics.append(topic_data)
        elif avg_score >= 75:
            strong_topics.append(topic_data)

    weak_topics = sorted(weak_topics, key=lambda x: x["avg_score"])[:5]
    strong_topics = sorted(strong_topics, key=lambda x: -x["avg_score"])[:5]

    recommendations = []

    declining_topics = [t for t in weak_topics if t["trend_text"] == "declining"]
    if declining_topics:
        recommendations.append(f"⚠️ Focus on {declining_topics[0]['topic']} - your performance is declining")

    improving_weak = [t for t in weak_topics if t["trend_text"] == "improving"]
    if improving_weak:
        recommendations.append(f"📈 Great improvement in {improving_weak[0]['topic']}! Keep practicing")

    stable_weak = [t for t in weak_topics if t["trend_text"] == "stable"]
    if stable_weak:
        recommendations.append(f"💡 Review concepts in {stable_weak[0]['topic']} - needs more attention")

    if strong_topics:
        recommendations.append(f"⭐ You're excelling in {strong_topics[0]['topic']}! Consider helping classmates")

    if not recommendations:
        recommendations = [
            "Complete more exams to get personalized insights",
            "Review feedback on each question to improve",
            "Practice regularly across all topics"
        ]

    avg_percentage = sum(percentages) / len(percentages) if percentages else 0

    if len(percentages) >= 2:
        recent_avg = sum(percentages[-3:]) / min(3, len(percentages))
        older_avg = sum(percentages[:-3]) / max(1, len(percentages) - 3) if len(percentages) > 3 else recent_avg
        improvement = round(recent_avg - older_avg, 1)
    else:
        improvement = 0

    return {
        "stats": {
            "total_exams": len(submissions),
            "avg_percentage": round(avg_percentage, 1),
            "rank": "Top 10",
            "improvement": improvement
        },
        "recent_results": recent_results,
        "subject_performance": subject_performance,
        "recommendations": recommendations,
        "weak_topics": weak_topics,
        "strong_topics": strong_topics,
        "weak_areas": [{"question": t["topic"], "score": f"{t['avg_score']}%", "feedback": t.get("feedback", "")} for t in weak_topics],
        "strong_areas": [{"question": t["topic"], "score": f"{t['avg_score']}%"} for t in strong_topics]
    }


# ============== DRILL-DOWN ANALYTICS ==============

@router.get("/analytics/drill-down/topic/{topic_name}")
async def get_topic_drilldown(
    topic_name: str,
    exam_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    user: User = Depends(get_current_user)
):
    """Level 2 Drill-Down: Get detailed breakdown of a topic into sub-skills"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Teacher only")

    exam_query = {"teacher_id": user.user_id}
    if exam_id:
        exam_query["exam_id"] = exam_id
    if batch_id:
        exam_query["batch_id"] = batch_id

    exams = await db.exams.find(exam_query, {"_id": 0}).to_list(50)
    if not exams:
        return {"sub_skills": [], "questions": [], "students": []}

    exam_ids = [e["exam_id"] for e in exams]

    questions_in_topic = []
    for exam in exams:
        for question in exam.get("questions", []):
            topics = question.get("topic_tags", [])
            if not topics:
                subject = None
                if exam.get("subject_id"):
                    subject_doc = await db.subjects.find_one({"subject_id": exam["subject_id"]}, {"_id": 0, "name": 1})
                    subject = subject_doc.get("name") if subject_doc else None
                topics = [subject or "General"]

            if topic_name in topics:
                questions_in_topic.append({
                    "exam_id": exam["exam_id"],
                    "exam_name": exam.get("exam_name", "Unknown"),
                    "question_number": question.get("question_number"),
                    "rubric": question.get("rubric", ""),
                    "max_marks": question.get("max_marks", 0),
                    "sub_questions": question.get("sub_questions", [])
                })

    submissions = await db.submissions.find(
        {"exam_id": {"$in": exam_ids}},
        {"_id": 0, "student_id": 1, "student_name": 1, "exam_id": 1, "question_scores": 1}
    ).to_list(500)

    sub_skill_performance = {}
    question_performance = {}

    for q in questions_in_topic:
        q_key = f"{q['exam_id']}_{q['question_number']}"
        question_performance[q_key] = {
            "exam_name": q["exam_name"], "question_number": q["question_number"],
            "rubric": q["rubric"], "max_marks": q["max_marks"],
            "scores": [], "avg_percentage": 0
        }

        rubric_lower = q["rubric"].lower()
        sub_skill = "Concept Understanding"
        if any(word in rubric_lower for word in ["calculate", "compute", "find the value"]):
            sub_skill = "Calculation"
        elif any(word in rubric_lower for word in ["prove", "derive", "show that"]):
            sub_skill = "Proof & Derivation"
        elif any(word in rubric_lower for word in ["apply", "solve", "use"]):
            sub_skill = "Application"
        elif any(word in rubric_lower for word in ["explain", "describe", "define"]):
            sub_skill = "Concept Understanding"

        if sub_skill not in sub_skill_performance:
            sub_skill_performance[sub_skill] = {"scores": [], "question_count": 0}
        sub_skill_performance[sub_skill]["question_count"] += 1

    for submission in submissions:
        for qs in submission.get("question_scores", []):
            q_key = f"{submission['exam_id']}_{qs.get('question_number')}"
            if q_key in question_performance:
                percentage = (qs["obtained_marks"] / qs["max_marks"]) * 100 if qs.get("max_marks", 0) > 0 else 0
                question_performance[q_key]["scores"].append({
                    "student_id": submission["student_id"],
                    "student_name": submission["student_name"],
                    "obtained": qs["obtained_marks"],
                    "max": qs["max_marks"],
                    "percentage": percentage,
                    "feedback": qs.get("ai_feedback", "")
                })

    for q_key, q_data in question_performance.items():
        if q_data["scores"]:
            q_data["avg_percentage"] = round(sum(s["percentage"] for s in q_data["scores"]) / len(q_data["scores"]), 1)

    for q in questions_in_topic:
        q_key = f"{q['exam_id']}_{q['question_number']}"
        if q_key in question_performance:
            rubric_lower = q["rubric"].lower()
            sub_skill = "Concept Understanding"
            if any(word in rubric_lower for word in ["calculate", "compute", "find the value"]):
                sub_skill = "Calculation"
            elif any(word in rubric_lower for word in ["prove", "derive", "show that"]):
                sub_skill = "Proof & Derivation"
            elif any(word in rubric_lower for word in ["apply", "solve", "use"]):
                sub_skill = "Application"
            elif any(word in rubric_lower for word in ["explain", "describe", "define"]):
                sub_skill = "Concept Understanding"

            for score in question_performance[q_key]["scores"]:
                sub_skill_performance[sub_skill]["scores"].append(score["percentage"])

    sub_skills = []
    for skill, data in sub_skill_performance.items():
        if data["scores"]:
            avg = round(sum(data["scores"]) / len(data["scores"]), 1)
            sub_skills.append({
                "name": skill, "avg_percentage": avg,
                "question_count": data["question_count"],
                "color": "green" if avg >= 70 else "amber" if avg >= 50 else "red"
            })

    student_performance = {}
    for q_key, q_data in question_performance.items():
        for score in q_data["scores"]:
            sid = score["student_id"]
            if sid not in student_performance:
                student_performance[sid] = {"student_id": sid, "student_name": score["student_name"], "scores": []}
            student_performance[sid]["scores"].append(score["percentage"])

    struggling_students = []
    for sid, data in student_performance.items():
        avg = sum(data["scores"]) / len(data["scores"]) if data["scores"] else 0
        if avg < 60:
            struggling_students.append({
                "student_id": data["student_id"], "student_name": data["student_name"],
                "avg_percentage": round(avg, 1), "attempts": len(data["scores"])
            })

    insight = f"Analysis shows {len(struggling_students)} students need attention in {topic_name}. "
    if sub_skills:
        weakest = min(sub_skills, key=lambda x: x["avg_percentage"])
        insight += f"Weakest sub-skill: {weakest['name']} ({weakest['avg_percentage']}%)."

    return {
        "topic": topic_name, "insight": insight,
        "sub_skills": sorted(sub_skills, key=lambda x: x["avg_percentage"]),
        "questions": [q for q in question_performance.values()],
        "struggling_students": struggling_students
    }


# ============== QUESTION DRILLDOWN ==============

@router.get("/analytics/drill-down/question")
async def get_question_drilldown(
    exam_id: str,
    question_number: int,
    user: User = Depends(get_current_user)
):
    """Level 3 Drill-Down: Get error patterns for a specific question"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Teacher only")

    exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    question = None
    for q in exam.get("questions", []):
        if q.get("question_number") == question_number:
            question = q
            break

    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    submissions = await db.submissions.find(
        {"exam_id": exam_id},
        {"_id": 0, "student_id": 1, "student_name": 1, "question_scores": 1, "file_images": 1}
    ).to_list(1000)

    student_answers = []
    for submission in submissions:
        for qs in submission.get("question_scores", []):
            if qs.get("question_number") == question_number:
                student_answers.append({
                    "student_id": submission["student_id"],
                    "student_name": submission["student_name"],
                    "obtained_marks": qs["obtained_marks"],
                    "max_marks": qs["max_marks"],
                    "percentage": (qs["obtained_marks"] / qs["max_marks"]) * 100 if qs.get("max_marks", 0) > 0 else 0,
                    "feedback": qs.get("ai_feedback", ""),
                    "answer_text": qs.get("answer_text", ""),
                    "sub_scores": qs.get("sub_scores", [])
                })

    logger.info(f"Analyzing error patterns for Question {question_number} with {len(student_answers)} answers")

    failed_answers = [a for a in student_answers if a["percentage"] < 50]
    passed_answers = [a for a in student_answers if a["percentage"] >= 50]
    blank_answers = [a for a in student_answers if a["obtained_marks"] == 0]

    error_groups = {}

    if failed_answers:
        try:
            feedback_samples = [f"Student {a['student_name']}: {a['feedback'][:200]}" for a in failed_answers[:10]]

            prompt = f"""
Analyze these student errors for Question {question_number}:

Question: {question.get('rubric', '')}
Max Marks: {question.get('max_marks', 0)}

Failed Student Feedbacks:
{chr(10).join(feedback_samples)}

Task: Identify 3-4 common error patterns/categories. For each category, provide:
1. Error type name (e.g., "Calculation Error", "Conceptual Misunderstanding", "Incomplete Answer")
2. Brief description
3. Which students fall into this category (by name)

Respond in JSON format:
{{
    "error_categories": [
        {{
            "type": "Calculation Error",
            "description": "Made arithmetic mistakes",
            "student_names": ["Alice", "Bob"]
        }}
    ]
}}
"""

            chat = LlmChat(
                api_key=get_llm_api_key(),
                session_id=f"error_group_{uuid.uuid4().hex[:8]}",
                system_message="You are an educational data analyst. Categorize student errors precisely."
            ).with_model("gemini", "gemini-2.5-flash").with_params(temperature=0)

            user_message = UserMessage(text=prompt)
            response = await chat.send_message(user_message)

            response_text = response.strip()
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)

            if json_match:
                error_analysis = json.loads(json_match.group())

                for category in error_analysis.get("error_categories", []):
                    error_type = category["type"]
                    error_groups[error_type] = {"description": category["description"], "students": []}

                    for answer in failed_answers:
                        if answer["student_name"] in category.get("student_names", []):
                            error_groups[error_type]["students"].append({
                                "student_id": answer["student_id"],
                                "student_name": answer["student_name"],
                                "score": answer["obtained_marks"],
                                "feedback": answer["feedback"]
                            })

        except Exception as e:
            logger.error(f"Error in AI error grouping: {e}")
            error_groups = {
                "Low Scorers": {
                    "description": "Students who scored below 50%",
                    "students": [{"student_id": a["student_id"], "student_name": a["student_name"], "score": a["obtained_marks"], "feedback": a["feedback"]} for a in failed_answers]
                }
            }

    if blank_answers:
        error_groups["Not Attempted / Blank"] = {
            "description": "Students who left the question blank or scored 0",
            "students": [{"student_id": a["student_id"], "student_name": a["student_name"], "score": 0, "feedback": "No answer provided"} for a in blank_answers]
        }

    total_students = len(student_answers)
    avg_score = sum(a["percentage"] for a in student_answers) / total_students if total_students > 0 else 0
    pass_count = len([a for a in student_answers if a["percentage"] >= 50])

    return {
        "question": {"number": question_number, "rubric": question.get("rubric", ""), "max_marks": question.get("max_marks", 0)},
        "statistics": {
            "total_students": total_students, "avg_percentage": round(avg_score, 1),
            "pass_count": pass_count, "fail_count": total_students - pass_count,
            "blank_count": len(blank_answers)
        },
        "error_groups": [
            {"type": error_type, "description": data["description"], "count": len(data["students"]), "students": data["students"]}
            for error_type, data in error_groups.items()
        ],
        "top_performers": sorted(
            [{"student_name": a["student_name"], "score": a["obtained_marks"], "max_marks": a["max_marks"]} for a in passed_answers],
            key=lambda x: x["score"], reverse=True
        )[:5]
    }


# ============== STUDENT JOURNEY ==============

@router.get("/analytics/student-journey/{student_id}")
async def get_student_journey(
    student_id: str,
    user: User = Depends(get_current_user)
):
    """Student Journey View: Complete academic health record with comparisons"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Teacher only")

    student = await db.users.find_one({"user_id": student_id}, {"_id": 0})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    submissions = await db.submissions.find({"student_id": student_id}, {"_id": 0}).to_list(1000)

    if not submissions:
        return {"student": student, "performance_trend": [], "vs_class_avg": [], "blind_spots": [], "strengths": []}

    submissions.sort(key=lambda x: x.get("created_at", ""))

    performance_trend = []
    for sub in submissions:
        exam = await db.exams.find_one({"exam_id": sub["exam_id"]}, {"_id": 0, "exam_name": 1})
        performance_trend.append({
            "exam_name": exam.get("exam_name", "Unknown") if exam else "Unknown",
            "date": sub.get("created_at", ""),
            "percentage": sub["percentage"],
            "score": sub["total_score"]
        })

    exam_ids = [s["exam_id"] for s in submissions]
    class_averages = {}

    for eid in exam_ids:
        all_submissions = await db.submissions.find({"exam_id": eid}, {"_id": 0, "percentage": 1}).to_list(1000)
        if all_submissions:
            avg = sum(s["percentage"] for s in all_submissions) / len(all_submissions)
            class_averages[eid] = round(avg, 1)

    vs_class_avg = []
    for sub in submissions:
        exam = await db.exams.find_one({"exam_id": sub["exam_id"]}, {"_id": 0, "exam_name": 1})
        vs_class_avg.append({
            "exam_name": exam.get("exam_name", "Unknown") if exam else "Unknown",
            "student_score": sub["percentage"],
            "class_avg": class_averages.get(sub["exam_id"], 0),
            "difference": round(sub["percentage"] - class_averages.get(sub["exam_id"], 0), 1)
        })

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

    blind_spots = []
    strengths = []

    for topic, scores in topic_performance.items():
        avg = sum(scores) / len(scores)
        data = {"topic": topic, "avg_score": round(avg, 1), "attempts": len(scores)}
        if avg < 50:
            blind_spots.append(data)
        elif avg >= 70:
            strengths.append(data)

    return {
        "student": {
            "name": student.get("name", "Unknown"),
            "email": student.get("email", ""),
            "student_id": student.get("student_id", "")
        },
        "overall_stats": {
            "total_exams": len(submissions),
            "avg_percentage": round(sum(s["percentage"] for s in submissions) / len(submissions), 1),
            "highest": max(s["percentage"] for s in submissions),
            "lowest": min(s["percentage"] for s in submissions)
        },
        "performance_trend": performance_trend,
        "vs_class_avg": vs_class_avg,
        "blind_spots": sorted(blind_spots, key=lambda x: x["avg_score"]),
        "strengths": sorted(strengths, key=lambda x: x["avg_score"], reverse=True)
    }


# ============== COMPREHENSIVE AI ANALYTICS ==============

@router.post("/analytics/ask-ai")
async def ask_ai_comprehensive(
    request: dict,
    user: User = Depends(get_current_user)
):
    """Comprehensive AI Analytics Assistant"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Teacher only")

    query = request.get("query", "").strip()
    exam_id = request.get("exam_id")
    batch_id = request.get("batch_id")

    if not query:
        raise HTTPException(status_code=400, detail="Query is required")

    logger.info(f"AI Analytics Query from {user.email}: {query}")

    try:
        exam_query = {"teacher_id": user.user_id}
        if exam_id:
            exam_query["exam_id"] = exam_id
        if batch_id:
            exam_query["batch_id"] = batch_id

        exams = await db.exams.find(exam_query, {"_id": 0}).to_list(100)
        exam_ids = [e["exam_id"] for e in exams]

        if not exam_ids:
            return {"type": "text", "response": "No exams found matching your criteria. Please create an exam first."}

        submissions = await db.submissions.find(
            {"exam_id": {"$in": exam_ids}},
            {"_id": 0}
        ).to_list(1000)

        students = await db.users.find(
            {"teacher_id": user.user_id, "role": "student"},
            {"_id": 0, "user_id": 1, "name": 1}
        ).to_list(1000)

        data_summary = f"""
Data available:
- {len(exams)} exams
- {len(submissions)} submissions
- {len(students)} students
- Exam names: {', '.join([e.get('exam_name', 'Unknown') for e in exams[:5]])}
"""

        prompt = f"""You are an AI analytics assistant for a teacher. Answer this question based on the data:

{data_summary}

Question: {query}

Provide a clear, concise answer. If you need specific data that isn't available, say so."""

        chat = LlmChat(
            api_key=get_llm_api_key(),
            session_id=f"ask_ai_{uuid.uuid4().hex[:8]}",
            system_message="You are a helpful educational analytics assistant."
        ).with_model("gemini", "gemini-2.5-flash").with_params(temperature=0)

        user_message = UserMessage(text=prompt)
        ai_response = await chat.send_message(user_message)

        return {"type": "text", "response": ai_response}

    except Exception as e:
        logger.error(f"AI analytics error: {e}")
        return {"type": "error", "response": f"Failed to process query: {str(e)}"}


# ============== STUDY MATERIALS ==============

@router.get("/study-materials")
async def get_study_materials(subject_id: Optional[str] = None, user: User = Depends(get_current_user)):
    """Get study material recommendations based on weak areas"""
    submissions = await db.submissions.find(
        {"student_id": user.user_id},
        {"_id": 0, "question_scores": 1, "exam_id": 1}
    ).sort("created_at", -1).limit(5).to_list(5)

    weak_topics = []
    for sub in submissions:
        exam = await db.exams.find_one({"exam_id": sub["exam_id"]}, {"_id": 0, "subject_id": 1})
        subject = await db.subjects.find_one({"subject_id": exam.get("subject_id")}, {"_id": 0, "name": 1}) if exam else None
        subj_name = subject.get("name", "General") if subject else "General"

        for qs in sub.get("question_scores", []):
            pct = (qs["obtained_marks"] / qs["max_marks"]) * 100 if qs["max_marks"] > 0 else 0
            if pct < 50:
                weak_topics.append({
                    "subject": subj_name,
                    "question": f"Q{qs['question_number']}",
                    "score": f"{pct:.0f}%"
                })

    materials = [
        {"title": "Practice Problems", "description": "Work through similar problems to strengthen weak areas", "type": "practice"},
        {"title": "Concept Review", "description": "Review fundamental concepts related to questions you struggled with", "type": "theory"},
        {"title": "Video Tutorials", "description": "Watch explanatory videos for complex topics", "type": "video"}
    ]

    return {"weak_topics": weak_topics[:10], "recommended_materials": materials}
