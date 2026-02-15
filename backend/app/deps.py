"""
FastAPI dependencies - get_current_user, get_admin_user, etc.
"""

from fastapi import Request, HTTPException, Depends
from datetime import datetime, timezone

from .database import db
from .models.user import User
from .utils.auth import decode_token


# Admin whitelist
ADMIN_WHITELIST = [
    "gradingtoolaibased@gmail.com",
    # Add more admin emails here
]

# Default feature flags and quotas
DEFAULT_FEATURES = {
    "ai_suggestions": True,
    "sub_questions": True,
    "bulk_upload": True,
    "analytics": True,
    "peer_comparison": True,
    "export_data": True
}

DEFAULT_QUOTAS = {
    "max_exams_per_month": 100,
    "max_papers_per_month": 1000,
    "max_students": 500,
    "max_batches": 50
}


async def get_current_user(request: Request) -> User:
    """Get current user from session token (supports both OAuth sessions and JWT tokens)"""
    session_token = request.cookies.get("session_token")

    if not session_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            session_token = auth_header.split(" ")[1]

    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Try to decode as JWT first
    jwt_payload = decode_token(session_token)
    if jwt_payload:
        user_id = jwt_payload.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")

        user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        account_status = user.get("account_status", "active")
        if account_status == "banned":
            raise HTTPException(status_code=403, detail="Account banned. Contact support.")
        elif account_status == "disabled":
            raise HTTPException(status_code=403, detail="Account disabled. Contact support.")

        return User(
            user_id=user["user_id"],
            email=user["email"],
            name=user["name"],
            role=user["role"],
            picture=user.get("picture")
        )

    # Fallback to session-based auth (OAuth)
    session = await db.user_sessions.find_one(
        {"session_token": session_token},
        {"_id": 0}
    )

    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    expires_at = session.get("expires_at")
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Session expired")

    user = await db.users.find_one(
        {"user_id": session["user_id"]},
        {"_id": 0}
    )

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    account_status = user.get("account_status", "active")
    if account_status == "banned":
        raise HTTPException(
            status_code=403,
            detail="Your account has been banned. Contact support for assistance."
        )
    elif account_status == "disabled":
        raise HTTPException(
            status_code=403,
            detail="Your account has been temporarily disabled. Contact support for assistance."
        )

    # Update last_login timestamp (throttled - only update if more than 5 minutes since last update)
    last_login = user.get("last_login")
    should_update = False

    if not last_login:
        should_update = True
    else:
        try:
            if isinstance(last_login, str):
                last_login_dt = datetime.fromisoformat(last_login.replace('Z', '+00:00'))
            else:
                last_login_dt = last_login

            if last_login_dt.tzinfo is None:
                last_login_dt = last_login_dt.replace(tzinfo=timezone.utc)

            time_since_last_update = datetime.now(timezone.utc) - last_login_dt
            if time_since_last_update.total_seconds() > 300:  # 5 minutes
                should_update = True
        except:
            should_update = True

    if should_update:
        await db.users.update_one(
            {"user_id": user["user_id"]},
            {"$set": {"last_login": datetime.now(timezone.utc).isoformat()}}
        )
        user["last_login"] = datetime.now(timezone.utc).isoformat()

    return User(**user)


def is_admin(user: User) -> bool:
    """Check if user has admin privileges"""
    return user.email in ADMIN_WHITELIST or user.role == "admin"


async def get_admin_user(user: User = Depends(get_current_user)) -> User:
    """Dependency to ensure user has admin privileges"""
    if not is_admin(user):
        raise HTTPException(
            status_code=403,
            detail="Admin access required. Contact support if you need admin privileges."
        )
    return user
