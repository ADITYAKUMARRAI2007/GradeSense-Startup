"""Admin routes — dashboard stats, user management, feedback, metrics."""

import uuid
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException

from app.database import db
from app.config import logger
from app.deps import get_current_user, get_admin_user, is_admin, DEFAULT_FEATURES, DEFAULT_QUOTAS
from app.models.user import User
from app.models.admin import UserFeatureFlags, UserQuotas, UserStatusUpdate, UserFeedback
from app.models.analytics import FrontendEvent
from app.utils.serialization import serialize_doc

router = APIRouter(tags=["admin"])


@router.get("/auth/check-admin")
async def check_admin_status(user: User = Depends(get_current_user)):
    """Check if current user has admin privileges"""
    return {"is_admin": is_admin(user), "email": user.email, "role": user.role}


@router.get("/admin/dashboard-stats")
async def get_dashboard_stats(user: User = Depends(get_admin_user)):
    """Get real-time dashboard statistics for admin"""
    try:
        thirty_mins_ago = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        active_sessions = await db.user_sessions.distinct(
            "user_id", {"created_at": {"$gte": thirty_mins_ago}}
        )
        active_now = len(active_sessions)

        pending_feedback = await db.user_feedback.count_documents({"status": {"$ne": "resolved"}})

        recent_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        api_metrics = await db.api_metrics.aggregate([
            {"$match": {"timestamp": {"$gte": recent_time}}},
            {"$group": {
                "_id": None,
                "total": {"$sum": 1},
                "successful": {"$sum": {"$cond": [{"$eq": ["$status_code", 200]}, 1, 0]}}
            }}
        ]).to_list(1)

        if api_metrics and api_metrics[0]["total"] > 0:
            api_health = round((api_metrics[0]["successful"] / api_metrics[0]["total"]) * 100, 1)
        else:
            api_health = 100.0

        system_status = "Healthy" if api_health >= 95 else "Degraded" if api_health >= 80 else "Issues"

        return {
            "active_now": active_now, "pending_feedback": pending_feedback,
            "api_health": api_health, "system_status": system_status
        }
    except Exception as e:
        logger.error(f"Error fetching dashboard stats: {e}")
        return {"active_now": 0, "pending_feedback": 0, "api_health": 0.0, "system_status": "Unknown"}


# ============== USER MANAGEMENT ==============

@router.get("/admin/users/{user_id}/details")
async def get_user_details(user_id: str, admin: User = Depends(get_admin_user)):
    """Get detailed user information including features and quotas"""
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0, "password": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if "feature_flags" not in user:
        user["feature_flags"] = DEFAULT_FEATURES
    if "quotas" not in user:
        user["quotas"] = DEFAULT_QUOTAS
    if "account_status" not in user:
        user["account_status"] = "active"

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    exams_this_month = await db.exams.count_documents({
        "teacher_id": user_id,
        "created_at": {"$gte": month_start.isoformat()}
    })

    papers_this_month = await db.submissions.aggregate([
        {"$lookup": {
            "from": "exams",
            "localField": "exam_id",
            "foreignField": "exam_id",
            "as": "exam"
        }},
        {"$unwind": "$exam"},
        {"$match": {
            "exam.teacher_id": user_id,
            "created_at": {"$gte": month_start.isoformat()}
        }},
        {"$count": "total"}
    ]).to_list(1)

    total_students = await db.students.count_documents({"teacher_id": user_id})
    total_batches = await db.batches.count_documents({"teacher_id": user_id})

    user["current_usage"] = {
        "exams_this_month": exams_this_month,
        "papers_this_month": papers_this_month[0]["total"] if papers_this_month else 0,
        "total_students": total_students,
        "total_batches": total_batches
    }

    return user


@router.put("/admin/users/{user_id}/features")
async def update_user_features(
    user_id: str,
    features: UserFeatureFlags,
    admin: User = Depends(get_admin_user)
):
    """Update user's feature flags"""
    result = await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"feature_flags": features.model_dump()}}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    logger.info(f"Admin {admin.email} updated features for user {user_id}")
    return {"success": True, "message": "Feature flags updated"}


@router.put("/admin/users/{user_id}/quotas")
async def update_user_quotas(
    user_id: str,
    quotas: UserQuotas,
    admin: User = Depends(get_admin_user)
):
    """Update user's usage quotas"""
    result = await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"quotas": quotas.model_dump()}}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    logger.info(f"Admin {admin.email} updated quotas for user {user_id}")
    return {"success": True, "message": "Quotas updated"}


@router.put("/admin/users/{user_id}/status")
async def update_user_status(
    user_id: str,
    status_update: UserStatusUpdate,
    admin: User = Depends(get_admin_user)
):
    """Update user account status (active/disabled/banned)"""
    if status_update.status not in ["active", "disabled", "banned"]:
        raise HTTPException(status_code=400, detail="Invalid status")

    update_data = {
        "account_status": status_update.status,
        "status_updated_at": datetime.now(timezone.utc).isoformat(),
        "status_updated_by": admin.email
    }
    if status_update.reason:
        update_data["status_reason"] = status_update.reason

    result = await db.users.update_one({"user_id": user_id}, {"$set": update_data})
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    logger.info(f"Admin {admin.email} changed user {user_id} status to {status_update.status}")
    return {"success": True, "message": f"User status updated to {status_update.status}"}


# ============== USER FEEDBACK SYSTEM ==============

@router.post("/feedback")
async def submit_user_feedback(feedback: UserFeedback, user: User = Depends(get_current_user)):
    """Submit user feedback (bug report, suggestion, or question)"""
    feedback_id = f"ufb_{uuid.uuid4().hex[:12]}"

    feedback_doc = {
        "feedback_id": feedback_id,
        "type": feedback.type,
        "data": feedback.data,
        "metadata": feedback.metadata or {},
        "user": {
            "user_id": user.user_id,
            "name": user.name,
            "email": user.email,
            "role": user.role
        },
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "resolved_at": None
    }

    await db.user_feedback.insert_one(feedback_doc)
    logger.info(f"Feedback submitted: {feedback_id} ({feedback.type}) by {user.name}")

    return {"success": True, "feedback_id": feedback_id, "message": "Feedback submitted successfully"}


@router.get("/admin/feedback")
async def get_all_feedback(user: User = Depends(get_admin_user)):
    """Get all user feedback (admin only)"""
    feedbacks = await db.user_feedback.find({}, {"_id": 0}).sort([("created_at", -1)]).to_list(1000)
    return feedbacks


@router.put("/admin/feedback/{feedback_id}/resolve")
async def resolve_feedback(feedback_id: str, user: User = Depends(get_admin_user)):
    """Mark feedback as resolved (admin only)"""
    result = await db.user_feedback.update_one(
        {"feedback_id": feedback_id},
        {"$set": {
            "status": "resolved",
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "resolved_by": {"user_id": user.user_id, "name": user.name}
        }}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Feedback not found")

    logger.info(f"Feedback resolved: {feedback_id} by {user.name}")
    return {"success": True, "message": "Feedback marked as resolved"}


# ============== METRICS & TRACKING ==============

@router.post("/metrics/track-event")
async def track_frontend_event(event: FrontendEvent, user: User = Depends(get_current_user)):
    """Track frontend user interactions for analytics"""
    try:
        await db.metrics_logs.insert_one({
            "event_id": f"evt_{uuid.uuid4().hex[:12]}",
            "event_type": event.event_type,
            "element_id": event.element_id,
            "page": event.page,
            "user_id": user.user_id,
            "role": user.role,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": event.metadata or {}
        })
        return {"success": True}
    except Exception as e:
        logger.error(f"Failed to track event: {e}")
        return {"success": False}


@router.get("/admin/users")
async def get_all_users(user: User = Depends(get_admin_user)):
    """Get all users for admin management"""
    users = await db.users.find({}, {"_id": 0, "password": 0}).sort([("created_at", -1)]).to_list(1000)
    return serialize_doc(users)


@router.get("/admin/metrics/overview")
async def get_metrics_overview(user: User = Depends(get_admin_user)):
    """Get comprehensive metrics overview for admin dashboard"""
    try:
        total_users = await db.users.count_documents({})
        total_teachers = await db.users.count_documents({"role": "teacher"})
        total_students = await db.users.count_documents({"role": "student"})

        now = datetime.now(timezone.utc)
        day_ago = (now - timedelta(days=1)).isoformat()
        week_ago = (now - timedelta(days=7)).isoformat()
        month_ago = (now - timedelta(days=30)).isoformat()

        dau = await db.metrics_logs.distinct("user_id", {"timestamp": {"$gte": day_ago}})
        wau = await db.metrics_logs.distinct("user_id", {"timestamp": {"$gte": week_ago}})
        mau = await db.metrics_logs.distinct("user_id", {"timestamp": {"$gte": month_ago}})

        new_signups = await db.users.count_documents({"created_at": {"$gte": month_ago}})

        teachers_with_multiple_exams = await db.exams.aggregate([
            {"$group": {"_id": "$teacher_id", "exam_count": {"$sum": 1}, "exams": {"$push": {"exam_id": "$exam_id", "created_at": "$created_at"}}}},
            {"$match": {"exam_count": {"$gte": 2}}}
        ]).to_list(None)

        retained_users = 0
        eligible_users = await db.users.count_documents({"role": "teacher"})

        for teacher in teachers_with_multiple_exams:
            exams = sorted(teacher["exams"], key=lambda x: x["created_at"])
            if len(exams) >= 2:
                first = datetime.fromisoformat(exams[0]["created_at"].replace('Z', '+00:00'))
                second = datetime.fromisoformat(exams[1]["created_at"].replace('Z', '+00:00'))
                days_diff = (second - first).days
                if days_diff <= 30:
                    retained_users += 1

        retention_rate = (retained_users / eligible_users * 100) if eligible_users > 0 else 0

        total_exams = await db.exams.count_documents({})
        total_papers = await db.submissions.count_documents({})

        exams_with_counts = await db.exams.aggregate([
            {"$lookup": {"from": "submissions", "localField": "exam_id", "foreignField": "exam_id", "as": "submissions"}},
            {"$project": {"submission_count": {"$size": "$submissions"}}}
        ]).to_list(None)

        avg_batch_size = sum(e["submission_count"] for e in exams_with_counts) / len(exams_with_counts) if exams_with_counts else 0

        power_users = await db.submissions.aggregate([
            {"$lookup": {"from": "exams", "localField": "exam_id", "foreignField": "exam_id", "as": "exam"}},
            {"$unwind": "$exam"},
            {"$group": {"_id": "$exam.teacher_id", "papers_graded": {"$sum": 1}}},
            {"$sort": {"papers_graded": -1}},
            {"$limit": 10},
            {"$lookup": {"from": "users", "localField": "_id", "foreignField": "user_id", "as": "teacher"}},
            {"$unwind": "$teacher"},
            {"$project": {"teacher_id": "$_id", "teacher_name": "$teacher.name", "papers_graded": 1, "_id": 0}}
        ]).to_list(10)

        grading_modes = await db.exams.aggregate([
            {"$group": {"_id": "$grading_mode", "count": {"$sum": 1}}}
        ]).to_list(None)

        grading_time_stats = await db.grading_analytics.aggregate([
            {"$group": {"_id": None, "avg_grading_time": {"$avg": "$grading_duration_seconds"}}}
        ]).to_list(1)
        avg_grading_time = grading_time_stats[0]["avg_grading_time"] if grading_time_stats else 0

        day_ago_errors = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        error_breakdown = await db.api_metrics.aggregate([
            {"$match": {"timestamp": {"$gte": day_ago_errors}, "status_code": {"$ne": 200}, "error_type": {"$ne": None}}},
            {"$group": {"_id": "$error_type", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10}
        ]).to_list(10)

        geo_distribution = await db.metrics_logs.aggregate([
            {"$group": {"_id": "$country", "users": {"$addToSet": "$user_id"}}},
            {"$project": {"country": "$_id", "user_count": {"$size": "$users"}, "_id": 0}},
            {"$sort": {"user_count": -1}},
            {"$limit": 10}
        ]).to_list(10)

        if not geo_distribution:
            geo_distribution = [{"country": "Unknown", "user_count": total_users}]

        ai_metrics = await db.grading_analytics.aggregate([
            {"$group": {
                "_id": None,
                "avg_confidence": {"$avg": "$ai_confidence_score"},
                "avg_grade_delta": {"$avg": "$grade_delta"},
                "total_graded": {"$sum": 1},
                "edited_count": {"$sum": {"$cond": ["$edited_by_teacher", 1, 0]}},
                "zero_touch_count": {"$sum": {"$cond": [{"$eq": ["$edited_by_teacher", False]}, 1, 0]}}
            }}
        ]).to_list(1)

        ai_stats = ai_metrics[0] if ai_metrics else {
            "avg_confidence": 0, "avg_grade_delta": 0, "total_graded": 0,
            "edited_count": 0, "zero_touch_count": 0
        }

        human_intervention_rate = (ai_stats["edited_count"] / ai_stats["total_graded"] * 100) if ai_stats["total_graded"] > 0 else 0
        zero_touch_rate = (ai_stats["zero_touch_count"] / ai_stats["total_graded"] * 100) if ai_stats["total_graded"] > 0 else 0

        avg_response_time = await db.api_metrics.aggregate([
            {"$group": {"_id": None, "avg_time": {"$avg": "$response_time_ms"}}}
        ]).to_list(1)

        success_rate_data = await db.api_metrics.aggregate([
            {"$group": {"_id": None, "total": {"$sum": 1}, "successful": {"$sum": {"$cond": [{"$eq": ["$status_code", 200]}, 1, 0]}}}}
        ]).to_list(1)

        success_rate = (success_rate_data[0]["successful"] / success_rate_data[0]["total"] * 100) if success_rate_data and success_rate_data[0]["total"] > 0 else 0

        cost_metrics = await db.grading_analytics.aggregate([
            {"$group": {
                "_id": None,
                "total_cost": {"$sum": "$estimated_cost"},
                "avg_cost_per_paper": {"$avg": "$estimated_cost"},
                "total_tokens_input": {"$sum": "$tokens_input"},
                "total_tokens_output": {"$sum": "$tokens_output"}
            }}
        ]).to_list(1)

        cost_stats = cost_metrics[0] if cost_metrics else {
            "total_cost": 0, "avg_cost_per_paper": 0,
            "total_tokens_input": 0, "total_tokens_output": 0
        }

        return {
            "business_metrics": {
                "total_users": total_users, "total_teachers": total_teachers,
                "total_students": total_students, "dau": len(dau), "wau": len(wau),
                "mau": len(mau), "new_signups_30d": new_signups,
                "retention_rate": round(retention_rate, 1)
            },
            "engagement_metrics": {
                "total_exams": total_exams, "total_papers": total_papers,
                "avg_batch_size": round(avg_batch_size, 1), "power_users": power_users,
                "grading_mode_distribution": grading_modes,
                "avg_grading_time_seconds": round(avg_grading_time, 1)
            },
            "ai_trust_metrics": {
                "avg_confidence": round(ai_stats["avg_confidence"], 1),
                "avg_grade_delta": round(ai_stats["avg_grade_delta"], 2),
                "human_intervention_rate": round(human_intervention_rate, 1),
                "zero_touch_rate": round(zero_touch_rate, 1),
                "total_graded": ai_stats["total_graded"]
            },
            "system_performance": {
                "avg_response_time_ms": round(avg_response_time[0]["avg_time"], 0) if avg_response_time else 0,
                "api_success_rate": round(success_rate, 1),
                "error_breakdown": error_breakdown
            },
            "unit_economics": {
                "total_cost_usd": round(cost_stats["total_cost"], 2),
                "avg_cost_per_paper_usd": round(cost_stats["avg_cost_per_paper"], 4),
                "total_tokens_input": cost_stats["total_tokens_input"],
                "total_tokens_output": cost_stats["total_tokens_output"]
            },
            "geographic_distribution": geo_distribution
        }
    except Exception as e:
        logger.error(f"Error fetching metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
