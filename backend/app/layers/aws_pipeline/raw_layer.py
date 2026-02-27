"""Immutable raw extraction layer for Textract outputs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import logger
from app.database import db

from .s3_storage import build_raw_layer_key, upload_json_to_s3, download_json_from_s3


async def save_raw_textract_layer(
    *,
    exam_id: str,
    blocks: List[Dict[str, Any]],
    page_texts: List[Dict[str, Any]],
    tables: Dict[int, Any],
    anchors: List[Dict[str, Any]],
    line_positions: List[Dict[str, Any]],
    textract_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist immutable raw layer. Write-once: never overwrite existing raw layer."""
    exam = await db.exams.find_one({"exam_id": exam_id}, {"_id": 0, "raw_layer_ref": 1, "raw_layer_version": 1})
    if exam and exam.get("raw_layer_ref"):
        logger.info("[AWS][RAW] Raw layer already exists for %s; skipping overwrite", exam_id)
        return {"raw_layer_ref": exam.get("raw_layer_ref"), "skipped": True}

    payload = {
        "raw_textract_blocks": blocks,
        "raw_page_text": page_texts,
        "raw_tables": tables,
        "raw_anchor_candidates": anchors,
        "raw_line_positions": line_positions,
        "textract_job_id": textract_job_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    key = build_raw_layer_key(exam_id)
    raw_uri = upload_json_to_s3(key=key, payload=payload)

    await db.exams.update_one(
        {"exam_id": exam_id},
        {"$set": {"raw_layer_ref": raw_uri, "raw_layer_version": int((exam or {}).get("raw_layer_version") or 0) or 1}},
    )
    logger.info("RAW_LAYER_SAVED exam_id=%s uri=%s", exam_id, raw_uri)
    return {"raw_layer_ref": raw_uri, "skipped": False}


async def load_raw_textract_layer(exam_id: str) -> Dict[str, Any]:
    """Load raw layer JSON from S3 for an exam."""
    exam = await db.exams.find_one({"exam_id": exam_id}, {"_id": 0, "raw_layer_ref": 1})
    if not exam or not exam.get("raw_layer_ref"):
        return {}
    uri = exam.get("raw_layer_ref")
    return download_json_from_s3(uri)

