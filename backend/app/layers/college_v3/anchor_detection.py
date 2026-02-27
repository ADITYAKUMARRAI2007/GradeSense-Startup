"""Hierarchical anchor detection for college_v3."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.config import logger


SECTION_PATTERNS = (
    r"^\s*SECTION\b",
    r"^\s*PART\b",
    r"^\s*VERY\s+SHORT\s+ANSWER\b",
    r"^\s*SHORT\s+ANSWER\b",
    r"^\s*LONG\s+ANSWER\b",
    r"^\s*CASE\s+STUDY\b",
    r"^\s*INTERNAL\s+CHOICE\b",
    r"^\s*\(?OR\)?\s*$",
)

QUESTION_PATTERNS = (
    re.compile(r"^\s*Q(?:uestion)?\s*([0-9]{1,3})\b", re.IGNORECASE),
    re.compile(r"^\s*([0-9]{1,3})\s*[\.\)]\s+", re.IGNORECASE),
)

SUBQUESTION_PATTERNS = (
    re.compile(r"^\s*\(?([a-z])\)\s+", re.IGNORECASE),
    re.compile(r"^\s*([a-z])\)\s+", re.IGNORECASE),
)

SUBSUBQUESTION_PATTERNS = (
    re.compile(r"^\s*\(?([ivxlcdm]{1,6})\)\s+", re.IGNORECASE),
    re.compile(r"^\s*([ivxlcdm]{1,6})\)\s+", re.IGNORECASE),
)


def _is_section(text: str) -> bool:
    if not text:
        return False
    for pat in SECTION_PATTERNS:
        if re.match(pat, text.strip().upper()):
            return True
    return False


def _bbox_center(bbox: List[float]) -> float:
    if not bbox or len(bbox) != 4:
        return 0.0
    return float(bbox[1] + bbox[3]) * 0.5


def detect_anchors(pages_ocr: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Detect hierarchical anchors from OCR blocks."""
    anchors: List[Dict[str, Any]] = []
    last_question_number: Optional[int] = None

    for page in pages_ocr or []:
        page_index = int(page.get("page_index") or 1)
        blocks = list(page.get("blocks") or [])
        blocks.sort(key=lambda b: (_bbox_center(b.get("bbox") or [0, 0, 0, 0]), float((b.get("bbox") or [0])[0])))
        for block in blocks:
            text = str(block.get("text", "")).strip()
            if not text:
                continue
            if _is_section(text):
                continue

            qn: Optional[int] = None
            for pat in QUESTION_PATTERNS:
                m = pat.search(text)
                if m:
                    qn = int(m.group(1))
                    break

            if qn is not None:
                last_question_number = qn
                anchors.append(
                    {
                        "question_number": qn,
                        "anchor_level": "question",
                        "parent_question_number": None,
                        "page_index": page_index,
                        "bbox": block.get("bbox") or [0, 0, 0, 0],
                        "text_snippet": text[:160],
                        "confidence": float(block.get("confidence", 0.0) or 0.0),
                        "y_position": _bbox_center(block.get("bbox") or [0, 0, 0, 0]),
                    }
                )
                continue

            sub_match = None
            for pat in SUBQUESTION_PATTERNS:
                sub_match = pat.search(text)
                if sub_match:
                    break
            if sub_match:
                if last_question_number is None:
                    continue
                anchors.append(
                    {
                        "question_number": last_question_number,
                        "anchor_level": "subquestion",
                        "parent_question_number": last_question_number,
                        "page_index": page_index,
                        "bbox": block.get("bbox") or [0, 0, 0, 0],
                        "text_snippet": text[:160],
                        "confidence": float(block.get("confidence", 0.0) or 0.0),
                        "y_position": _bbox_center(block.get("bbox") or [0, 0, 0, 0]),
                    }
                )
                continue

            subsub_match = None
            for pat in SUBSUBQUESTION_PATTERNS:
                subsub_match = pat.search(text)
                if subsub_match:
                    break
            if subsub_match:
                if last_question_number is None:
                    continue
                anchors.append(
                    {
                        "question_number": last_question_number,
                        "anchor_level": "subsubquestion",
                        "parent_question_number": last_question_number,
                        "page_index": page_index,
                        "bbox": block.get("bbox") or [0, 0, 0, 0],
                        "text_snippet": text[:160],
                        "confidence": float(block.get("confidence", 0.0) or 0.0),
                        "y_position": _bbox_center(block.get("bbox") or [0, 0, 0, 0]),
                    }
                )

    anchors.sort(key=lambda a: (int(a.get("page_index") or 1), float(a.get("y_position") or 0.0)))
    logger.info("[COLLEGE-V3][ANCHOR] anchors=%s", len(anchors))
    return anchors
