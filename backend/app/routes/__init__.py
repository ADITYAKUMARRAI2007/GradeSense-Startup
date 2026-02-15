"""API route registration."""

from fastapi import APIRouter
from .auth import router as auth_router
from .batches import router as batches_router
from .subjects import router as subjects_router
from .students import router as students_router
from .exams import router as exams_router
from .uploads import router as uploads_router
from .grading import router as grading_router
from .submissions import router as submissions_router
from .re_evaluations import router as re_evaluations_router
from .feedback import router as feedback_router
from .analytics import router as analytics_router
from .student_portal import router as student_portal_router
from .notifications import router as notifications_router
from .search import router as search_router
from .admin import router as admin_router
from .debug import router as debug_router


def register_all_routes(api_router: APIRouter):
    """Include all route modules on the main API router."""
    api_router.include_router(auth_router)
    api_router.include_router(batches_router)
    api_router.include_router(subjects_router)
    api_router.include_router(students_router)
    api_router.include_router(exams_router)
    api_router.include_router(uploads_router)
    api_router.include_router(grading_router)
    api_router.include_router(submissions_router)
    api_router.include_router(re_evaluations_router)
    api_router.include_router(feedback_router)
    api_router.include_router(analytics_router)
    api_router.include_router(student_portal_router)
    api_router.include_router(notifications_router)
    api_router.include_router(search_router)
    api_router.include_router(admin_router)
    api_router.include_router(debug_router)
