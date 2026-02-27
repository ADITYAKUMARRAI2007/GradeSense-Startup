"""Phase 1 ingestion utilities for universal pipeline."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.layers.college.normalization import normalize_answer_pages


def ingest_pdf_pages(answer_images: List[str]) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Normalize already-rendered page images for downstream OCR.

    The upload pipeline currently converts PDFs to page images before grading.
    This phase enforces the 300-DPI normalization workflow contract.
    """
    clean_pages, metrics = normalize_answer_pages(answer_images or [])
    return clean_pages, metrics


__all__ = ["ingest_pdf_pages"]
