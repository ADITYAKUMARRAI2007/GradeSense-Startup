"""Phase 2 OCR extraction for universal pipeline."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.layers.college.layout import detect_page_blocks
from app.layers.college.region_ocr import extract_region_text


def extract_ocr_blocks(clean_pages: List[str]) -> Tuple[List[List[Dict[str, Any]]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return layout blocks, region OCR output, and layout recovery flags."""
    page_layout, layout_flags = detect_page_blocks(clean_pages or [])
    region_text = extract_region_text(clean_pages or [], page_layout)
    return page_layout, region_text, layout_flags


__all__ = ["extract_ocr_blocks"]
