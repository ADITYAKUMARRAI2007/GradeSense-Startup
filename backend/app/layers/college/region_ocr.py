"""Phase 4: region-level OCR with fallback merge."""

from __future__ import annotations

import base64
import re
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from app.utils.ocr_provider import get_ocr_provider


QUESTION_ANCHOR_RE = re.compile(r"^\s*(?:q\.?\s*)?0*(\d{1,3})(?:\s*[\).:]|\b)", re.IGNORECASE)
SUBPART_RE = re.compile(
    r"^\s*(?:[\(\[]\s*([a-z])\s*[\)\]]|([a-z])[\).]|[\(\[]\s*(i{1,4}|v|vi{0,3}|ix|x)\s*[\)\]]|(i{1,4}|v|vi{0,3}|ix|x)[\).])",
    re.IGNORECASE,
)
WORKING_NOTE_RE = re.compile(r"\b(?:working\s*note|wn|note|calculation|working)\b", re.IGNORECASE)

# Subject-specific patterns for better question detection
ACCOUNTING_MARKERS = re.compile(
    r"\b(?:journal\s+entry|ledger\s+account|trial\s+balance|particulars|"
    r"balance\s+sheet|profit\s+and\s+loss|trading\s+account|"
    r"cash\s+book|bank\s+reconciliation)\b",
    re.IGNORECASE
)
ACCOUNTING_ENTRY_RE = re.compile(r"^\s*(?:to|by)\s+(.+?)(?:a/?c|account)", re.IGNORECASE)

LANGUAGE_MARKERS = re.compile(
    r"\b(?:passage|comprehension|essay|letter\s+to|translate|grammar|"
    r"read\s+the\s+following|write\s+a|compose)\b",
    re.IGNORECASE
)

MATHS_MARKERS = re.compile(
    r"\b(?:solve|prove\s+that|calculate|find\s+the|show\s+that|verify|"
    r"evaluate|simplify|factorize|integrate|differentiate)\b",
    re.IGNORECASE
)

SCIENCE_MARKERS = re.compile(
    r"\b(?:diagram|experiment|observation|aim|apparatus|procedure|"
    r"conclusion|label|draw|identify|describe\s+the)\b",
    re.IGNORECASE
)

# Enhanced question detection patterns
QUESTION_VERB_START = re.compile(
    r"^\s*(?:explain|describe|define|discuss|compare|analyze|evaluate|"
    r"illustrate|justify|outline|state|list|name|give|write|draw|solve|"
    r"calculate|find|prove|show|verify|translate|compose)\b",
    re.IGNORECASE
)

# Detect question-like content
QUESTION_INDICATORS = re.compile(r"\?$|^\s*(?:what|why|how|when|where|which|who)\b", re.IGNORECASE)


def _b64_to_cv2(image_base64: str) -> np.ndarray:
    arr = np.frombuffer(base64.b64decode(image_base64), dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Failed to decode image")
    return img


def _cv2_to_b64(img: np.ndarray, quality: int = 90) -> str:
    ok, enc = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise ValueError("Failed to encode image")
    return base64.b64encode(enc.tobytes()).decode()


def _crop_b64(image_b64: str, bbox: List[float]) -> str:
    bgr = _b64_to_cv2(image_b64)
    h, w = bgr.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in bbox]
    x1 = max(0, min(w - 1, x1))
    y1 = max(0, min(h - 1, y1))
    x2 = max(x1 + 1, min(w, x2))
    y2 = max(y1 + 1, min(h, y2))
    return _cv2_to_b64(bgr[y1:y2, x1:x2])


def _normalize_sub_id(text: str) -> Optional[str]:
    m = SUBPART_RE.match((text or "").strip())
    if not m:
        return None
    token = m.group(1) or m.group(2) or m.group(3) or m.group(4)
    if not token:
        return None
    token = re.sub(r"[^a-z0-9]", "", token.strip().lower())
    return token or None


def _detect_subject_type(text: str) -> str:
    """Detect subject type from text content."""
    text_lower = (text or "").lower()
    
    # Count markers for each subject
    accounting_count = len(ACCOUNTING_MARKERS.findall(text_lower))
    language_count = len(LANGUAGE_MARKERS.findall(text_lower))
    maths_count = len(MATHS_MARKERS.findall(text_lower))
    science_count = len(SCIENCE_MARKERS.findall(text_lower))
    
    # Return subject with highest marker count
    counts = {
        "accounting": accounting_count,
        "language": language_count,
        "maths": maths_count,
        "science": science_count,
    }
    
    max_count = max(counts.values())
    if max_count > 0:
        return max(counts, key=counts.get)
    return "general"


def _is_question_like_content(text: str) -> bool:
    """Check if text looks like a question based on content patterns."""
    if not text or len(text.strip()) < 10:
        return False
    
    text_stripped = text.strip()
    
    # Check for question indicators
    if QUESTION_INDICATORS.search(text_stripped):
        return True
    
    # Check for question verb starts
    if QUESTION_VERB_START.match(text_stripped):
        return True
    
    # Check for subject-specific markers
    if (ACCOUNTING_MARKERS.search(text_stripped) or
        LANGUAGE_MARKERS.search(text_stripped) or
        MATHS_MARKERS.search(text_stripped) or
        SCIENCE_MARKERS.search(text_stripped)):
        return True
    
    return False


def _detect_accounting_entry(text: str) -> bool:
    """Detect if text is an accounting journal entry (To/By format)."""
    return bool(ACCOUNTING_ENTRY_RE.match((text or "").strip()))


def _extract_text_from_ocr(res: Dict[str, Any]) -> Dict[str, Any]:
    words = res.get("words", []) or []
    lines = res.get("lines", []) or []
    text = "\n".join(
        (ln.get("text", "") or "").strip()
        for ln in lines
        if (ln.get("text", "") or "").strip()
    )
    if not text:
        text = " ".join((w.get("text", "") or "").strip() for w in words if (w.get("text", "") or "").strip())

    conf_vals = [float(w.get("conf", 0.0) or 0.0) for w in words if (w.get("text", "") or "").strip()]
    confidence = float(sum(conf_vals) / max(1, len(conf_vals))) if conf_vals else 0.0
    return {"text": text.strip(), "confidence": confidence, "words": words, "lines": lines}


def extract_region_text(
    clean_pages: List[str],
    page_blocks: List[List[Dict[str, Any]]],
    min_confidence: float = 0.52,
    min_fallback_confidence: float = 0.45,
) -> List[Dict[str, Any]]:
    """Run OCR per region and merge low-confidence blocks with fallback OCR."""
    ocr = get_ocr_provider()
    regions: List[Dict[str, Any]] = []
    
    # Detect overall subject type from all text
    all_text = ""
    for blocks in page_blocks or []:
        for block in blocks:
            all_text += " "

    for blocks, page_b64 in zip(page_blocks or [], clean_pages or []):
        page_width = float(_b64_to_cv2(page_b64).shape[1]) if page_b64 else 1000.0
        for block in blocks:
            crop_b64 = _crop_b64(page_b64, block.get("bbox", [0, 0, 1, 1]))
            res_primary = ocr.detect(
                crop_b64,
                min_conf=0.35,
                min_words=1,
                min_lines=1,
                force_fallback=False,
                allow_fallback=True,
            )
            parsed = _extract_text_from_ocr(res_primary)
            text = parsed["text"]
            conf = parsed["confidence"]
            fallback_used = bool(res_primary.get("fallback_used", False))

            if conf < min_confidence or not text:
                res_fallback = ocr.detect(
                    crop_b64,
                    min_conf=0.2,
                    min_words=1,
                    min_lines=1,
                    force_fallback=True,
                    allow_fallback=True,
                )
                parsed_fb = _extract_text_from_ocr(res_fallback)
                if parsed_fb["text"] and parsed_fb["confidence"] >= max(conf, min_fallback_confidence):
                    text = parsed_fb["text"]
                    conf = parsed_fb["confidence"]
                    fallback_used = True

            stripped = (text or "").strip()
            q_match = QUESTION_ANCHOR_RE.match(stripped)
            q_num = int(q_match.group(1)) if q_match else None
            sub_id = _normalize_sub_id(stripped)
            is_working = bool(WORKING_NOTE_RE.search(stripped))
            is_table = block.get("type") == "table"
            in_anchor_lane = float((block.get("bbox") or [0])[0]) <= float(page_width * 0.52)
            
            # Enhanced question anchor detection
            is_anchor = bool(
                q_num is not None
                and not is_table
                and not is_working
                and (block.get("type") == "question_anchor_candidate" or in_anchor_lane)
            )
            
            # Detect subject-specific content markers
            is_accounting_entry = _detect_accounting_entry(stripped)
            is_question_content = _is_question_like_content(stripped)
            
            # Detect subject-specific markers
            has_accounting_marker = bool(ACCOUNTING_MARKERS.search(stripped))
            has_language_marker = bool(LANGUAGE_MARKERS.search(stripped))
            has_maths_marker = bool(MATHS_MARKERS.search(stripped))
            has_science_marker = bool(SCIENCE_MARKERS.search(stripped))

            regions.append(
                {
                    "block_id": str(block.get("block_id")),
                    "page_number": int(block.get("page_number") or 1),
                    "bbox": block.get("bbox") or [0, 0, 0, 0],
                    "block_type": block.get("type", "text"),
                    "text": stripped,
                    "ocr_confidence": round(float(conf), 4),
                    "question_anchor": int(q_num) if is_anchor else None,
                    "subpart_id": sub_id,
                    "is_table": bool(is_table),
                    "is_working_note": bool(is_working),
                    "is_accounting_entry": bool(is_accounting_entry),
                    "is_question_content": bool(is_question_content),
                    "has_accounting_marker": bool(has_accounting_marker),
                    "has_language_marker": bool(has_language_marker),
                    "has_maths_marker": bool(has_maths_marker),
                    "has_science_marker": bool(has_science_marker),
                    "fallback_used": bool(fallback_used),
                    "ocr_provider": res_primary.get("provider"),
                }
            )

    regions.sort(key=lambda r: (int(r.get("page_number", 0)), float((r.get("bbox") or [0, 0])[1]), float((r.get("bbox") or [0])[0])))
    return regions


__all__ = ["extract_region_text"]
