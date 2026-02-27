"""Universal pipeline namespace routes.

These endpoints provide an explicit Universal V2 API surface while preserving the
existing exam/submission endpoints. They delegate to existing hardened handlers
that are now universal-aware via feature flags.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.deps import get_current_user
from app.models.user import User
from app.routes.debug import (
    debug_grading_audit as _debug_grading_audit,
    debug_ocr_structure as _debug_ocr_structure,
    debug_packet_pipeline as _debug_packet_pipeline,
)
from app.routes.exams import get_blueprint_health as _get_blueprint_health
from app.routes.grading import grade_papers_background as _grade_papers_background
from app.routes.submissions import preflight_submission_mapping as _preflight_submission_mapping

router = APIRouter(prefix="/universal", tags=["universal"])


@router.post("/upload-answer-pdf")
async def upload_answer_pdf_universal(
    exam_id: str = Form(...),
    files: List[UploadFile] = File(...),
    user: User = Depends(get_current_user),
):
    """Universal alias to start background grading from uploaded answer PDFs."""
    return await _grade_papers_background(exam_id=exam_id, files=files, user=user)


@router.post("/preflight-map")
async def preflight_map_universal(
    submission_id: str = Form(...),
    user: User = Depends(get_current_user),
):
    """Universal alias for packet/alignment preflight diagnostics."""
    return await _preflight_submission_mapping(submission_id=submission_id, user=user)


@router.post("/grade")
async def grade_universal(
    exam_id: str = Form(...),
    files: List[UploadFile] = File(...),
    user: User = Depends(get_current_user),
):
    """Universal alias to run grading background job with V2 routing."""
    return await _grade_papers_background(exam_id=exam_id, files=files, user=user)


@router.get("/blueprint-health")
async def blueprint_health_universal(
    exam_id: str,
    user: User = Depends(get_current_user),
):
    """Universal alias for blueprint health diagnostics."""
    return await _get_blueprint_health(exam_id=exam_id, user=user)


@router.get("/debug/ocr-structure")
async def ocr_structure_universal(
    submission_id: str,
    user: User = Depends(get_current_user),
):
    """Universal alias for OCR and structure inspection."""
    return await _debug_ocr_structure(submission_id=submission_id, user=user)


@router.get("/debug/packet-pipeline")
async def packet_pipeline_universal(
    submission_id: str,
    user: User = Depends(get_current_user),
):
    """Universal alias for packet pipeline debug with continuity traces."""
    return await _debug_packet_pipeline(submission_id=submission_id, user=user)


@router.get("/debug/grading-audit/{submission_id}")
async def grading_audit_universal(
    submission_id: str,
    user: User = Depends(get_current_user),
):
    """Universal alias for grading audit diagnostics."""
    return await _debug_grading_audit(submission_id=submission_id, user=user)


__all__ = ["router"]
