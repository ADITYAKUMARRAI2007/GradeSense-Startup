"""Notification routes."""

from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timezone

from app.database import db
from app.deps import get_current_user
from app.models.user import User

router = APIRouter(tags=["notifications"])


@router.get("/notifications")
async def get_notifications(user: User = Depends(get_current_user)):
    """Get user's notifications"""
    notifications = await db.notifications.find(
        {"user_id": user.user_id},
        {"_id": 0}
    ).sort("created_at", -1).limit(50).to_list(50)

    unread_count = await db.notifications.count_documents({
        "user_id": user.user_id,
        "is_read": False
    })

    return {
        "notifications": notifications,
        "unread_count": unread_count
    }


@router.put("/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: str, user: User = Depends(get_current_user)):
    """Mark notification as read"""
    result = await db.notifications.update_one(
        {"notification_id": notification_id, "user_id": user.user_id},
        {"$set": {"is_read": True, "read_at": datetime.now(timezone.utc).isoformat()}}
    )

    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Notification not found")

    return {"message": "Notification marked as read"}


@router.put("/notifications/mark-all-read")
async def mark_all_notifications_read(user: User = Depends(get_current_user)):
    """Mark all notifications as read"""
    result = await db.notifications.update_many(
        {"user_id": user.user_id, "is_read": False},
        {"$set": {"is_read": True, "read_at": datetime.now(timezone.utc).isoformat()}}
    )

    return {
        "message": "All notifications marked as read",
        "count": result.modified_count
    }


@router.delete("/notifications/clear-all")
async def clear_all_notifications(user: User = Depends(get_current_user)):
    """Clear (delete) all notifications"""
    result = await db.notifications.delete_many({"user_id": user.user_id})

    return {
        "message": "All notifications cleared",
        "count": result.deleted_count
    }


@router.delete("/notifications/{notification_id}")
async def delete_notification(notification_id: str, user: User = Depends(get_current_user)):
    """Delete a specific notification"""
    result = await db.notifications.delete_one(
        {"notification_id": notification_id, "user_id": user.user_id}
    )

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Notification not found")

    return {"message": "Notification deleted"}
