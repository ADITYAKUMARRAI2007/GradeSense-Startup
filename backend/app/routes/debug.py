"""Debug and maintenance routes."""

from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timezone, timedelta
import os

from app.database import db
from app.deps import get_current_user
from app.models.user import User
from app.config import logger

router = APIRouter(tags=["debug"])


@router.post("/debug/force-reextract/{exam_id}")
async def force_reextract_questions(exam_id: str, user: User = Depends(get_current_user)):
    """Force complete re-extraction of ALL questions - deletes old and extracts fresh."""
    from app.services.extraction import auto_extract_questions
    try:
        exam = await db.exams.find_one({"exam_id": exam_id}, {"_id": 0})
        if not exam:
            raise HTTPException(status_code=404, detail="Exam not found")
        
        delete_result = await db.questions.delete_many({"exam_id": exam_id})
        print(f"\n{'='*70}")
        print(f"[FORCE-REEXTRACT] Deleted {delete_result.deleted_count} old questions for {exam_id}")
        
        await db.exams.update_one(
            {"exam_id": exam_id},
            {"$set": {"questions": [], "questions_count": 0, "extraction_source": None, "question_extraction_status": "pending"}}
        )
        
        result = await auto_extract_questions(exam_id, force=True)
        print(f"[FORCE-REEXTRACT] Extraction complete: {result}")
        print(f"{'='*70}\n")
        
        return {
            "success": result.get("success", False),
            "message": result.get("message", ""),
            "deleted_count": delete_result.deleted_count,
            "extracted_count": result.get("count", 0),
            "questions": result.get("count", 0)
        }
    except Exception as e:
        logger.error(f"Force reextraction error: {e}")
        return {"success": False, "message": str(e)}


@router.get("/debug/exam-questions/{exam_id}")
async def debug_exam_questions(exam_id: str, user: User = Depends(get_current_user)):
    """Debug endpoint to see ALL questions in database for this exam."""
    try:
        db_questions = await db.questions.find({"exam_id": exam_id}, {"_id": 0}).to_list(1000)
        exam = await db.exams.find_one({"exam_id": exam_id}, {"_id": 0, "questions": 1})
        exam_questions = exam.get("questions", []) if exam else []
        
        db_q_numbers = [q.get("question_number") for q in db_questions]
        exam_q_numbers = [q.get("question_number") for q in exam_questions]
        
        return {
            "exam_id": exam_id,
            "database_count": len(db_questions),
            "database_questions": db_q_numbers,
            "database_details": db_questions,
            "exam_count": len(exam_questions),
            "exam_questions": exam_q_numbers,
            "exam_details": exam_questions
        }
    except Exception as e:
        logger.error(f"Debug questions error: {e}")
        return {"error": str(e)}


@router.post("/debug/cleanup")
async def debug_cleanup():
    """EMERGENCY CLEANUP: Cancel all stuck jobs and tasks."""
    try:
        jobs_result = await db.grading_jobs.update_many(
            {"status": {"$in": ["processing", "pending"]}},
            {"$set": {"status": "failed", "error": "Emergency cleanup - manually cancelled", "updated_at": datetime.now(timezone.utc).isoformat()}}
        )
        tasks_result = await db.tasks.update_many(
            {"status": {"$in": ["pending", "processing", "claimed"]}},
            {"$set": {"status": "cancelled"}}
        )
        return {
            "success": True,
            "jobs_cancelled": jobs_result.modified_count,
            "tasks_cancelled": tasks_result.modified_count,
            "message": f"Cleaned up {jobs_result.modified_count} jobs and {tasks_result.modified_count} tasks"
        }
    except Exception as e:
        logger.error(f"Cleanup error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/debug/status")
async def debug_status():
    """Debug endpoint to check worker status, database connectivity, and job queue."""
    debug_info = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "db_name": os.environ.get('DB_NAME', 'NOT_SET'),
            "mongo_url_configured": "MONGO_URL" in os.environ,
            "worker_integrated": True,
        },
        "database": {"connection": "Unknown", "collections": []},
        "jobs": {"pending": 0, "processing": 0, "completed_last_hour": 0, "failed_last_hour": 0, "recent_jobs": []},
        "tasks": {"pending": 0, "processing": 0, "recent_tasks": []}
    }
    
    try:
        await db.command("ping")
        debug_info["database"]["connection"] = "Connected ✅"
        collections = await db.list_collection_names()
        debug_info["database"]["collections"] = collections[:10]
        
        one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        debug_info["jobs"]["pending"] = await db.grading_jobs.count_documents({"status": "pending"})
        debug_info["jobs"]["processing"] = await db.grading_jobs.count_documents({"status": "processing"})
        debug_info["jobs"]["completed_last_hour"] = await db.grading_jobs.count_documents({"status": "completed", "updated_at": {"$gte": one_hour_ago}})
        debug_info["jobs"]["failed_last_hour"] = await db.grading_jobs.count_documents({"status": "failed", "updated_at": {"$gte": one_hour_ago}})
        
        recent_jobs = await db.grading_jobs.find({}, {"_id": 0, "job_id": 1, "status": 1, "total_papers": 1, "processed_papers": 1, "created_at": 1}).sort([("created_at", -1)]).limit(5).to_list(5)
        debug_info["jobs"]["recent_jobs"] = [{"job_id": j.get("job_id"), "status": j.get("status"), "progress": f"{j.get('processed_papers', 0)}/{j.get('total_papers', 0)}"} for j in recent_jobs]
        
        debug_info["tasks"]["pending"] = await db.tasks.count_documents({"status": "pending"})
        debug_info["tasks"]["processing"] = await db.tasks.count_documents({"status": "processing"})
        
    except Exception as e:
        debug_info["error"] = f"Error: {str(e)}"
    
    return debug_info
