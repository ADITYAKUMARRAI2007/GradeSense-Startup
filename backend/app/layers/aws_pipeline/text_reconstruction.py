"""Reconstruct ordered text from Textract blocks and detect anchors."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from app.config import logger

SECTION_MARKERS = (
    "section",
    "part",
    "very short answer",
    "short answer",
    "long answer",
    "case study",
    "internal choice",
)

QUESTION_PATTERNS = [
    re.compile(r"^\s*Q\s*(\d+)", re.IGNORECASE),
    re.compile(r"^\s*Question\s*(\d+)", re.IGNORECASE),
    re.compile(r"^\s*Ans(?:wer)?\.?\s*(?:No\.?\s*)?(\d+)\b", re.IGNORECASE),
    re.compile(r"^\s*(\d+)\s*[-/]\s*[A-Za-z]\b"),
    re.compile(r"^\s*(\d+)\s*[\.)]"),
]

SUBQUESTION_PATTERNS = [
    re.compile(r"^\s*\(?([a-h])\)"),
    re.compile(r"^\s*([a-h])\)"),
]

SUBSUBQUESTION_PATTERNS = [
    re.compile(r"^\s*\(?([ivxlcdm]+)\)"),
    re.compile(r"^\s*([ivxlcdm]+)\)"),
]


def _bbox(block: Dict[str, Any]) -> Dict[str, float]:
    geo = (block.get("Geometry") or {}).get("BoundingBox") or {}
    return {
        "left": float(geo.get("Left", 0.0)),
        "top": float(geo.get("Top", 0.0)),
        "width": float(geo.get("Width", 0.0)),
        "height": float(geo.get("Height", 0.0)),
    }


def rebuild_page_text(blocks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build ordered line text per page and retain tables/line positions."""
    lines_by_page: Dict[int, List[Dict[str, Any]]] = {}
    tables_by_page: Dict[int, List[Dict[str, Any]]] = {}

    for block in blocks or []:
        btype = block.get("BlockType")
        page = int(block.get("Page") or 1)
        if btype == "LINE":
            lines_by_page.setdefault(page, []).append(
                {
                    "text": block.get("Text") or "",
                    "bbox": _bbox(block),
                    "confidence": float(block.get("Confidence") or 0.0),
                }
            )
        if btype == "TABLE":
            tables_by_page.setdefault(page, []).append(
                {
                    "bbox": _bbox(block),
                    "confidence": float(block.get("Confidence") or 0.0),
                    "id": block.get("Id"),
                }
            )

    page_texts: List[Dict[str, Any]] = []
    line_positions: List[Dict[str, Any]] = []

    for page in sorted(lines_by_page.keys()):
        lines = lines_by_page.get(page, [])
        lines_sorted = sorted(lines, key=lambda l: (l["bbox"]["top"], l["bbox"]["left"]))
        full_text = "\n".join([l["text"] for l in lines_sorted]).strip()
        for l in lines_sorted:
            line_positions.append(
                {
                    "page": page,
                    "text": l["text"],
                    "bbox": l["bbox"],
                    "line_height": l["bbox"]["height"],
                }
            )
        page_texts.append(
            {
                "page_index": page,
                "full_text": full_text,
                "lines": lines_sorted,
                "tables": tables_by_page.get(page, []),
            }
        )

    logger.info("[AWS][Rebuild] pages=%s", len(page_texts))
    return {
        "page_texts": page_texts,
        "line_positions": line_positions,
        "tables": tables_by_page,
    }


def detect_anchors(page_texts: List[Dict[str, Any]], line_positions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Detect anchor candidates across pages using regex + basic heuristics."""
    anchors: List[Dict[str, Any]] = []
    for line in line_positions or []:
        text = (line.get("text") or "").strip()
        if not text:
            continue
        lowered = text.lower()
        if any(marker in lowered for marker in SECTION_MARKERS):
            continue
        anchor_level = None
        q_num = None
        for pat in QUESTION_PATTERNS:
            m = pat.search(text)
            if m:
                q_num = m.group(1)
                anchor_level = "question"
                break
        if anchor_level is None:
            for pat in SUBQUESTION_PATTERNS:
                if pat.search(text):
                    anchor_level = "subquestion"
                    break
        if anchor_level is None:
            for pat in SUBSUBQUESTION_PATTERNS:
                if pat.search(text):
                    anchor_level = "subsubquestion"
                    break
        if anchor_level is None:
            continue

        anchors.append(
            {
                "question_number": q_num,
                "anchor_level": anchor_level,
                "page_index": line.get("page"),
                "bbox": line.get("bbox"),
                "text_snippet": text[:120],
                "confidence": 0.7 if anchor_level == "question" else 0.5,
            }
        )

    anchors_sorted = sorted(anchors, key=lambda a: (a.get("page_index", 0), a.get("bbox", {}).get("top", 0.0)))
    logger.info("[AWS][Anchor] candidates=%s", len(anchors_sorted))
    return anchors_sorted
