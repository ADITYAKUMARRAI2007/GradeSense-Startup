"""Vision-only OCR for college_v3 (DOCUMENT_TEXT_DETECTION)."""

from __future__ import annotations

from typing import Dict, List, Any

from app.config import logger
from app.utils.vision_ocr_service import get_vision_service


def _to_bbox(item: Dict[str, Any]) -> List[float]:
    return [
        float(item.get("x1", 0.0)),
        float(item.get("y1", 0.0)),
        float(item.get("x2", 0.0)),
        float(item.get("y2", 0.0)),
    ]


def ocr_pages(images: List[str]) -> List[Dict[str, Any]]:
    """OCR a list of base64 images using Vision DOCUMENT_TEXT_DETECTION."""
    vision = get_vision_service()
    pages: List[Dict[str, Any]] = []
    for idx, img_b64 in enumerate(images, start=1):
        if not img_b64:
            pages.append(
                {
                    "page_index": idx,
                    "full_text": "",
                    "blocks": [],
                    "paragraphs": [],
                    "word_boxes": [],
                }
            )
            continue
        res = vision.detect_text_from_base64(
            image_base64=img_b64,
            languages=["en"],
            mode="document",
            handwriting=True,
            min_confidence=0.2,
        )
        words = res.get("words", []) or []
        lines = res.get("lines", []) or []
        full_text = "\n".join((l.get("text") or "").strip() for l in lines if (l.get("text") or "").strip()).strip()
        blocks = [
            {
                "text": l.get("text", ""),
                "bbox": _to_bbox(l),
                "confidence": float(l.get("confidence", l.get("conf", 0.0)) or 0.0),
                "page": idx,
            }
            for l in lines
        ]
        paragraphs = [
            {
                "text": l.get("text", ""),
                "bbox": _to_bbox(l),
                "confidence": float(l.get("confidence", l.get("conf", 0.0)) or 0.0),
                "page": idx,
            }
            for l in lines
        ]
        word_boxes = [
            {
                "text": w.get("text", ""),
                "bbox": _to_bbox(w),
                "confidence": float(w.get("confidence", w.get("conf", 0.0)) or 0.0),
                "page": idx,
            }
            for w in words
        ]
        pages.append(
            {
                "page_index": idx,
                "full_text": full_text,
                "blocks": blocks,
                "paragraphs": paragraphs,
                "word_boxes": word_boxes,
            }
        )
    logger.info("[COLLEGE-V3][OCR] completed pages=%s", len(pages))
    return pages

