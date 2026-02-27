"""Submission routes - CRUD, approve, review."""

from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timezone
from typing import Optional, List
import asyncio
import pickle
import base64
import math
import os

from bson import ObjectId

from app.database import db, fs
from app.deps import get_current_user
from app.models.user import User
from app.services.score_normalization import normalize_submission_scores
from app.utils.serialization import serialize_doc
from app.config import (
    logger,
)

router = APIRouter(tags=["submissions"])

MAPPED_QUESTION_RATIO_MIN = float(os.getenv("MAPPED_QUESTION_RATIO_MIN", "0.85"))
MAPPING_COVERAGE_GATE_MIN = float(os.getenv("MAPPING_COVERAGE_GATE_MIN", "0.75"))
UNRESOLVED_RATIO_MAX = float(os.getenv("UNRESOLVED_RATIO_MAX", "0.10"))


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
            {"_id": 0, "questions": 1, "results_published": 1, "student_visibility": 1, "total_marks": 1}
        )

        # Self-heal legacy score metadata (e.g. 0/0 max marks with valid feedback)
        if exam:
            normalized = normalize_submission_scores(submission, exam, source="read")
            submission["question_scores"] = normalized["question_scores"]
            submission["total_score"] = normalized["total_score"]
            submission["percentage"] = normalized["percentage"]
            if normalized["changed"]:
                await db.submissions.update_one(
                    {"submission_id": submission_id},
                    {"$set": {
                        "question_scores": normalized["question_scores"],
                        "total_score": normalized["total_score"],
                        "percentage": normalized["percentage"],
                    }}
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
        {"_id": 0, "total_marks": 1, "teacher_id": 1, "questions": 1}
    )
    normalized = normalize_submission_scores(
        {
            "submission_id": submission_id,
            "question_scores": question_scores,
            "total_score": total_score,
            "percentage": updates.get("percentage"),
        },
        exam or {},
        source="manual_update",
    )
    question_scores = normalized["question_scores"]
    total_score = normalized["total_score"]
    percentage = normalized["percentage"]

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


@router.post("/submissions/{submission_id}/preflight-map")
async def preflight_submission_mapping(submission_id: str, user: User = Depends(get_current_user)):
    """Dry-run mapping report without grading; used to gate risky runs."""
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can run preflight mapping")

    from app.layers.ai_structured.engine import preflight_submission_mapping as ai_preflight

    try:
        return await ai_preflight(submission_id=submission_id, user_id=user.user_id)
    except RuntimeError as exc:
        reason = str(exc)
        if reason == "submission_not_found":
            raise HTTPException(status_code=404, detail="Submission not found")
        if reason == "exam_not_found":
            raise HTTPException(status_code=404, detail="Exam not found")
        if reason == "blueprint_not_locked":
            raise HTTPException(status_code=409, detail="Blueprint is not locked for this exam")
        raise HTTPException(status_code=400, detail=f"Preflight failed: {reason}")
    except Exception as exc:
        logger.error("Preflight mapping failed for submission %s: %s", submission_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Preflight failed: {exc}")

    submission = await db.submissions.find_one(
        {"submission_id": submission_id},
        {"_id": 0, "submission_id": 1, "exam_id": 1, "file_images": 1, "images_gridfs_id": 1},
    )
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    exam = await db.exams.find_one(
        {"exam_id": submission.get("exam_id"), "teacher_id": user.user_id},
        {"_id": 0, "exam_id": 1, "exam_type": 1, "questions": 1, "blueprint_status": 1, "blueprint_health": 1},
    )
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    images = submission.get("file_images") or []
    if not images and submission.get("images_gridfs_id"):
        try:
            img_oid = ObjectId(submission["images_gridfs_id"])
            if fs.exists(img_oid):
                images = pickle.loads(fs.get(img_oid).read())
        except Exception as e:
            logger.error(f"Preflight image load failed for {submission_id}: {e}")

    if not images:
        return {
            "submission_id": submission_id,
            "exam_id": submission.get("exam_id"),
            "mapping_status": "failed",
            "fail_reasons": ["missing_submission_images"],
            "message": "No submission images available for mapping preflight.",
        }

    questions = exam.get("questions", []) or []
    expected_qs = sorted(
        {
            int(q.get("question_number"))
            for q in questions
            if q.get("question_number") is not None and str(q.get("question_number", "")).isdigit()
        }
    )
    if not expected_qs:
        return {
            "submission_id": submission_id,
            "exam_id": submission.get("exam_id"),
            "mapping_status": "failed",
            "fail_reasons": ["missing_exam_questions"],
            "message": "No exam questions available for mapping preflight.",
        }

    question_paper_pdf_bytes = await get_exam_question_paper_pdf_bytes(submission.get("exam_id"))
    exam_type = str(exam.get("exam_type", "") or "").lower()
    use_universal_v2 = bool(
        False
    )
    use_aws_pipeline = bool(
        exam_type != "upsc"
    )
    use_college_v2 = bool(
        COLLEGE_V2_PIPELINE_ENABLED
        and exam_type != "upsc"
        and not use_universal_v2
        and not use_aws_pipeline
    )
    pipeline = None
    if use_universal_v2:
        pipeline, question_map = run_universal_pipeline_v2(
            exam_id=submission.get("exam_id") or "unknown_exam",
            exam_questions=questions,
            answer_images=images,
            question_paper_pdf_bytes=question_paper_pdf_bytes or None,
            failed_chunks=((exam.get("blueprint_health") or {}).get("failed_chunks") or []),
        )
    elif use_aws_pipeline:
        pipeline, question_map = run_aws_pipeline_v3(
            exam_id=submission.get("exam_id") or "unknown_exam",
            exam_questions=questions,
            answer_images=images,
        )
    elif use_college_v2:
        pipeline, question_map = run_college_pipeline_v3(
            exam_id=submission.get("exam_id") or "unknown_exam",
            exam_questions=questions,
            answer_images=images,
            question_paper_pdf_bytes=question_paper_pdf_bytes or None,
            failed_chunks=((exam.get("blueprint_health") or {}).get("failed_chunks") or []),
        )
    else:
        pipeline = run_answer_packet_pipeline(
            answer_images=images,
            questions=questions,
            question_paper_pdf_bytes=question_paper_pdf_bytes or None,
        )
        question_map = pipeline_result_to_question_map(pipeline)
    packet_meta = (question_map.get("_meta", {}) or {}).copy()

    detected_qs = sorted(
        [
            int(qn)
            for qn, payload in question_map.items()
            if isinstance(qn, int) and isinstance(payload, dict) and (payload.get("segments") or [])
        ]
    )
    mapped_question_ratio = len(detected_qs) / float(len(expected_qs)) if expected_qs else 0.0
    mapping_coverage = float(packet_meta.get("mapping_coverage", 0.0) or 0.0)
    unresolved_questions = sorted(set(expected_qs) - set(detected_qs))
    unresolved_limit = max(2, int(math.ceil(len(expected_qs) * UNRESOLVED_RATIO_MAX)))

    fail_reasons: List[str] = []
    if mapped_question_ratio < MAPPED_QUESTION_RATIO_MIN:
        fail_reasons.append(
            f"mapped_question_ratio_below_threshold:{mapped_question_ratio:.3f}<{MAPPED_QUESTION_RATIO_MIN:.3f}"
        )
    if mapping_coverage < MAPPING_COVERAGE_GATE_MIN:
        fail_reasons.append(
            f"mapping_coverage_below_threshold:{mapping_coverage:.3f}<{MAPPING_COVERAGE_GATE_MIN:.3f}"
        )
    if len(unresolved_questions) > unresolved_limit:
        fail_reasons.append(f"too_many_unresolved_questions:{len(unresolved_questions)}>{unresolved_limit}")
    for reason in (packet_meta.get("mapping_fail_reasons") or []):
        if reason not in fail_reasons:
            fail_reasons.append(str(reason))

    packet_summary = {
        str(qn): {
            "page_refs": (question_map.get(qn, {}) or {}).get("page_refs", []),
            "segment_count": len((question_map.get(qn, {}) or {}).get("segments", [])),
            "subquestion_count": int((question_map.get(qn, {}) or {}).get("subquestion_count", 0) or 0),
            "mapping_confidence": float((question_map.get(qn, {}) or {}).get("mapping_confidence", 0.0) or 0.0),
            "table_segments": (question_map.get(qn, {}) or {}).get("table_segments", []),
            "working_note_segments": (question_map.get(qn, {}) or {}).get("working_note_segments", []),
            "mapping_trace": (question_map.get(qn, {}) or {}).get("mapping_trace", []),
            "start_anchor": (question_map.get(qn, {}) or {}).get("start_anchor"),
            "end_anchor": (question_map.get(qn, {}) or {}).get("end_anchor"),
        }
        for qn in detected_qs
    }

    status = "pass" if not fail_reasons else "needs_review"
    if str(packet_meta.get("mapping_status", "") or "").lower() == "failed":
        status = "failed"
    confidence_vectors = (pipeline or {}).get("confidence_vectors", []) if isinstance(pipeline, dict) else []
    aligned_answers = (pipeline or {}).get("aligned_answers", []) if isinstance(pipeline, dict) else []
    return {
        "submission_id": submission_id,
        "exam_id": submission.get("exam_id"),
        "pipeline": packet_meta.get("pipeline", "legacy"),
        "blueprint_status": exam.get("blueprint_status", "pending"),
        "mapping_status": status,
        "mapped_question_ratio": round(mapped_question_ratio, 4),
        "mapping_coverage": round(mapping_coverage, 4),
        "unresolved_questions": unresolved_questions,
        "unresolved_limit": unresolved_limit,
        "expected_questions": expected_qs,
        "detected_questions": detected_qs,
        "packets_generated": int(packet_meta.get("packets_generated", len(detected_qs)) or len(detected_qs)),
        "subpacket_count": int(packet_meta.get("subpacket_count", 0) or 0),
        "low_confidence_questions": packet_meta.get("low_confidence_questions", []),
        "consistency_flags": packet_meta.get("consistency_flags", []),
        "fail_reasons": fail_reasons,
        "packet_summary": packet_summary,
        "confidence_vectors": confidence_vectors,
        "aligned_answers": [
            {
                "question_id": int(row.get("question_id", 0) or 0),
                "packet_id": row.get("packet_id") or ((row.get("packet") or {}).get("packet_id")),
                "aligned_by": row.get("aligned_by"),
                "alignment_confidence": float(row.get("alignment_confidence", 0.0) or 0.0),
            }
            for row in (aligned_answers or [])
        ],
        "phase_timings": packet_meta.get("phase_timings", {}),
        "continuity_confidence_summary": packet_meta.get("continuity_confidence_summary", {}),
        "orphan_block_count": int(packet_meta.get("orphan_block_count", 0) or 0),
        "orphan_block_ratio": float(packet_meta.get("orphan_block_ratio", 0.0) or 0.0),
        "semantic_attach_events": int(packet_meta.get("semantic_attach_events", 0) or 0),
        "table_continuity_events": int(packet_meta.get("table_continuity_events", 0) or 0),
    }


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
