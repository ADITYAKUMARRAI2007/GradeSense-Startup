"""Exam routes - CRUD, close/reopen, extract questions, student-upload workflow."""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from datetime import datetime, timezone
from typing import Optional, List
import uuid
import asyncio
import pickle

from app.database import db, fs
from app.deps import get_current_user
from app.models.user import User
from app.models.exam import ExamCreate, StudentExamCreate
from app.utils.serialization import serialize_doc
from app.utils.validation import infer_upsc_paper
from app.services.gridfs_helpers import get_exam_model_answer_images, get_exam_question_paper_images
from app.config import logger, get_llm_api_key
from app.utils.concurrency import conversion_semaphore
from app.utils.file_utils import convert_to_images
from app.services.llm import LlmChat, UserMessage
from app.utils.blueprint import (
    compute_blueprint_health,
    compute_attempt_rules_v2,
    compute_effective_total_marks_v2,
    compute_or_groups_map_v2,
    compute_structure_hash,
    derive_expected_question_count,
    evaluate_blueprint_lock_readiness,
    normalize_question_structure_v2,
)

router = APIRouter(tags=["exams"])


def _derive_blueprint_health(exam_doc: dict, questions: List[dict]) -> dict:
    expected_count = derive_expected_question_count(exam_doc or {}, fallback_questions=questions)
    failed_chunks = ((exam_doc or {}).get("blueprint_health", {}) or {}).get("failed_chunks")
    return compute_blueprint_health(
        questions or [],
        expected_count=expected_count,
        failed_chunks=failed_chunks,
    )


@router.get("/exams")
async def get_exams(
    batch_id: Optional[str] = None,
    subject_id: Optional[str] = None,
    status: Optional[str] = None,
    user: User = Depends(get_current_user)
):
    """Get all exams"""
    if user.role == "teacher":
        query = {"teacher_id": user.user_id}
    else:
        query = {"batch_id": {"$in": user.batches}}

    if batch_id:
        query["batch_id"] = batch_id
    if subject_id:
        query["subject_id"] = subject_id
    if status:
        query["status"] = status

    exams = await db.exams.find(query, {"_id": 0}).to_list(100)

    for exam in exams:
        batch = await db.batches.find_one({"batch_id": exam["batch_id"]}, {"_id": 0, "name": 1})
        subject = await db.subjects.find_one({"subject_id": exam["subject_id"]}, {"_id": 0, "name": 1})
        exam["batch_name"] = batch["name"] if batch else "Unknown"
        exam["subject_name"] = subject["name"] if subject else "Unknown"
        exam["upsc_paper"] = infer_upsc_paper(exam.get("exam_name"), exam.get("subject_name"))

        sub_count = await db.submissions.count_documents({"exam_id": exam["exam_id"]})
        exam["submission_count"] = sub_count

    return serialize_doc(exams)


@router.post("/exams")
async def create_exam(exam: ExamCreate, user: User = Depends(get_current_user)):
    """Create a new exam"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can create exams")

    exam_name_normalized = exam.exam_name.strip().lower()

    existing_exams = await db.exams.find({
        "batch_id": exam.batch_id,
        "teacher_id": user.user_id
    }, {"_id": 0, "exam_name": 1, "exam_id": 1}).to_list(1000)

    for existing in existing_exams:
        existing_name_normalized = existing.get("exam_name", "").strip().lower()
        if existing_name_normalized == exam_name_normalized:
            logger.warning(f"Duplicate exam found: '{exam.exam_name}' matches existing '{existing.get('exam_name')}' (ID: {existing.get('exam_id')}) in batch {exam.batch_id}")
            raise HTTPException(status_code=400, detail=f"An exam named '{exam.exam_name}' already exists in this batch")

    exam_id = f"exam_{uuid.uuid4().hex[:8]}"
    new_exam = {
        "exam_id": exam_id,
        "batch_id": exam.batch_id,
        "subject_id": exam.subject_id,
        "exam_type": exam.exam_type,
        "exam_name": exam.exam_name,
        "total_marks": exam.total_marks,
        "exam_date": exam.exam_date,
        "grading_mode": exam.grading_mode,
        "questions": exam.questions,
        "question_extraction_status": "pending",
        "question_paper_processing": False,
        "processing_state": "idle",
        "processing_lock_at": None,
        "processing_lock_owner": None,
        "blueprint_status": "pending",
        "blueprint_locked": False,
        "blueprint_locked_at": None,
        "blueprint_version": 0,
        "structure_confidence": 0.0,
        "question_structure_v2": None,
        "question_structure_validation": None,
        "question_structure_confidence": 0.0,
        "question_structure_source": None,
        "question_structure_retry_count": 0,
        "active_structure_hash": None,
        "effective_total_marks": float(exam.total_marks or 0),
        "or_groups_map": {},
        "attempt_rules": {},
        "locked_at": None,
        "model_name": None,
        "prompt_version": None,
        "pipeline_version": None,
        "extraction_hash": None,
        "blueprint_health": _derive_blueprint_health({}, exam.questions or []),
        "college_pipeline_version": "v3" if str(exam.exam_type).lower() == "college" else None,
        "teacher_id": user.user_id,
        "status": "draft",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.exams.insert_one(new_exam)
    logger.info(f"Created new exam: {exam_id} - '{exam.exam_name}' in batch {exam.batch_id}")
    return {"exam_id": exam_id, "status": "draft"}


@router.get("/exams/{exam_id}")
async def get_exam(exam_id: str, user: User = Depends(get_current_user)):
    """Get exam details including files from separate collection"""
    try:
        exam = await db.exams.find_one({"exam_id": exam_id}, {"_id": 0})
        if not exam:
            raise HTTPException(status_code=404, detail="Exam not found")

        model_answer_imgs = await get_exam_model_answer_images(exam_id)
        if model_answer_imgs:
            exam["model_answer_images"] = model_answer_imgs

        question_paper_imgs = await get_exam_question_paper_images(exam_id)
        if question_paper_imgs:
            exam["question_paper_images"] = question_paper_imgs

        exam["upsc_paper"] = infer_upsc_paper(exam.get("exam_name"), exam.get("subject_name"))

        return serialize_doc(exam)
    except Exception as e:
        logger.error(f"Error fetching exam {exam_id}: {e}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/exams/{exam_id}")
async def update_exam(exam_id: str, update_data: dict, user: User = Depends(get_current_user)):
    """Update exam details including name, subject, total marks, grading mode, etc."""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can update exams")

    exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    update_fields = {}

    if "questions" in update_data:
        # Removed 409 check - allow editing even during extraction
        # extraction_status = str(exam.get("question_extraction_status", "")).lower()
        # if exam.get("question_paper_processing") or extraction_status == "processing":
        #     raise HTTPException(
        #         status_code=409,
        #         detail="Question extraction is in progress. Wait for completion before editing questions.",
        #     )
        extraction_status = str(exam.get("question_extraction_status", "")).lower()
        if str(exam.get("blueprint_status", "pending")).lower() == "ready_locked":
            raise HTTPException(
                status_code=423,
                detail="Blueprint is locked. Unlock blueprint before editing questions.",
            )
        existing_questions = exam.get("questions") or []
        new_questions = update_data["questions"] or []
        if (
            exam.get("has_question_paper")
            and extraction_status == "completed"
            and len(existing_questions) >= 5
            and len(new_questions) <= 1
            and not bool(update_data.get("force_question_override"))
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "message": (
                        "Refusing risky question overwrite: extracted blueprint has many questions, "
                        "but update payload contains 0/1 question."
                    ),
                    "required_action": (
                        "Use Auto-Extract flow, or send force_question_override=true only if this is intentional."
                    ),
                    "existing_question_count": len(existing_questions),
                    "incoming_question_count": len(new_questions),
                },
            )
        update_fields["questions"] = update_data["questions"]
        health = _derive_blueprint_health(exam, update_data["questions"] or [])
        update_fields["blueprint_health"] = health
        update_fields["blueprint_status"] = "ready_unlocked" if health.get("question_count", 0) > 0 else "pending"
        update_fields["blueprint_locked"] = False
        update_fields["blueprint_version"] = int(exam.get("blueprint_version", 0) or 0) + 1
        update_fields["blueprint_locked_at"] = None
        logger.info(f"Updating {len(update_data['questions'])} questions for exam {exam_id}")

    if "exam_name" in update_data:
        update_fields["exam_name"] = update_data["exam_name"]
    if "subject_id" in update_data:
        update_fields["subject_id"] = update_data["subject_id"]
    if "total_marks" in update_data:
        update_fields["total_marks"] = float(update_data["total_marks"])
    if "grading_mode" in update_data:
        update_fields["grading_mode"] = update_data["grading_mode"]
    if "exam_type" in update_data:
        update_fields["exam_type"] = update_data["exam_type"]
    if "exam_date" in update_data:
        update_fields["exam_date"] = update_data["exam_date"]

    if update_fields:
        update_fields["updated_at"] = datetime.now(timezone.utc).isoformat()
        await db.exams.update_one(
            {"exam_id": exam_id},
            {"$set": update_fields}
        )
        logger.info(f"Updated exam {exam_id}: {list(update_fields.keys())}")

    return {"message": "Exam updated successfully", "updated_fields": list(update_fields.keys())}


@router.get("/exams/{exam_id}/blueprint-health")
async def get_blueprint_health(exam_id: str, user: User = Depends(get_current_user)):
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can view blueprint health")

    exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    questions = exam.get("questions", []) or []
    health = _derive_blueprint_health(exam, questions)
    await db.exams.update_one(
        {"exam_id": exam_id},
        {"$set": {"blueprint_health": health, "blueprint_checked_at": datetime.now(timezone.utc).isoformat()}},
    )

    return {
        "exam_id": exam_id,
        "blueprint_status": exam.get("blueprint_status", "pending"),
        "blueprint_locked": bool(exam.get("blueprint_locked", False)),
        "blueprint_version": int(exam.get("blueprint_version", 0) or 0),
        "blueprint_locked_at": exam.get("blueprint_locked_at"),
        "blueprint_health": health,
    }


@router.post("/exams/{exam_id}/lock-blueprint")
async def lock_blueprint(exam_id: str, user: User = Depends(get_current_user)):
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can lock blueprint")

    exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    if str(exam.get("blueprint_status", "pending")).lower() == "ready_locked":
        return {
            "message": "Blueprint already locked",
            "exam_id": exam_id,
            "blueprint_status": "ready_locked",
            "blueprint_locked": True,
            "blueprint_locked_at": exam.get("blueprint_locked_at"),
            "blueprint_health": exam.get("blueprint_health"),
        }

    # Removed 409 check - allow locking even during extraction
    # extraction_status = str(exam.get("question_extraction_status", "")).lower()
    # if exam.get("question_paper_processing") or extraction_status == "processing":
    #     raise HTTPException(status_code=409, detail="Question extraction is still processing")

    questions = exam.get("questions", []) or []
    if not questions:
        raise HTTPException(status_code=400, detail="No extracted questions to lock")

    readiness = evaluate_blueprint_lock_readiness(exam, questions=questions)
    health = readiness.get("health") or {}
    if not readiness.get("can_lock"):
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Blueprint lock blocked: blueprint health check failed",
                "question_count": int(readiness.get("question_count", 0) or 0),
                "question_paper_pages": int(readiness.get("question_paper_pages", 0) or 0),
                "issues": readiness.get("issues", []),
                "health": health,
            },
        )

    now = datetime.now(timezone.utc).isoformat()
    question_structure_v2 = exam.get("question_structure_v2") or {
        "questions": [
            {
                "number": q.get("question_number"),
                "section": None,
                "instruction": None,
                "question_text": q.get("question_text") or q.get("rubric") or "",
                "question_type": q.get("question_type", "descriptive"),
                "marks": float(q.get("max_marks") or 0.0),
                "options": None,
                "subquestions": [
                    {
                        "label": sq.get("sub_id"),
                        "text": sq.get("rubric") or "",
                        "marks": float(sq.get("max_marks") or 0.0),
                    }
                    for sq in (q.get("sub_questions") or [])
                ],
                "or_group_id": q.get("or_group_id"),
            }
            for q in questions
        ],
        "total_questions": len(questions),
        "total_marks": float(exam.get("total_marks") or 0.0),
        "numbering_contiguous": bool(health.get("numbering_contiguous", False)),
    }
    question_structure_v2 = normalize_question_structure_v2(question_structure_v2)
    structure_hash = compute_structure_hash(question_structure_v2)
    effective_total_marks = compute_effective_total_marks_v2(question_structure_v2)
    or_groups_map = compute_or_groups_map_v2(question_structure_v2)
    attempt_rules = compute_attempt_rules_v2(question_structure_v2)
    next_version = int(exam.get("blueprint_version", 0) or 0) + 1

    await db.exam_blueprint_versions.insert_one(
        {
            "exam_id": exam_id,
            "blueprint_version": next_version,
            "structure_hash": structure_hash,
            "question_count": len(question_structure_v2.get("questions") or []),
            "effective_total_marks": effective_total_marks,
            "or_groups_map": or_groups_map,
            "attempt_rules": attempt_rules,
            "locked_at": now,
            "question_structure_v2": question_structure_v2,
            "validation_report": {"health": health},
            "structure_confidence": float(exam.get("question_structure_confidence") or 0.0),
            "model_name": exam.get("model_name"),
            "prompt_version": exam.get("prompt_version"),
            "pipeline_version": exam.get("pipeline_version"),
            "extraction_hash": exam.get("extraction_hash"),
            "created_at": now,
        }
    )
    logger.info(
        "BLUEPRINT_VERSION_CREATED exam_id=%s version=%s structure_hash=%s",
        exam_id,
        next_version,
        structure_hash,
    )

    await db.exams.update_one(
        {"exam_id": exam_id},
        {"$set": {
            "blueprint_status": "ready_locked",
            "blueprint_locked": True,
            "blueprint_locked_at": now,
            "blueprint_version": next_version,
            "blueprint_health": health,
            "question_structure_v2": question_structure_v2,
            "active_structure_hash": structure_hash,
            "effective_total_marks": effective_total_marks,
            "or_groups_map": or_groups_map,
            "attempt_rules": attempt_rules,
            "locked_at": now,
        }},
    )
    realign_update = await db.submissions.update_many(
        {
            "exam_id": exam_id,
            "$or": [
                {"blueprint_version_used": {"$exists": False}},
                {"blueprint_version_used": {"$ne": next_version}},
            ],
        },
        {"$set": {"realign_required": True}},
    )
    if int(realign_update.modified_count or 0) > 0:
        logger.info(
            "REALIGN_REQUIRED exam_id=%s version=%s affected_submissions=%s",
            exam_id,
            next_version,
            int(realign_update.modified_count or 0),
        )
    logger.info("OR_RULES_FROZEN exam_id=%s version=%s", exam_id, next_version)
    logger.info("BLUEPRINT_LOCKED exam_id=%s version=%s source=manual", exam_id, next_version)
    return {
        "message": "Blueprint locked",
        "exam_id": exam_id,
        "blueprint_status": "ready_locked",
        "blueprint_locked": True,
        "blueprint_locked_at": now,
        "blueprint_health": health,
    }


@router.post("/exams/{exam_id}/unlock-blueprint")
async def unlock_blueprint(exam_id: str, user: User = Depends(get_current_user)):
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can unlock blueprint")

    exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    questions = exam.get("questions", []) or []
    health = _derive_blueprint_health(exam, questions)
    await db.exams.update_one(
        {"exam_id": exam_id},
        {"$set": {
            "blueprint_status": "ready_unlocked" if questions else "pending",
            "blueprint_locked": False,
            "blueprint_locked_at": None,
            "blueprint_health": health,
        }},
    )
    return {
        "message": "Blueprint unlocked",
        "exam_id": exam_id,
        "blueprint_status": "ready_unlocked" if questions else "pending",
        "blueprint_locked": False,
        "blueprint_health": health,
    }


@router.delete("/exams/{exam_id}")
async def delete_exam(exam_id: str, user: User = Depends(get_current_user)):
    """Delete an exam and all its submissions, and cancel any active grading jobs"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can delete exams")

    exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    logger.info(f"Cancelling active grading jobs for exam {exam_id}")
    cancelled_jobs = await db.grading_jobs.update_many(
        {"exam_id": exam_id, "status": {"$in": ["pending", "processing"]}},
        {"$set": {
            "status": "cancelled",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "cancellation_reason": "Exam deleted by teacher"
        }}
    )

    cancelled_tasks = await db.tasks.update_many(
        {"data.exam_id": exam_id, "status": {"$in": ["pending", "processing"]}},
        {"$set": {"status": "cancelled"}}
    )

    if cancelled_jobs.modified_count > 0 or cancelled_tasks.modified_count > 0:
        logger.info(f"Cancelled {cancelled_jobs.modified_count} jobs and {cancelled_tasks.modified_count} tasks for exam {exam_id}")

    await db.submissions.delete_many({"exam_id": exam_id})
    await db.re_evaluations.delete_many({"exam_id": exam_id})
    await db.exam_files.delete_many({"exam_id": exam_id})

    try:
        for grid_file in fs.find({"exam_id": exam_id}):
            fs.delete(grid_file._id)
            logger.info(f"Deleted GridFS file: {grid_file.filename}")
    except Exception as e:
        logger.warning(f"Error cleaning up GridFS files for exam {exam_id}: {e}")

    result = await db.exams.delete_one({"exam_id": exam_id, "teacher_id": user.user_id})

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Exam not found")

    return {
        "message": "Exam deleted successfully",
        "cancelled_jobs": cancelled_jobs.modified_count,
        "cancelled_tasks": cancelled_tasks.modified_count
    }


@router.put("/exams/{exam_id}/close")
async def close_exam(exam_id: str, user: User = Depends(get_current_user)):
    """Close an exam (prevent further uploads/edits)"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can close exams")

    exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    await db.exams.update_one(
        {"exam_id": exam_id},
        {"$set": {"status": "closed", "closed_at": datetime.now(timezone.utc).isoformat()}}
    )

    return {"message": "Exam closed successfully"}


@router.put("/exams/{exam_id}/reopen")
async def reopen_exam(exam_id: str, user: User = Depends(get_current_user)):
    """Reopen a closed exam"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can reopen exams")

    exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    await db.exams.update_one(
        {"exam_id": exam_id},
        {"$set": {"status": "completed", "reopened_at": datetime.now(timezone.utc).isoformat()}}
    )

    return {"message": "Exam reopened successfully"}


@router.post("/exams/{exam_id}/extract-questions")
async def extract_and_update_questions(exam_id: str, user: User = Depends(get_current_user)):
    """Extract question structure from question paper, else answer sheets."""
    from app.services.extraction import auto_extract_questions

    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can update exams")

    exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    if str(exam.get("blueprint_status", "pending")).lower() == "ready_locked":
        raise HTTPException(status_code=423, detail="Blueprint is locked. Unlock before re-extracting questions.")

    result = await auto_extract_questions(
        exam_id=exam_id,
        force=True,
        use_model_answer_fallback=False
    )

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "Failed to extract questions"))

    return {
        "message": result.get("message", "Questions extracted"),
        "updated_count": result.get("count", 0),
        "source": result.get("source", "")
    }


@router.post("/exams/{exam_id}/re-extract-questions")
async def re_extract_question_structure(exam_id: str, user: User = Depends(get_current_user)):
    """Re-extract COMPLETE question structure (with force=True)."""
    from app.services.extraction import auto_extract_questions

    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can re-extract questions")

    exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    if str(exam.get("blueprint_status", "pending")).lower() == "ready_locked":
        raise HTTPException(status_code=423, detail="Blueprint is locked. Unlock before re-extracting questions.")

    result = await auto_extract_questions(
        exam_id=exam_id,
        force=True,
        use_model_answer_fallback=False
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=result.get("message", "Failed to re-extract questions")
        )

    return {
        "message": result.get("message"),
        "count": result.get("count", 0),
        "total_marks": result.get("total_marks", 0),
        "source": result.get("source", ""),
        "questions": exam.get("questions", [])
    }


@router.post("/exams/{exam_id}/infer-topics")
async def infer_question_topics(
    exam_id: str,
    user: User = Depends(get_current_user)
):
    """Use AI to infer topic tags for each question in an exam"""
    import json

    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can infer topics")

    exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    questions = exam.get("questions", [])
    if not questions:
        raise HTTPException(status_code=400, detail="No questions found in exam")

    subject = await db.subjects.find_one({"subject_id": exam.get("subject_id")}, {"_id": 0, "name": 1})
    subject_name = subject.get("name", "General") if subject else "General"

    questions_text = []
    for q in questions:
        q_text = q.get("rubric", "") or q.get("question_text", "")
        questions_text.append(f"Q{q.get('question_number')}: {q_text[:200]}")

    prompt = f"""Subject: {subject_name}
Exam: {exam.get('exam_name', '')}

For each question below, suggest 1-3 topic tags that describe what the question is about.
Return a JSON array where each element has "question_number" and "topics" (array of strings).

Questions:
{chr(10).join(questions_text)}

Return ONLY valid JSON, no explanation."""

    try:
        chat = LlmChat(
            api_key=get_llm_api_key() or "",
            session_id=f"infer_topics_{uuid.uuid4().hex[:8]}",
            system_message="You are an exam topic classifier."
        ).with_model("gemini", "gemini-2.5-flash").with_params(temperature=0)

        response_text = await asyncio.wait_for(
            chat.send_message(UserMessage(text=prompt)),
            timeout=60.0
        )
        response_text = response_text.strip()
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()

        topic_data = json.loads(response_text)

        updated_count = 0
        for topic_item in topic_data:
            q_num = topic_item.get("question_number")
            topics = topic_item.get("topics", [])

            for q in questions:
                if q.get("question_number") == q_num:
                    q["topic_tags"] = topics
                    updated_count += 1
                    break

        await db.exams.update_one(
            {"exam_id": exam_id},
            {"$set": {"questions": questions}}
        )

        return {
            "message": f"Inferred topics for {updated_count} questions",
            "updated_count": updated_count,
            "topics": topic_data
        }

    except Exception as e:
        logger.error(f"Error inferring topics: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to infer topics: {str(e)}")


@router.put("/exams/{exam_id}/question-topics")
async def update_question_topics(
    exam_id: str,
    data: dict,
    user: User = Depends(get_current_user)
):
    """Manually update topic tags for questions"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can update topics")

    exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    questions = exam.get("questions", [])
    topic_updates = data.get("topics", {})

    for q in questions:
        q_num = str(q.get("question_number"))
        if q_num in topic_updates:
            q["topic_tags"] = topic_updates[q_num]

    await db.exams.update_one(
        {"exam_id": exam_id},
        {"$set": {"questions": questions}}
    )

    return {"message": "Topics updated successfully"}


# ============== STUDENT-UPLOAD EXAM WORKFLOW ==============

@router.post("/exams/student-mode")
async def create_student_upload_exam(
    exam_data: StudentExamCreate,
    question_paper: UploadFile = File(...),
    model_answer: UploadFile = File(...),
    user: User = Depends(get_current_user)
):
    """Create exam where students upload their answer papers"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can create exams")

    exam_id = f"exam_{uuid.uuid4().hex[:12]}"

    qp_bytes = await question_paper.read()
    qp_file_ref = f"qp_{exam_id}"
    fs.put(qp_bytes, filename=qp_file_ref)

    ma_bytes = await model_answer.read()
    ma_file_ref = f"ma_{exam_id}"
    fs.put(ma_bytes, filename=ma_file_ref)

    exam_doc = {
        "exam_id": exam_id,
        "batch_id": exam_data.batch_id,
        "exam_name": exam_data.exam_name,
        "total_marks": exam_data.total_marks,
        "grading_mode": exam_data.grading_mode,
        "exam_mode": "student_upload",
        "show_question_paper": exam_data.show_question_paper,
        "question_paper_ref": qp_file_ref,
        "model_answer_ref": ma_file_ref,
        "questions": [q.dict() for q in exam_data.questions],
        "question_extraction_status": "completed" if exam_data.questions else "pending",
        "question_paper_processing": False,
        "blueprint_status": "ready_locked" if exam_data.questions else "pending",
        "blueprint_locked_at": datetime.now(timezone.utc).isoformat() if exam_data.questions else None,
        "blueprint_version": 1 if exam_data.questions else 0,
        "blueprint_health": _derive_blueprint_health({}, [q.dict() for q in exam_data.questions]),
        "teacher_id": user.user_id,
        "selected_students": exam_data.student_ids,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "awaiting_submissions",
        "total_students": len(exam_data.student_ids),
        "submitted_count": 0
    }

    await db.exams.insert_one(exam_doc)
    logger.info(f"Created student-upload exam {exam_id} with {len(exam_data.student_ids)} students")

    return {"exam_id": exam_id, "message": "Exam created. Students can now submit their answers."}


@router.get("/exams/{exam_id}/submissions-status")
async def get_submission_status(exam_id: str, user: User = Depends(get_current_user)):
    """Get submission status for a student-upload exam"""
    exam = await db.exams.find_one({"exam_id": exam_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    if exam.get("exam_mode") != "student_upload":
        raise HTTPException(status_code=400, detail="This is not a student-upload exam")

    submissions = await db.student_submissions.find(
        {"exam_id": exam_id},
        {"_id": 0}
    ).to_list(1000)

    selected_students = exam.get("selected_students", [])
    submitted_ids = {sub["student_id"] for sub in submissions}

    students_info = []
    for student_id in selected_students:
        student = await db.users.find_one({"user_id": student_id}, {"_id": 0})
        if student:
            has_submitted = student_id in submitted_ids
            submission = next((s for s in submissions if s["student_id"] == student_id), None)
            students_info.append({
                "student_id": student_id,
                "name": student["name"],
                "email": student["email"],
                "submitted": has_submitted,
                "submitted_at": submission["submitted_at"] if submission else None
            })

    return {
        "exam_id": exam_id,
        "exam_name": exam["exam_name"],
        "total_students": len(selected_students),
        "submitted_count": len(submitted_ids),
        "students": students_info,
        "all_submitted": len(submitted_ids) == len(selected_students)
    }


@router.post("/exams/{exam_id}/submit")
async def submit_student_answer(
    exam_id: str,
    answer_paper: UploadFile = File(...),
    user: User = Depends(get_current_user)
):
    """Student submits their answer paper"""
    if user.role != "student":
        raise HTTPException(status_code=403, detail="Only students can submit answers")

    exam = await db.exams.find_one({"exam_id": exam_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    if exam.get("exam_mode") != "student_upload":
        raise HTTPException(status_code=400, detail="This exam does not accept student submissions")

    if user.user_id not in exam.get("selected_students", []):
        raise HTTPException(status_code=403, detail="You are not enrolled in this exam")

    existing = await db.student_submissions.find_one({
        "exam_id": exam_id,
        "student_id": user.user_id
    })
    if existing:
        raise HTTPException(status_code=400, detail="You have already submitted. Re-submission is not allowed.")

    file_bytes = await answer_paper.read()
    file_ref = f"ans_{exam_id}_{user.user_id}"

    gridfs_id = fs.put(
        file_bytes,
        filename=file_ref,
        contentType=answer_paper.content_type or 'application/pdf',
        exam_id=exam_id,
        student_id=user.user_id
    )

    submission_id = f"sub_{uuid.uuid4().hex[:12]}"
    submission_doc = {
        "submission_id": submission_id,
        "exam_id": exam_id,
        "student_id": user.user_id,
        "student_name": user.name,
        "student_email": user.email,
        "answer_file_ref": file_ref,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "status": "submitted"
    }

    await db.student_submissions.insert_one(submission_doc)

    await db.exams.update_one(
        {"exam_id": exam_id},
        {"$inc": {"submitted_count": 1}}
    )

    logger.info(f"Student {user.user_id} submitted answer for exam {exam_id}")

    return {"message": "Answer submitted successfully", "submission_id": submission_id}


@router.delete("/exams/{exam_id}/remove-student/{student_id}")
async def remove_student_from_exam(
    exam_id: str,
    student_id: str,
    user: User = Depends(get_current_user)
):
    """Teacher removes a student from exam (for non-submitters)"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can remove students")

    exam = await db.exams.find_one({"exam_id": exam_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    if exam["teacher_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Not your exam")

    await db.exams.update_one(
        {"exam_id": exam_id},
        {
            "$pull": {"selected_students": student_id},
            "$inc": {"total_students": -1}
        }
    )

    logger.info(f"Teacher {user.user_id} removed student {student_id} from exam {exam_id}")

    return {"message": "Student removed from exam"}


@router.post("/exams/{exam_id}/publish-results")
async def publish_exam_results(
    exam_id: str,
    data: dict,
    user: User = Depends(get_current_user)
):
    """Publish exam results to students"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can publish results")

    exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    await db.exams.update_one(
        {"exam_id": exam_id},
        {"$set": {
            "results_published": True,
            "results_published_at": datetime.now(timezone.utc).isoformat(),
            "publish_options": data.get("options", {})
        }}
    )

    return {"message": "Results published successfully"}


@router.post("/exams/{exam_id}/unpublish-results")
async def unpublish_exam_results(exam_id: str, user: User = Depends(get_current_user)):
    """Unpublish exam results"""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can unpublish results")

    exam = await db.exams.find_one({"exam_id": exam_id, "teacher_id": user.user_id}, {"_id": 0})
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    await db.exams.update_one(
        {"exam_id": exam_id},
        {"$set": {"results_published": False}}
    )

    return {"message": "Results unpublished"}
