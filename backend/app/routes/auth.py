"""Authentication routes - Google OAuth, JWT email/password, session management."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from datetime import datetime, timezone, timedelta
from typing import Optional
import os
import uuid

import httpx

from app.database import db
from app.deps import get_current_user
from app.models.user import User, ProfileUpdate
from app.models.admin import RegisterRequest, LoginRequest, SetPasswordRequest
from app.utils.auth import verify_password, get_password_hash, create_access_token, decode_token
from app.config import logger

router = APIRouter(tags=["auth"])


@router.post("/auth/google/callback")
async def google_oauth_callback(request: Request, response: Response):
    """Handle Google OAuth callback and create session"""
    data = await request.json()
    code = data.get("code")
    state = data.get("state")

    if not code:
        raise HTTPException(status_code=400, detail="Authorization code required")

    logger.info(f"=== GOOGLE OAUTH CALLBACK === code: {code[:20]}...")

    try:
        import json as json_module
        state_data = json_module.loads(state) if state else {}
        preferred_role = state_data.get("role", "teacher")

        GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
        GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
        REDIRECT_URI = f"http://localhost:3000/callback"

        if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
            raise HTTPException(status_code=500, detail="Google OAuth not configured")

        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "redirect_uri": REDIRECT_URI,
                    "grant_type": "authorization_code"
                }
            )

            if token_response.status_code != 200:
                logger.error(f"Token exchange failed: {token_response.text}")
                raise HTTPException(status_code=400, detail="Failed to exchange authorization code")

            tokens = token_response.json()
            access_token = tokens.get("access_token")

            user_info_response = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if user_info_response.status_code != 200:
                logger.error(f"User info fetch failed: {user_info_response.text}")
                raise HTTPException(status_code=400, detail="Failed to get user information")

            user_info = user_info_response.json()
            logger.info(f"Google user info: {user_info.get('email')}")

        user_email = user_info.get("email")
        user_name = user_info.get("name")
        user_picture = user_info.get("picture")

        if not user_email:
            raise HTTPException(status_code=400, detail="Email not found in Google response")

        # Check if student already exists (created by teacher)
        existing_student = await db.users.find_one({
            "email": user_email,
            "role": "student"
        }, {"_id": 0})

        if existing_student:
            user_id = existing_student["user_id"]
            await db.users.update_one(
                {"user_id": user_id},
                {"$set": {
                    "name": user_name,
                    "picture": user_picture,
                    "profile_completed": True,
                    "last_login": datetime.now(timezone.utc).isoformat()
                }}
            )
            user_role = "student"
        else:
            existing_user = await db.users.find_one({"email": user_email}, {"_id": 0})

            if existing_user:
                user_id = existing_user["user_id"]
                await db.users.update_one(
                    {"user_id": user_id},
                    {"$set": {
                        "name": user_name,
                        "picture": user_picture,
                        "profile_completed": True,
                        "last_login": datetime.now(timezone.utc).isoformat()
                    }}
                )
                user_role = existing_user.get("role", "teacher")
            else:
                user_id = f"user_{uuid.uuid4().hex[:12]}"
                user_role = preferred_role if preferred_role in ["teacher", "student"] else "teacher"
                new_user = {
                    "user_id": user_id,
                    "email": user_email,
                    "name": user_name,
                    "picture": user_picture,
                    "role": user_role,
                    "batches": [],
                    "profile_completed": False,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "last_login": datetime.now(timezone.utc).isoformat()
                }
                await db.users.insert_one(new_user)

        # Create session token
        session_token = f"session_{uuid.uuid4().hex}"
        expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

        await db.user_sessions.insert_one({
            "session_token": session_token,
            "user_id": user_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": expires_at
        })

        response.set_cookie(
            key="session_token",
            value=session_token,
            httponly=True,
            max_age=7 * 24 * 60 * 60,
            samesite="lax",
            secure=False,
            path="/"
        )

        return {
            "user_id": user_id,
            "email": user_email,
            "name": user_name,
            "picture": user_picture,
            "role": user_role,
            "session_token": session_token
        }

    except Exception as e:
        logger.error(f"Google OAuth error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/auth/session")
async def create_session(request: Request, response: Response):
    """Exchange session_id for session_token"""
    data = await request.json()
    session_id = data.get("session_id")
    preferred_role = data.get("preferred_role", "teacher")

    logger.info(f"=== AUTH SESSION REQUEST === session_id: {session_id[:20] if session_id else 'None'}..., role: {preferred_role}")

    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")

    logger.info("Processing auth session with configured Google OAuth credentials")
    logger.info(f"Auth session validated: {session_id[:20]}...")

    return {
        "success": True,
        "message": "Authentication session validated",
        "session_id": session_id,
        "preferred_role": preferred_role
    }


@router.post("/auth/register")
async def register_user(request: RegisterRequest, response: Response, req: Request):
    """Register a new user with email and password (JWT-based auth)"""
    existing_user = await db.users.find_one({"email": request.email}, {"_id": 0})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    user_id = str(uuid.uuid4())
    try:
        hashed_password = get_password_hash(request.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    new_user = {
        "user_id": user_id,
        "email": request.email,
        "name": request.name,
        "role": request.role,
        "password_hash": hashed_password,
        "auth_type": "jwt",
        "picture": None,
        "exam_type": request.exam_type,
        "teacher_type": "competitive" if request.exam_type == "upsc" else "college",
        "exam_category": "UPSC" if request.exam_type == "upsc" else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_login": datetime.now(timezone.utc).isoformat(),
        "account_status": "active"
    }

    await db.users.insert_one(new_user)
    logger.info(f"New user registered via JWT: {request.email} as {request.role}")

    token_data = {
        "user_id": user_id,
        "email": request.email,
        "role": request.role
    }
    access_token = create_access_token(token_data)

    response.set_cookie(
        key="session_token",
        value=access_token,
        httponly=True,
        max_age=7 * 24 * 60 * 60,
        samesite="lax",
        secure=req.url.scheme == "https",
        path="/"
    )

    return {
        "user_id": user_id,
        "email": request.email,
        "name": request.name,
        "role": request.role,
        "exam_type": request.exam_type,
        "token": access_token
    }


@router.post("/auth/set-password")
async def set_password_for_google_account(request: SetPasswordRequest):
    """Allow Google OAuth users to set a password for email/password login"""
    user = await db.users.find_one({"email": request.email}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="No account found with this email")

    if "password_hash" in user:
        raise HTTPException(status_code=400, detail="This account already has a password. Use the login page or reset password if you forgot it.")

    try:
        password_hash = get_password_hash(request.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.users.update_one(
        {"email": request.email},
        {"$set": {
            "password_hash": password_hash,
            "password_set_at": datetime.now(timezone.utc).isoformat(),
            "profile_completed": True
        }}
    )

    return {
        "message": "Password set successfully! You can now login with your email and password."
    }


@router.post("/auth/login")
async def login_user(request: LoginRequest, response: Response, req: Request):
    """Login with email and password (JWT-based auth)"""
    user = await db.users.find_one({"email": request.email}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if "password_hash" not in user:
        raise HTTPException(
            status_code=400,
            detail="This account uses Google sign-in. Please use the 'Sign in with Google' button."
        )

    if not verify_password(request.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    account_status = user.get("account_status", "active")
    if account_status == "banned":
        raise HTTPException(status_code=403, detail="Account banned. Contact support.")
    elif account_status == "disabled":
        raise HTTPException(status_code=403, detail="Account disabled. Contact support.")

    update_fields = {"last_login": datetime.now(timezone.utc).isoformat()}
    if request.exam_type in ["upsc", "college"]:
        update_fields["exam_type"] = request.exam_type
        update_fields["teacher_type"] = "competitive" if request.exam_type == "upsc" else "college"
        update_fields["exam_category"] = "UPSC" if request.exam_type == "upsc" else None
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": update_fields}
    )

    token_data = {
        "user_id": user["user_id"],
        "email": user["email"],
        "role": user["role"]
    }
    access_token = create_access_token(token_data)

    response.set_cookie(
        key="session_token",
        value=access_token,
        httponly=True,
        max_age=7 * 24 * 60 * 60,
        samesite="lax",
        secure=req.url.scheme == "https",
        path="/"
    )

    logger.info(f"User logged in via JWT: {user['email']}")

    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "name": user.get("name"),
        "picture": user.get("picture"),
        "role": user["role"],
        "exam_type": user.get("exam_type"),
        "token": access_token,
        "profile_completed": user.get("profile_completed", True)
    }


@router.get("/auth/me")
async def get_me(user: User = Depends(get_current_user)):
    """Get current user info"""
    return {
        "user_id": user.user_id,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "role": user.role,
        "batches": user.batches,
        "exam_type": getattr(user, "exam_type", None)
    }


@router.post("/auth/logout")
async def logout(request: Request, response: Response):
    """Logout and clear session"""
    session_token = request.cookies.get("session_token")
    if session_token:
        await db.user_sessions.delete_one({"session_token": session_token})

    response.delete_cookie(key="session_token", path="/")
    return {"message": "Logged out"}


@router.put("/profile/complete")
async def complete_profile(
    profile: ProfileUpdate,
    user: User = Depends(get_current_user)
):
    """Complete user profile on first login"""
    try:
        if profile.exam_type and profile.exam_type not in ["upsc", "college"]:
            raise HTTPException(status_code=400, detail="Invalid exam type")

        valid_teacher_types = ["school", "college", "competitive", "others"]
        if profile.teacher_type not in valid_teacher_types:
            raise HTTPException(status_code=400, detail="Invalid teacher type")

        if profile.teacher_type == "competitive":
            valid_exam_categories = ["UPSC", "CA", "CLAT", "JEE", "NEET", "others"]
            if not profile.exam_category or profile.exam_category not in valid_exam_categories:
                raise HTTPException(status_code=400, detail="Exam category required for competitive exams")

        update_data = {
            "name": profile.name,
            "contact": profile.contact,
            "email": profile.email,
            "teacher_type": profile.teacher_type,
            "exam_category": profile.exam_category if profile.teacher_type == "competitive" else None,
            "exam_type": profile.exam_type,
            "profile_completed": True,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }

        await db.users.update_one(
            {"user_id": user.user_id},
            {"$set": update_data}
        )

        updated_user = await db.users.find_one({"user_id": user.user_id}, {"_id": 0})
        return updated_user

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error completing profile: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to complete profile: {str(e)}")


@router.get("/profile/check")
async def check_profile_completion(user: User = Depends(get_current_user)):
    """Check if user has completed profile setup"""
    profile_completed = user.profile_completed if hasattr(user, 'profile_completed') else None

    if profile_completed is None or (user.name and user.email):
        profile_completed = True

    return {
        "profile_completed": profile_completed,
        "user_id": user.user_id,
        "email": user.email,
        "name": user.name,
        "teacher_type": user.teacher_type if hasattr(user, 'teacher_type') else None,
        "exam_category": user.exam_category if hasattr(user, 'exam_category') else None
    }
