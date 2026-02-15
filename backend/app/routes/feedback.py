"""Feedback routes — submit feedback, apply to batch/all papers, teacher patterns."""

import json
import re
import uuid
from typing import Optional, Dict, List, Any
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.database import db
from app.config import logger, get_llm_api_key
from app.deps import get_current_user
from app.models.user import User
from app.models.feedback import FeedbackSubmit
from app.models.admin import PublishResultsRequest
from app.services.extraction import get_exam_model_answer_text
from app.services.llm import LlmChat, UserMessage, ImageContent

router = APIRouter(tags=["feedback"])


# ============== SUBMIT FEEDBACK ==============

@router.post("/feedback/submit")
async def submit_grading_feedback(feedback: FeedbackSubmit, user: User = Depends(get_current_user)):
    """Submit feedback to improve AI grading"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can submit feedback")

    feedback_id = f"feedback_{uuid.uuid4().hex[:8]}"

    exam_id = None
    grading_mode = None
    student_answer_summary = None
    subject_id = "unknown"

    if feedback.submission_id:
        submission = await db.submissions.find_one(
            {"submission_id": feedback.submission_id},
            {"_id": 0, "exam_id": 1, "question_scores": 1}
        )
        if submission:
            exam_id = submission.get("exam_id")
            if feedback.question_number:
                qs = next((q for q in submission.get("question_scores", [])
                          if q["question_number"] == feedback.question_number), None)
                if qs:
                    student_answer_summary = qs.get("ai_feedback", "")[:200]

            exam = await db.exams.find_one({"exam_id": exam_id}, {"_id": 0, "grading_mode": 1, "subject_id": 1})
            if exam:
                grading_mode = exam.get("grading_mode")
                subject_id = exam.get("subject_id", "unknown")

    feedback_doc = {
        "feedback_id": feedback_id,
        "teacher_id": user.user_id,
        "submission_id": feedback.submission_id,
        "exam_id": feedback.exam_id or exam_id,
        "subject_id": subject_id,
        "question_number": feedback.question_number,
        "sub_question_id": feedback.sub_question_id,
        "feedback_type": feedback.feedback_type,
        "question_text": feedback.question_text,
        "question_topic": feedback.question_topic,
        "student_answer_summary": student_answer_summary,
        "ai_grade": feedback.ai_grade,
        "ai_feedback": feedback.ai_feedback,
        "teacher_expected_grade": feedback.teacher_expected_grade,
        "teacher_correction": feedback.teacher_correction,
        "grading_mode": grading_mode,
        "is_common": False,
        "upvote_count": 0,
        "created_at": datetime.now(timezone.utc)
    }

    await db.grading_feedback.insert_one(feedback_doc)

    return {
        "message": "Feedback submitted successfully",
        "feedback_id": feedback_id,
        "exam_id": exam_id
    }


# ============== APPLY FEEDBACK TO BATCH ==============

@router.post("/feedback/{feedback_id}/apply-to-batch")
async def apply_feedback_to_batch(
    feedback_id: str,
    user: User = Depends(get_current_user)
):
    """Re-grade a specific question across all submissions in the batch based on teacher feedback"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can apply feedback")

    feedback = await db.grading_feedback.find_one({"feedback_id": feedback_id}, {"_id": 0})
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")

    exam_id = feedback.get("exam_id")
    question_number = feedback.get("question_number")
    teacher_correction = feedback.get("teacher_correction")

    if not exam_id or not question_number:
        raise HTTPException(status_code=400, detail="Missing exam_id or question_number in feedback")

    submissions = await db.submissions.find(
        {"exam_id": exam_id, "status": "ai_graded"},
        {"_id": 0, "submission_id": 1, "question_scores": 1, "file_images": 1}
    ).to_list(1000)

    if not submissions:
        return {"message": "No submissions to re-grade", "updated_count": 0}

    exam = await db.exams.find_one({"exam_id": exam_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    question = await db.questions.find_one(
        {"exam_id": exam_id, "question_number": question_number}, {"_id": 0}
    )
    if not question:
        question = next((q for q in exam.get("questions", []) if q.get("question_number") == question_number), None)
    if not question:
        raise HTTPException(status_code=404, detail=f"Question {question_number} not found")

    model_answer_text = await get_exam_model_answer_text(exam_id)

    updated_count = 0

    for submission in submissions:
        try:
            question_scores = submission.get("question_scores", [])
            q_score = next((qs for qs in question_scores if qs.get("question_number") == question_number), None)
            if not q_score:
                continue

            student_images = submission.get("file_images", [])
            if not student_images:
                continue

            enhanced_prompt = f"""# RE-GRADING TASK - Question {question_number}

## TEACHER'S CORRECTION GUIDANCE
{teacher_correction}

## QUESTION DETAILS
Question {question_number}: {question.get('rubric', '')}
Maximum Marks: {question.get('max_marks')}

## MODEL ANSWER REFERENCE
{model_answer_text[:5000] if model_answer_text else "No model answer available"}

## TASK
Re-grade ONLY Question {question_number} based on the teacher's correction guidance above.
Apply the same grading standard the teacher expects.

## OUTPUT FORMAT
Return JSON:
{{
  "question_number": {question_number},
  "obtained_marks": <marks>,
  "ai_feedback": "<detailed feedback>",
  "sub_scores": []
}}
"""

            api_key = get_llm_api_key()
            chat = LlmChat(
                api_key=api_key,
                session_id=f"regrade_{submission['submission_id']}_{question_number}",
                system_message="You are an expert grader. Re-grade this specific question based on teacher's guidance."
            ).with_model("gemini", "gemini-2.5-flash").with_params(temperature=0)

            image_objs = [ImageContent(image_base64=img) for img in student_images[:10]]
            user_msg = UserMessage(text=enhanced_prompt, file_contents=image_objs)

            response = await chat.send_message(user_msg)

            resp_text = response.strip()
            new_score = None
            if resp_text.startswith("```"):
                resp_text = resp_text.split("```")[1]
                if resp_text.startswith("json"):
                    resp_text = resp_text[4:]
                resp_text = resp_text.strip()

            try:
                result = json.loads(resp_text)
                new_score = result
            except:
                json_match = re.search(r'\{[^{}]*"question_number"[^{}]*\}', resp_text, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                    new_score = result

            if new_score and "obtained_marks" in new_score:
                for qs in question_scores:
                    if qs.get("question_number") == question_number:
                        qs["obtained_marks"] = new_score["obtained_marks"]
                        qs["ai_feedback"] = new_score.get("ai_feedback", qs["ai_feedback"])
                        if "sub_scores" in new_score:
                            qs["sub_scores"] = new_score["sub_scores"]
                        break

                total_score = sum(qs.get("obtained_marks", 0) for qs in question_scores)

                await db.submissions.update_one(
                    {"submission_id": submission["submission_id"]},
                    {"$set": {
                        "question_scores": question_scores,
                        "total_score": total_score,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }}
                )
                updated_count += 1
                logger.info(f"Re-graded Q{question_number} for submission {submission['submission_id']}")

        except Exception as e:
            logger.error(f"Error re-grading submission {submission['submission_id']}: {e}")
            continue

    return {
        "message": f"Successfully re-graded question {question_number} for {updated_count} submissions",
        "updated_count": updated_count,
        "total_submissions": len(submissions)
    }


# ============== APPLY FEEDBACK TO ALL PAPERS ==============

@router.post("/feedback/{feedback_id}/apply-to-all-papers")
async def apply_feedback_to_all_papers(
    feedback_id: str,
    user: User = Depends(get_current_user)
):
    """Intelligent re-grading: Uses teacher's feedback to re-analyze each student's answer via AI"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can apply corrections")

    feedback = await db.grading_feedback.find_one({"feedback_id": feedback_id}, {"_id": 0})
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")

    exam_id = feedback.get("exam_id")
    question_number = feedback.get("question_number")
    sub_question_id = feedback.get("sub_question_id")
    teacher_correction = feedback.get("teacher_correction")

    if not exam_id or not question_number:
        raise HTTPException(status_code=400, detail="Missing exam_id or question_number")

    exam = await db.exams.find_one({"exam_id": exam_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    question = await db.questions.find_one(
        {"exam_id": exam_id, "question_number": question_number}, {"_id": 0}
    )
    if not question:
        question = next((q for q in exam.get("questions", []) if q.get("question_number") == question_number), None)
    if not question:
        raise HTTPException(status_code=404, detail=f"Question {question_number} not found")

    model_answer_text = await get_exam_model_answer_text(exam_id)

    submissions = await db.submissions.find(
        {"exam_id": exam_id},
        {"_id": 0, "submission_id": 1, "student_name": 1, "question_scores": 1, "file_images": 1, "total_score": 1}
    ).to_list(1000)

    if not submissions:
        return {"message": "No submissions found", "updated_count": 0}

    updated_count = 0
    failed_count = 0

    logger.info(f"Starting intelligent re-grading for {len(submissions)} papers - Question {question_number}" +
                (f" Sub-question {sub_question_id}" if sub_question_id and sub_question_id != "all" else ""))

    for idx, submission in enumerate(submissions):
        try:
            question_scores = submission.get("question_scores", [])
            q_index = next((i for i, qs in enumerate(question_scores)
                           if qs.get("question_number") == question_number), None)
            if q_index is None:
                continue

            question_score = question_scores[q_index]
            student_images = submission.get("file_images", [])
            if not student_images:
                logger.warning(f"No images for submission {submission['submission_id']}")
                continue

            if sub_question_id and sub_question_id != "all":
                # Re-grade specific sub-question
                sub_scores = question_score.get("sub_scores", [])
                sub_index = next((i for i, ss in enumerate(sub_scores)
                                 if ss.get("sub_id") == sub_question_id), None)
                if sub_index is None:
                    continue

                old_sub_score = sub_scores[sub_index]
                sub_question = next((sq for sq in question.get("sub_questions", [])
                                    if sq.get("sub_id") == sub_question_id), None)
                if not sub_question:
                    continue

                re_grade_prompt = f"""# INTELLIGENT RE-GRADING TASK

## TEACHER'S GRADING GUIDANCE
{teacher_correction}

## CONTEXT
- Question {question_number}, Part/Sub-question: {sub_question.get('sub_label', 'Part')}
- Maximum Marks: {sub_question.get('max_marks')}
- Sub-question: {sub_question.get('rubric', '')}

## MODEL ANSWER REFERENCE
{model_answer_text[:3000] if model_answer_text else "No model answer available"}

## YOUR TASK
Re-grade this student's answer for the sub-question based on the teacher's guidance above.

## OUTPUT FORMAT (JSON ONLY)
{{
  "obtained_marks": <marks between 0 and {sub_question.get('max_marks')}>,
  "ai_feedback": "<brief explanation of grading decision>"
}}
"""

                chat = LlmChat(
                    api_key=get_llm_api_key(),
                    session_id=f"regrade_{submission['submission_id']}_{question_number}_{sub_question_id}",
                    system_message="You are an expert grader. Re-grade based on teacher's guidance."
                ).with_model("gemini", "gemini-2.5-flash").with_params(temperature=0.3)

                image_objs = [ImageContent(image_base64=img) for img in student_images[:20]]
                user_msg = UserMessage(text=re_grade_prompt, file_contents=image_objs)
                result = await chat.send_message(user_msg)

                resp_text = result.strip()
                if resp_text.startswith("```"):
                    resp_text = resp_text.split("```")[1]
                    if resp_text.startswith("json"):
                        resp_text = resp_text[4:]
                re_grade_result = json.loads(resp_text.strip())

                new_marks = float(re_grade_result.get("obtained_marks", old_sub_score["obtained_marks"]))
                new_feedback = f"[Teacher Re-graded] {re_grade_result.get('ai_feedback', '')}"

                sub_scores[sub_index]["obtained_marks"] = new_marks
                sub_scores[sub_index]["ai_feedback"] = new_feedback

                new_question_total = sum(ss.get("obtained_marks", 0) for ss in sub_scores)
                question_scores[q_index]["obtained_marks"] = new_question_total
                question_scores[q_index]["sub_scores"] = sub_scores

                old_submission_total = submission.get("total_score", 0)
                old_question_total = question_score.get("obtained_marks", 0)
                new_submission_total = old_submission_total - old_question_total + new_question_total

                await db.submissions.update_one(
                    {"submission_id": submission["submission_id"]},
                    {"$set": {"question_scores": question_scores, "total_score": new_submission_total}}
                )
                updated_count += 1
                logger.info(f"[{idx+1}/{len(submissions)}] Re-graded {submission['student_name']} - Q{question_number} Part: {new_marks}/{sub_question.get('max_marks')}")

            else:
                # Re-grade whole question
                re_grade_prompt = f"""# INTELLIGENT RE-GRADING TASK

## TEACHER'S GRADING GUIDANCE
{teacher_correction}

## CONTEXT
- Question {question_number}
- Maximum Marks: {question.get('max_marks')}
- Question: {question.get('rubric', '')}

## MODEL ANSWER REFERENCE
{model_answer_text[:3000] if model_answer_text else "No model answer available"}

## YOUR TASK
Re-grade this student's entire answer for Question {question_number} based on the teacher's guidance above.

## OUTPUT FORMAT (JSON ONLY)
{{
  "obtained_marks": <marks between 0 and {question.get('max_marks')}>,
  "ai_feedback": "<brief explanation of grading decision>"
}}
"""

                chat = LlmChat(
                    api_key=get_llm_api_key(),
                    session_id=f"regrade_{submission['submission_id']}_{question_number}",
                    system_message="You are an expert grader. Re-grade based on teacher's guidance."
                ).with_model("gemini", "gemini-2.5-flash").with_params(temperature=0.3)

                image_objs = [ImageContent(image_base64=img) for img in student_images[:20]]
                user_msg = UserMessage(text=re_grade_prompt, file_contents=image_objs)
                result = await chat.send_message(user_msg)

                resp_text = result.strip()
                if resp_text.startswith("```"):
                    resp_text = resp_text.split("```")[1]
                    if resp_text.startswith("json"):
                        resp_text = resp_text[4:]
                re_grade_result = json.loads(resp_text.strip())

                new_marks = float(re_grade_result.get("obtained_marks", question_score.get("obtained_marks", 0)))
                new_feedback = f"[Teacher Re-graded] {re_grade_result.get('ai_feedback', '')}"

                question_scores[q_index]["obtained_marks"] = new_marks
                question_scores[q_index]["ai_feedback"] = new_feedback

                old_submission_total = submission.get("total_score", 0)
                old_question_total = question_score.get("obtained_marks", 0)
                new_submission_total = old_submission_total - old_question_total + new_marks

                await db.submissions.update_one(
                    {"submission_id": submission["submission_id"]},
                    {"$set": {"question_scores": question_scores, "total_score": new_submission_total}}
                )
                updated_count += 1
                logger.info(f"[{idx+1}/{len(submissions)}] Re-graded {submission['student_name']} - Q{question_number}: {new_marks}/{question.get('max_marks')}")

        except Exception as e:
            logger.error(f"Error re-grading submission {submission.get('submission_id')}: {e}")
            failed_count += 1
            continue

    logger.info(f"Intelligent re-grading complete: {updated_count} updated, {failed_count} failed")

    return {
        "message": f"Intelligently re-graded {updated_count} papers using your feedback",
        "updated_count": updated_count,
        "failed_count": failed_count
    }


# ============== APPLY MULTIPLE FEEDBACK TO ALL PAPERS ==============

@router.post("/feedback/apply-multiple-to-all-papers")
async def apply_multiple_feedback_to_all_papers(
    request: dict,
    user: User = Depends(get_current_user)
):
    """Apply multiple feedback corrections to all papers in ONE batch"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can apply corrections")

    feedback_ids = request.get("feedback_ids", [])
    if not feedback_ids:
        raise HTTPException(status_code=400, detail="No feedback IDs provided")

    feedbacks = await db.grading_feedback.find(
        {"feedback_id": {"$in": feedback_ids}},
        {"_id": 0}
    ).to_list(100)

    if not feedbacks:
        raise HTTPException(status_code=404, detail="No feedback found")

    # Group feedbacks by exam_id and question_number
    exam_question_groups = {}
    for feedback in feedbacks:
        exam_id = feedback.get("exam_id")
        question_number = feedback.get("question_number")
        key = f"{exam_id}_{question_number}"

        if key not in exam_question_groups:
            exam_question_groups[key] = {
                "exam_id": exam_id,
                "question_number": question_number,
                "feedbacks": []
            }
        exam_question_groups[key]["feedbacks"].append(feedback)

    total_updated = 0
    total_failed = 0

    for group_key, group in exam_question_groups.items():
        exam_id = group["exam_id"]
        question_number = group["question_number"]
        group_feedbacks = group["feedbacks"]

        logger.info(f"Processing {len(group_feedbacks)} corrections for Q{question_number} in exam {exam_id}")

        exam = await db.exams.find_one({"exam_id": exam_id}, {"_id": 0})
        if not exam:
            logger.error(f"Exam {exam_id} not found")
            continue

        question = await db.questions.find_one(
            {"exam_id": exam_id, "question_number": question_number}, {"_id": 0}
        )
        if not question:
            question = next((q for q in exam.get("questions", []) if q.get("question_number") == question_number), None)
        if not question:
            logger.error(f"Question {question_number} not found for exam {exam_id}")
            continue

        model_answer_text = await get_exam_model_answer_text(exam_id)

        submissions = await db.submissions.find(
            {"exam_id": exam_id},
            {"_id": 0, "submission_id": 1, "student_name": 1, "question_scores": 1, "file_images": 1, "total_score": 1}
        ).to_list(1000)

        if not submissions:
            logger.warning(f"No submissions found for exam {exam_id}")
            continue

        for idx, submission in enumerate(submissions):
            try:
                question_scores = submission.get("question_scores", [])
                q_index = next((i for i, qs in enumerate(question_scores)
                               if qs.get("question_number") == question_number), None)
                if q_index is None:
                    continue

                question_score = question_scores[q_index]
                student_images = submission.get("file_images", [])
                if not student_images:
                    logger.warning(f"No images for submission {submission['submission_id']}")
                    continue

                submission_updated = False
                old_question_total = question_score.get("obtained_marks", 0)

                for fb in group_feedbacks:
                    sub_question_id = fb.get("sub_question_id")
                    teacher_correction = fb.get("teacher_correction")
                    if not teacher_correction:
                        continue

                    if sub_question_id and sub_question_id != "all":
                        sub_scores = question_score.get("sub_scores", [])
                        sub_index = next((i for i, ss in enumerate(sub_scores)
                                         if ss.get("sub_id") == sub_question_id), None)
                        if sub_index is None:
                            continue

                        sub_question = next((sq for sq in question.get("sub_questions", [])
                                            if sq.get("sub_id") == sub_question_id), None)
                        if not sub_question:
                            continue

                        re_grade_prompt = f"""# INTELLIGENT RE-GRADING TASK

## TEACHER'S GRADING GUIDANCE
{teacher_correction}

## CONTEXT
- Question {question_number}, Part/Sub-question: {sub_question.get('sub_label', 'Part')}
- Maximum Marks: {sub_question.get('max_marks')}
- Sub-question: {sub_question.get('rubric', '')}

## MODEL ANSWER REFERENCE
{model_answer_text[:3000] if model_answer_text else "No model answer available"}

## YOUR TASK
Re-grade this student's answer based on the teacher's guidance above.

## OUTPUT FORMAT (JSON ONLY)
{{
  "obtained_marks": <marks between 0 and {sub_question.get('max_marks')}>,
  "ai_feedback": "<brief explanation>"
}}
"""

                        chat = LlmChat(
                            api_key=get_llm_api_key(),
                            session_id=f"regrade_multi_{submission['submission_id']}_{question_number}_{sub_question_id}",
                            system_message="You are an expert grader."
                        ).with_model("gemini", "gemini-2.5-flash").with_params(temperature=0.3)

                        image_objs = [ImageContent(image_base64=img) for img in student_images[:15]]
                        user_msg = UserMessage(text=re_grade_prompt, file_contents=image_objs)
                        result = await chat.send_message(user_msg)

                        resp_text = result.strip()
                        if resp_text.startswith("```"):
                            resp_text = resp_text.split("```")[1]
                            if resp_text.startswith("json"):
                                resp_text = resp_text[4:]
                        re_grade_result = json.loads(resp_text.strip())

                        new_marks = float(re_grade_result.get("obtained_marks", sub_scores[sub_index]["obtained_marks"]))
                        new_feedback = f"[Teacher Re-graded] {re_grade_result.get('ai_feedback', '')}"

                        sub_scores[sub_index]["obtained_marks"] = new_marks
                        sub_scores[sub_index]["ai_feedback"] = new_feedback
                        question_scores[q_index]["sub_scores"] = sub_scores

                        submission_updated = True
                        logger.info(f"[{idx+1}/{len(submissions)}] {submission['student_name']} - Q{question_number} Part {sub_question_id}: {new_marks}/{sub_question.get('max_marks')}")

                    else:
                        # Re-grade whole question
                        re_grade_prompt = f"""# INTELLIGENT RE-GRADING TASK

## TEACHER'S GRADING GUIDANCE
{teacher_correction}

## CONTEXT
- Question {question_number}
- Maximum Marks: {question.get('max_marks')}
- Question: {question.get('rubric', '')}

## MODEL ANSWER REFERENCE
{model_answer_text[:3000] if model_answer_text else "No model answer available"}

## YOUR TASK
Re-grade this student's entire answer based on the teacher's guidance above.

## OUTPUT FORMAT (JSON ONLY)
{{
  "obtained_marks": <marks between 0 and {question.get('max_marks')}>,
  "ai_feedback": "<brief explanation>"
}}
"""

                        chat = LlmChat(
                            api_key=get_llm_api_key(),
                            session_id=f"regrade_multi_{submission['submission_id']}_{question_number}",
                            system_message="You are an expert grader."
                        ).with_model("gemini", "gemini-2.5-flash").with_params(temperature=0.3)

                        image_objs = [ImageContent(image_base64=img) for img in student_images[:20]]
                        user_msg = UserMessage(text=re_grade_prompt, file_contents=image_objs)
                        result = await chat.send_message(user_msg)

                        resp_text = result.strip()
                        if resp_text.startswith("```"):
                            resp_text = resp_text.split("```")[1]
                            if resp_text.startswith("json"):
                                resp_text = resp_text[4:]
                        re_grade_result = json.loads(resp_text.strip())

                        new_marks = float(re_grade_result.get("obtained_marks", question_score.get("obtained_marks", 0)))
                        new_feedback = f"[Teacher Re-graded] {re_grade_result.get('ai_feedback', '')}"

                        question_scores[q_index]["obtained_marks"] = new_marks
                        question_scores[q_index]["ai_feedback"] = new_feedback

                        submission_updated = True
                        logger.info(f"[{idx+1}/{len(submissions)}] {submission['student_name']} - Q{question_number}: {new_marks}/{question.get('max_marks')}")

                if submission_updated:
                    if question_score.get("sub_scores"):
                        new_question_total = sum(ss.get("obtained_marks", 0) for ss in question_score["sub_scores"])
                        question_scores[q_index]["obtained_marks"] = new_question_total
                    else:
                        new_question_total = question_scores[q_index]["obtained_marks"]

                    old_submission_total = submission.get("total_score", 0)
                    new_submission_total = old_submission_total - old_question_total + new_question_total

                    await db.submissions.update_one(
                        {"submission_id": submission["submission_id"]},
                        {"$set": {"question_scores": question_scores, "total_score": new_submission_total}}
                    )
                    total_updated += 1

            except Exception as e:
                logger.error(f"Error re-grading submission {submission.get('submission_id')}: {e}")
                total_failed += 1
                continue

    logger.info(f"Multiple feedback re-grading complete: {total_updated} updated, {total_failed} failed")

    return {
        "message": f"Intelligently re-graded {total_updated} papers using {len(feedback_ids)} corrections",
        "updated_count": total_updated,
        "failed_count": total_failed
    }


# ============== PUBLISH / UNPUBLISH RESULTS ==============

@router.post("/exams/{exam_id}/publish-results")
async def publish_exam_results(
    exam_id: str,
    settings: PublishResultsRequest,
    user: User = Depends(get_current_user)
):
    """Publish exam results to make them visible to students with visibility controls"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can publish results")

    exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found or access denied")

    await db.exams.update_one(
        {"exam_id": exam_id},
        {"$set": {
            "results_published": True,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "student_visibility": {
                "show_model_answer": settings.show_model_answer,
                "show_answer_sheet": settings.show_answer_sheet,
                "show_question_paper": settings.show_question_paper,
                "show_feedback": True
            }
        }}
    )

    return {"message": "Results published successfully", "exam_id": exam_id, "visibility": settings.dict()}


@router.post("/exams/{exam_id}/unpublish-results")
async def unpublish_exam_results(exam_id: str, user: User = Depends(get_current_user)):
    """Unpublish exam results to hide them from students"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can unpublish results")

    exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found or access denied")

    await db.exams.update_one(
        {"exam_id": exam_id},
        {"$set": {"results_published": False}}
    )

    return {"message": "Results unpublished successfully", "exam_id": exam_id}


# ============== MY FEEDBACK & PATTERNS ==============

@router.get("/feedback/my-feedback")
async def get_my_feedback(user: User = Depends(get_current_user)):
    """Get teacher's own feedback submissions"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can view feedback")

    feedback = await db.grading_feedback.find(
        {"teacher_id": user.user_id},
        {"_id": 0}
    ).sort("created_at", -1).to_list(100)

    return {"feedback": feedback, "count": len(feedback)}


@router.get("/feedback/teacher-patterns/{teacher_id}")
async def get_teacher_feedback_patterns(teacher_id: str):
    """Get feedback patterns for a specific teacher to personalize grading"""
    feedback = await db.grading_feedback.find(
        {"teacher_id": teacher_id, "feedback_type": {"$in": ["question_grading", "correction"]}},
        {"_id": 0, "teacher_correction": 1, "grading_mode": 1, "question_text": 1, "ai_feedback": 1}
    ).sort("created_at", -1).to_list(10)

    return feedback


@router.get("/feedback/common-patterns")
async def get_common_feedback_patterns():
    """Get common feedback patterns across all teachers"""
    common_feedback = await db.grading_feedback.find(
        {"$or": [{"is_common": True}, {"upvote_count": {"$gte": 3}}]},
        {"_id": 0, "teacher_correction": 1, "grading_mode": 1, "feedback_type": 1}
    ).to_list(20)

    return common_feedback
