"""Answer sheet extraction using AWS Textract async."""

from __future__ import annotations

from typing import Any, Dict, List

from app.config import logger

from .s3_storage import upload_pdf_to_s3
from .textract_client import start_document_analysis, poll_document_analysis
from .text_reconstruction import rebuild_page_text, detect_anchors


def extract_answer_pages(*, exam_id: str, pdf_bytes: bytes) -> Dict[str, Any]:
    if not pdf_bytes:
        return {"status": "failed", "reason": "no_pdf_bytes", "answer_pages": []}

    s3_info = upload_pdf_to_s3(exam_id=exam_id, pdf_bytes=pdf_bytes, prefix="textract/answers")
    job_id = start_document_analysis(bucket=s3_info["bucket"], key=s3_info["key"])
    resp = poll_document_analysis(job_id)
    if resp.get("status") not in ("SUCCEEDED", "PARTIAL_SUCCESS"):
        return {"status": "failed", "reason": resp.get("error") or "textract_failed", "answer_pages": []}

    blocks = resp.get("blocks") or []
    rebuild = rebuild_page_text(blocks)
    page_texts = rebuild.get("page_texts", [])
    anchors = detect_anchors(page_texts, rebuild.get("line_positions", []))

    logger.info("[AWS][Answer] pages=%s anchors=%s", len(page_texts), len(anchors))
    return {
        "status": "ok",
        "answer_pages": page_texts,
        "answer_anchors": anchors,
        "textract_job_id": job_id,
    }
