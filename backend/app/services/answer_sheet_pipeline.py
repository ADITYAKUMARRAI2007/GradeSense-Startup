"""Packet-first answer sheet pipeline for accountancy-style grading."""

import base64
import gc
import io
import os
import re
from typing import Any, Dict, List, Optional, Tuple

# cv2 and numpy are optional at import-time; some environments (e.g.
# lightweight test containers) may not have them installed.  We wrap the
# import so that at least the PDF-based helpers (used by simple_pipeline)
# remain available.

_HAS_CV2 = True
try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None  # type: ignore
    np = None  # type: ignore
    _HAS_CV2 = False

# fitz (PyMuPDF) is also optional; if absent we fall back to text-only
# processing in the calling modules.  We import it lazily when needed.
try:
    import fitz
except ImportError:
    fitz = None  # type: ignore

# pdf2image is used for PDF->image conversion; if unavailable we simply
# won't be able to normalise/ocr pages via the full pipeline.  Functions
# that rely on it will raise if executed.
try:
    from pdf2image import convert_from_bytes, pdfinfo_from_bytes
except ImportError:
    convert_from_bytes = None  # type: ignore
    pdfinfo_from_bytes = None  # type: ignore

from app.config import logger
from app.utils.ocr_provider import get_ocr_provider


ANCHOR_LEFT_RATIO = float(os.getenv("ANCHOR_LEFT_RATIO", "0.38"))
REGION_OCR_CONF_MIN = float(os.getenv("REGION_OCR_CONF_MIN", "0.52"))
REGION_OCR_VISION_CONF_MIN = float(os.getenv("REGION_OCR_VISION_CONF_MIN", "0.45"))
PIPELINE_ENABLED = os.getenv("ANSWER_PACKET_PIPELINE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
PDF_IMAGE_BATCH_PAGES = int(os.getenv("PDF_IMAGE_BATCH_PAGES", "4"))
PDF_IMAGE_JPEG_QUALITY = int(os.getenv("PDF_IMAGE_JPEG_QUALITY", "82"))
PDF_IMAGE_NORMALIZE = os.getenv("PDF_IMAGE_NORMALIZE", "true").lower() in ("1", "true", "yes", "on")

# anchor regex: capture a question number (with optional leading Q/q and
# any zero padding) followed by a punctuation or whitespace.  We deliberately
# avoid the ^ anchor here so that `.search` can find a number anywhere in the
# region; student writing often places the number after text.
QUESTION_ANCHOR_RE = re.compile(r"(?:q\.?\s*)?0*(\d{1,3})(?:[\).:]|\b)", re.IGNORECASE)
SUBPART_RE = re.compile(
    r"^\s*(?:[\(\[]\s*([a-z])\s*[\)\]]|([a-z])[\).]|[\(\[]\s*(i{1,4}|v|vi{0,3}|ix|x)\s*[\)\]]|(i{1,4}|v|vi{0,3}|ix|x)[\).])",
    re.IGNORECASE,
)
MARKS_RE = re.compile(r"\(?\b(\d+(?:\.\d+)?)\s*(?:marks?|m)\b\)?", re.IGNORECASE)
WORKING_NOTE_RE = re.compile(r"\b(?:working\s*note|wn|note|calculation|working)\b", re.IGNORECASE)
TO_ACCOUNT_RE = re.compile(r"^\s*to\s+(.+?)(?:a\/?c|account)\b", re.IGNORECASE)
BY_ACCOUNT_RE = re.compile(r"^\s*by\s+(.+?)(?:a\/?c|account)\b", re.IGNORECASE)
AMOUNT_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*$")
FORMULA_RE = re.compile(r"[=+\-*/]")


def _b64_to_cv2(image_base64: str) -> np.ndarray:
    data = base64.b64decode(image_base64)
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Failed to decode base64 image")
    return img


def _cv2_to_b64(img: np.ndarray, quality: int = 85) -> str:
    ok, enc = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise ValueError("Failed to encode image")
    return base64.b64encode(enc.tobytes()).decode()


def _normalize_sub_id(text: str) -> Optional[str]:
    m = SUBPART_RE.match((text or "").strip())
    if not m:
        return None
    token = m.group(1) or m.group(2) or m.group(3) or m.group(4)
    if not token:
        return None
    token = token.strip().lower()
    token = re.sub(r"[^a-z0-9]", "", token)
    return token or None


def _infer_question_type(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in ("journal", "debit", "credit", "dr", "cr", "to ", "by ")):
        return "journal"
    if any(k in t for k in ("ledger", "account", "a/c", "trial balance")):
        return "ledger"
    if any(k in t for k in ("goodwill", "sacrificing ratio", "gaining ratio")):
        return "goodwill"
    if any(k in t for k in ("ratio", "current ratio", "quick ratio", "debt equity")):
        return "ratios"
    if any(k in t for k in ("prepare", "balance sheet", "cash flow", "comparative")):
        return "calculation"
    return "theory"


def _expected_components(question_type: str) -> List[str]:
    if question_type == "journal":
        return ["entries", "dr_cr_columns", "narration", "amounts", "totals"]
    if question_type == "ledger":
        return ["account_headers", "to_by_rows", "balance_c_d", "totals"]
    if question_type == "goodwill":
        return ["formula", "calculation_steps", "ratio_logic", "final_value"]
    if question_type == "ratios":
        return ["formula", "substitution", "calculation", "final_ratio"]
    if question_type == "calculation":
        return ["working_notes", "tabular_structure", "totals", "final_answer"]
    return ["key_points", "concepts", "supporting_reasoning"]


def build_question_blueprint_from_exam_questions(questions: List[dict]) -> List[dict]:
    blueprint: List[dict] = []
    for q in questions or []:
        q_num = q.get("question_number")
        if q_num is None:
            continue
        try:
            q_num_int = int(q_num)
        except Exception:
            continue
        rubric = str(q.get("rubric", "") or "")
        q_text = str(q.get("question_text", "") or "")
        source_text = f"{q_text}\n{rubric}".strip()
        q_type = _infer_question_type(source_text)
        parts = []
        for sq in q.get("sub_questions", []) or []:
            sub_id = str(sq.get("sub_id", "") or "").strip().lower()
            if not sub_id:
                continue
            parts.append(
                {
                    "part_id": sub_id,
                    "marks": float(sq.get("max_marks") or 0.0),
                    "rubric": str(sq.get("rubric", "") or ""),
                }
            )
        blueprint.append(
            {
                "question_id": q_num_int,
                "parts": parts,
                "marks": float(q.get("max_marks") or 0.0),
                "type": q_type,
                "expected_components": _expected_components(q_type),
                "rubric": rubric,
                "question_text": q_text,
            }
        )
    return sorted(blueprint, key=lambda x: int(x["question_id"]))


def build_question_blueprint_from_pdf(pdf_bytes: bytes) -> List[dict]:
    """Extract coarse question blueprint directly from question paper PDF text."""
    blueprint: List[dict] = []
    if fitz is None:
        logger.warning("Question blueprint extraction skipped because PyMuPDF is not installed")
        return blueprint
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = []
        for page in doc:
            text.append(page.get_text("text") or "")
        doc.close()
        joined = "\n".join(text)
    except Exception as e:
        logger.warning("Question blueprint PDF parse failed: %s", e)
        return blueprint

    chunks = re.split(r"\n\s*(?:Q\.?\s*)?(\d{1,3})[\).:\s]", joined)
    if len(chunks) < 3:
        return blueprint

    for idx in range(1, len(chunks), 2):
        qn_raw = chunks[idx]
        body = chunks[idx + 1] if idx + 1 < len(chunks) else ""
        try:
            qn = int(qn_raw)
        except Exception:
            continue
        marks = 0.0
        marks_match = MARKS_RE.search(body)
        if marks_match:
            try:
                marks = float(marks_match.group(1))
            except Exception:
                marks = 0.0
        question_type = _infer_question_type(body)
        parts: List[dict] = []
        for sm in re.finditer(r"\(([a-z]|i{1,4}|v|vi{0,3}|ix|x)\)", body, re.IGNORECASE):
            sid = re.sub(r"[^a-z0-9]", "", sm.group(1).lower())
            if sid:
                parts.append({"part_id": sid, "marks": 0.0, "rubric": ""})
        blueprint.append(
            {
                "question_id": qn,
                "parts": parts,
                "marks": marks,
                "type": question_type,
                "expected_components": _expected_components(question_type),
                "rubric": body[:1200].strip(),
                "question_text": f"Q{qn}",
            }
        )
    return sorted(blueprint, key=lambda x: int(x["question_id"]))


def normalize_answer_pages(images: List[str]) -> List[str]:
    """Stage 2 normalization over already-rendered pages."""
    cleaned: List[str] = []
    for image_b64 in images:
        try:
            bgr = _b64_to_cv2(image_b64)
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

            # Shadow suppression + contrast.
            blur = cv2.GaussianBlur(gray, (3, 3), 0)
            bg = cv2.medianBlur(blur, 25)
            norm = cv2.divide(blur, bg, scale=255)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(norm)

            # Deskew by minimum-area rectangle angle from foreground pixels.
            th = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
            coords = cv2.findNonZero(th)
            if coords is not None and len(coords) > 500:
                angle = cv2.minAreaRect(coords)[-1]
                if angle < -45:
                    angle = 90 + angle
                if abs(angle) > 0.1:
                    h, w = enhanced.shape[:2]
                    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
                    enhanced = cv2.warpAffine(
                        enhanced,
                        m,
                        (w, h),
                        flags=cv2.INTER_CUBIC,
                        borderMode=cv2.BORDER_REPLICATE,
                    )

            out = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)
            cleaned.append(_cv2_to_b64(out, quality=88))
        except Exception as e:
            logger.warning("Answer normalization failed for a page; using original. err=%s", e)
            cleaned.append(image_b64)
    return cleaned


def _get_pdf_page_count(pdf_bytes: bytes) -> Optional[int]:
    if pdfinfo_from_bytes is not None:
        try:
            info = pdfinfo_from_bytes(pdf_bytes)
            pages = int(info.get("Pages", 0) or 0)
            if pages > 0:
                return pages
        except Exception as e:
            logger.warning("pdfinfo_from_bytes failed; falling back. err=%s", e)
    if fitz is not None:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            pages = int(doc.page_count)
            doc.close()
            return pages if pages > 0 else None
        except Exception as e:
            logger.warning("PyMuPDF page count failed; falling back. err=%s", e)
    return None


def pdf_to_clean_images(pdf_bytes: bytes, dpi: int = 300, normalize: Optional[bool] = None) -> List[str]:
    """Stage 2 from raw PDF bytes using pdf2image at target DPI, batched to reduce memory."""
    if convert_from_bytes is None:
        raise RuntimeError("pdf2image is not available")

    if normalize is None:
        normalize = PDF_IMAGE_NORMALIZE
    if normalize and not _HAS_CV2:
        logger.warning("cv2 not available; skipping normalization")
        normalize = False

    images: List[str] = []
    page_count = _get_pdf_page_count(pdf_bytes)
    batch_size = max(1, int(PDF_IMAGE_BATCH_PAGES or 1))

    def _encode_pages(pages: List["Image.Image"]) -> List[str]:
        encoded: List[str] = []
        for page in pages:
            buf = io.BytesIO()
            page.save(buf, format="JPEG", quality=PDF_IMAGE_JPEG_QUALITY, optimize=True)
            encoded.append(base64.b64encode(buf.getvalue()).decode())
        return encoded

    if not page_count:
        pil_pages = convert_from_bytes(pdf_bytes, dpi=dpi, fmt="jpeg")
        images = _encode_pages(pil_pages)
        return normalize_answer_pages(images) if normalize else images

    for start in range(1, page_count + 1, batch_size):
        end = min(page_count, start + batch_size - 1)
        pil_pages = convert_from_bytes(
            pdf_bytes,
            dpi=dpi,
            fmt="jpeg",
            first_page=start,
            last_page=end,
        )
        batch_images = _encode_pages(pil_pages)
        if normalize:
            batch_images = normalize_answer_pages(batch_images)
        images.extend(batch_images)
        del pil_pages
        del batch_images
        gc.collect()
    return images


def _table_like(binary_inv: np.ndarray, bbox: Tuple[int, int, int, int]) -> bool:
    x, y, w, h = bbox
    roi = binary_inv[y : y + h, x : x + w]
    if roi.size == 0:
        return False
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, w // 12), 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, h // 8)))
    h_lines = cv2.morphologyEx(roi, cv2.MORPH_OPEN, h_kernel)
    v_lines = cv2.morphologyEx(roi, cv2.MORPH_OPEN, v_kernel)
    line_pixels = cv2.countNonZero(h_lines) + cv2.countNonZero(v_lines)
    density = line_pixels / float(max(1, w * h))
    return density >= 0.045


def detect_page_layout(clean_pages: List[str]) -> List[List[dict]]:
    """Stage 3 block detection and coarse typing."""
    all_pages: List[List[dict]] = []
    for page_idx, image_b64 in enumerate(clean_pages, start=1):
        blocks: List[dict] = []
        try:
            bgr = _b64_to_cv2(image_b64)
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            thr = cv2.adaptiveThreshold(
                gray,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY_INV,
                21,
                15,
            )
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (13, 5))
            conn = cv2.morphologyEx(thr, cv2.MORPH_CLOSE, kernel, iterations=1)
            contours, _ = cv2.findContours(conn, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            h, w = gray.shape[:2]
            i = 0
            for c in contours:
                x, y, bw, bh = cv2.boundingRect(c)
                area = bw * bh
                if area < 1800 or bw < 25 or bh < 12:
                    continue
                x1 = max(0, x - 6)
                y1 = max(0, y - 4)
                x2 = min(w, x + bw + 6)
                y2 = min(h, y + bh + 4)
                bw2 = x2 - x1
                bh2 = y2 - y1
                if bw2 * bh2 < 1800:
                    continue
                is_table = _table_like(thr, (x1, y1, bw2, bh2))
                left_margin = x1 <= int(w * ANCHOR_LEFT_RATIO)
                block_type = "table" if is_table else ("question_anchor_candidate" if left_margin and bh2 < int(h * 0.12) else "text")
                i += 1
                blocks.append(
                    {
                        "block_id": f"P{page_idx}-B{i}",
                        "page_number": page_idx,
                        "bbox": [float(x1), float(y1), float(x2), float(y2)],
                        "type": block_type,
                    }
                )

            if not blocks:
                # Never OCR the entire page as one region. Use deterministic bands.
                band_count = 6
                pad_x = max(8, int(w * 0.02))
                pad_top = max(8, int(h * 0.015))
                usable_h = max(1, h - (2 * pad_top))
                band_h = max(24, usable_h // band_count)
                for bi in range(band_count):
                    y1 = pad_top + (bi * band_h)
                    y2 = pad_top + ((bi + 1) * band_h if bi < band_count - 1 else usable_h)
                    blocks.append(
                        {
                            "block_id": f"P{page_idx}-FB{bi+1}",
                            "page_number": page_idx,
                            "bbox": [float(pad_x), float(y1), float(w - pad_x), float(min(h, y2))],
                            "type": "text",
                        }
                    )
            blocks.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))
        except Exception as e:
            logger.warning("Layout detection failed on page %s: %s", page_idx, e)
            blocks = []
        all_pages.append(blocks)
    return all_pages


def _crop_b64(image_b64: str, bbox: List[float]) -> str:
    bgr = _b64_to_cv2(image_b64)
    h, w = bgr.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in bbox]
    x1 = max(0, min(w - 1, x1))
    y1 = max(0, min(h - 1, y1))
    x2 = max(x1 + 1, min(w, x2))
    y2 = max(y1 + 1, min(h, y2))
    roi = bgr[y1:y2, x1:x2]
    return _cv2_to_b64(roi, quality=90)


def run_region_ocr(clean_pages: List[str], page_layout: List[List[dict]]) -> List[dict]:
    """Stage 4 region OCR with confidence fallback."""
    ocr = get_ocr_provider()
    # Region crops often include blank/noisy strips; keep provider stable and fast.
    # Whole-page OCR fallback behavior remains available in legacy mapping path.
    region_allow_fallback = os.getenv("REGION_OCR_ALLOW_FALLBACK", "false").lower() in ("1", "true", "yes", "on")
    regions: List[dict] = []
    for page_blocks, page_b64 in zip(page_layout, clean_pages):
        page_w = 1000.0
        try:
            page_w = float(_b64_to_cv2(page_b64).shape[1])
        except Exception:
            page_w = 1000.0
        for block in page_blocks:
            block_id = block["block_id"]
            bbox = block["bbox"]
            crop_b64 = _crop_b64(page_b64, bbox)
            res = ocr.detect(
                crop_b64,
                min_conf=0.35,
                min_words=1,
                min_lines=1,
                force_fallback=False,
                allow_fallback=region_allow_fallback,
            )
            words = res.get("words", []) or []
            lines = res.get("lines", []) or []
            text = "\n".join((ln.get("text", "") or "").strip() for ln in lines if (ln.get("text", "") or "").strip())
            if not text:
                text = " ".join((w.get("text", "") or "").strip() for w in words if (w.get("text", "") or "").strip())
            conf_vals = [float(w.get("conf", 0.0) or 0.0) for w in words if (w.get("text", "") or "").strip()]
            confidence = float(sum(conf_vals) / max(1, len(conf_vals))) if conf_vals else 0.0

            fallback_used = bool(res.get("fallback_used", False))
            if confidence < REGION_OCR_CONF_MIN or not text.strip():
                retry = ocr.detect(
                    crop_b64,
                    min_conf=0.2,
                    min_words=1,
                    min_lines=1,
                    force_fallback=True,
                    allow_fallback=region_allow_fallback,
                )
                retry_words = retry.get("words", []) or []
                retry_lines = retry.get("lines", []) or []
                retry_text = "\n".join(
                    (ln.get("text", "") or "").strip()
                    for ln in retry_lines
                    if (ln.get("text", "") or "").strip()
                )
                if not retry_text:
                    retry_text = " ".join((w.get("text", "") or "").strip() for w in retry_words if (w.get("text", "") or "").strip())
                retry_conf_vals = [float(w.get("conf", 0.0) or 0.0) for w in retry_words if (w.get("text", "") or "").strip()]
                retry_conf = float(sum(retry_conf_vals) / max(1, len(retry_conf_vals))) if retry_conf_vals else 0.0
                if retry_text and retry_conf >= max(confidence, REGION_OCR_VISION_CONF_MIN):
                    words = retry_words
                    lines = retry_lines
                    text = retry_text
                    confidence = retry_conf
                    fallback_used = True

            stripped = (text or "").strip()
            # question anchors are often written at the beginning of a line, but
            # on messy student sheets the number may appear in the middle of a
            # region ("Answer to Q1:", "1.", etc.).  Use `search` instead of
            # `match` so we pick up the first occurrence anywhere in the text.
            # the rest of the pipeline relies on `qn` being the first valid
            # question number seen, which is exactly what the user described –
            # look for the first Q you see and then pin all following blocks to
            # that question until a new anchor appears.
            q_match = QUESTION_ANCHOR_RE.search(stripped)
            qn = int(q_match.group(1)) if q_match else None
            sub_id = _normalize_sub_id(stripped)
            working_note = bool(WORKING_NOTE_RE.search(stripped))
            in_left_anchor_lane = float(bbox[0]) <= float(page_w * max(ANCHOR_LEFT_RATIO + 0.08, 0.45))
            is_anchor = bool(
                qn is not None
                and not working_note
                and block.get("type") != "table"
                and (block.get("type") == "question_anchor_candidate" or in_left_anchor_lane)
            )

            regions.append(
                {
                    "block_id": block_id,
                    "page_number": int(block["page_number"]),
                    "bbox": bbox,
                    "block_type": block.get("type", "text"),
                    "text": stripped,
                    "ocr_confidence": round(float(confidence), 4),
                    "fallback_used": fallback_used,
                    "question_anchor": qn if is_anchor else None,
                    "subpart_id": sub_id,
                    "is_working_note": working_note,
                    "is_table": block.get("type") == "table",
                    "ocr_provider": res.get("provider"),
                }
            )

    regions.sort(key=lambda r: (int(r["page_number"]), float(r["bbox"][1]), float(r["bbox"][0])))
    return regions


def build_packets(regions: List[dict], blueprint: List[dict]) -> Dict[int, dict]:
    """Stage 5 deterministic packet reconstruction."""
    expected_qs = {int(q["question_id"]) for q in blueprint if q.get("question_id") is not None}
    packets: Dict[int, dict] = {}
    active_q: Optional[int] = None
    last_seen_q: Optional[int] = None
    assigned = 0

    for r in regions:
        qn = r.get("question_anchor")
        if isinstance(qn, int) and qn in expected_qs and not r.get("is_working_note"):
            active_q = qn
            last_seen_q = qn

        chosen: Optional[int] = None
        if active_q in expected_qs:
            chosen = active_q
        elif last_seen_q in expected_qs and (r.get("is_working_note") or r.get("is_table")):
            chosen = last_seen_q
        elif r.get("question_anchor") in expected_qs:
            chosen = int(r["question_anchor"])
            active_q = chosen
            last_seen_q = chosen

        if chosen is None:
            continue

        pkt = packets.setdefault(
            chosen,
            {
                "question_id": chosen,
                "pages": [],
                "text_blocks": [],
                "tables": [],
                "workings": [],
                "subparts": {},
                "segment_ids": [],
                "mapping_trace": [],
                "start_anchor": None,
                "end_anchor": None,
            },
        )
        assigned += 1
        pkt["pages"].append(int(r["page_number"]))
        pkt["segment_ids"].append(str(r["block_id"]))
        pkt["text_blocks"].append(
            {
                "block_id": r["block_id"],
                "page_number": r["page_number"],
                "bbox": r["bbox"],
                "text": r["text"],
                "confidence": r["ocr_confidence"],
                "is_table": bool(r["is_table"]),
                "is_working_note": bool(r["is_working_note"]),
            }
        )
        if r["is_table"]:
            pkt["tables"].append(r["block_id"])
            pkt["mapping_trace"].append("table_sticky")
        if r["is_working_note"]:
            pkt["workings"].append(r["block_id"])
            pkt["mapping_trace"].append("working_note_attach")
        if r.get("subpart_id"):
            sid = str(r["subpart_id"])
            pkt["subparts"].setdefault(sid, []).append(r["block_id"])

        if isinstance(r.get("question_anchor"), int) and r["question_anchor"] == chosen:
            anchor = {
                "page": int(r["page_number"]),
                "y": float(r["bbox"][1]),
                "raw": (r.get("text", "") or "")[:80],
                "segment_id": str(r["block_id"]),
            }
            if pkt["start_anchor"] is None:
                pkt["start_anchor"] = anchor
            pkt["end_anchor"] = anchor
            pkt["mapping_trace"].append("anchor_match")

    for qn, pkt in packets.items():
        pkt["pages"] = sorted(set(pkt["pages"]))
        pkt["segment_ids"] = list(dict.fromkeys(pkt["segment_ids"]))
        pkt["tables"] = list(dict.fromkeys(pkt["tables"]))
        pkt["workings"] = list(dict.fromkeys(pkt["workings"]))
        pkt["mapping_trace"] = list(dict.fromkeys(pkt["mapping_trace"]))
        text = "\n".join(tb["text"] for tb in pkt["text_blocks"] if tb.get("text"))
        confs = [float(tb.get("confidence", 0.0) or 0.0) for tb in pkt["text_blocks"]]
        anchor_bonus = 0.15 if pkt.get("start_anchor") else 0.0
        table_bonus = 0.08 if pkt["tables"] else 0.0
        pkt["combined_text"] = text[:12000]
        pkt["mapping_confidence"] = round(min(0.99, (sum(confs) / max(1, len(confs))) + anchor_bonus + table_bonus), 4)
        pkt["subanswers"] = []
        for sid, block_ids in sorted(pkt["subparts"].items(), key=lambda it: it[0]):
            sid_set = set(block_ids)
            sub_blocks = [b for b in pkt["text_blocks"] if b["block_id"] in sid_set]
            sub_pages = sorted(set(int(b["page_number"]) for b in sub_blocks))
            sub_text = "\n".join(str(b.get("text", "") or "") for b in sub_blocks).strip()
            sub_confs = [float(b.get("confidence", 0.0) or 0.0) for b in sub_blocks]
            pkt["subanswers"].append(
                {
                    "sub_id": sid,
                    "segment_ids": list(dict.fromkeys(block_ids)),
                    "combined_text": sub_text[:5000],
                    "page_refs": sub_pages,
                    "mapping_confidence": round(sum(sub_confs) / max(1, len(sub_confs)), 4),
                }
            )
        pkt["subquestion_count"] = len(pkt["subanswers"])
        pkt["table_segments"] = pkt["tables"]
        pkt["working_note_segments"] = pkt["workings"]

    mapped_count = assigned
    total_regions = len(regions)
    mapping_coverage = mapped_count / total_regions if total_regions > 0 else 0.0
    low_conf = sorted([int(qn) for qn, pkt in packets.items() if float(pkt.get("mapping_confidence", 0.0) or 0.0) < 0.6])
    packets["_meta"] = {
        "mapping_coverage": round(mapping_coverage, 4),
        "packets_generated": len([k for k in packets.keys() if isinstance(k, int)]),
        "subpacket_count": sum(len(pkt.get("subanswers", [])) for qn, pkt in packets.items() if isinstance(qn, int)),
        "low_confidence_questions": low_conf,
        "consistency_flags": ["low_mapping_coverage"] if mapping_coverage < 0.85 else [],
        "page_segment_index": [
            {
                "segment_id": r["block_id"],
                "page": int(r["page_number"]),
                "text": (r.get("text", "") or "")[:600],
                "x1": float(r["bbox"][0]),
                "y1": float(r["bbox"][1]),
                "x2": float(r["bbox"][2]),
                "y2": float(r["bbox"][3]),
            }
            for r in regions
        ],
    }
    return packets


def align_packets_to_blueprint(blueprint: List[dict], packets: Dict[int, dict]) -> List[dict]:
    """Stage 6 alignment with sequence fallback."""
    aligned: List[dict] = []
    used_packets = set()

    packet_keys = sorted([int(k) for k in packets.keys() if isinstance(k, int)])
    packet_by_order = [packets[k] for k in packet_keys]
    next_unmatched_idx = 0

    for q in sorted(blueprint, key=lambda x: int(x["question_id"])):
        qid = int(q["question_id"])
        pkt = packets.get(qid)
        aligned_by = "anchor"
        if pkt is None:
            while next_unmatched_idx < len(packet_by_order):
                cand = packet_by_order[next_unmatched_idx]
                next_unmatched_idx += 1
                cand_q = int(cand.get("question_id", -1))
                if cand_q not in used_packets:
                    pkt = cand
                    aligned_by = "sequence_fallback"
                    break
        if pkt:
            used_packets.add(int(pkt.get("question_id", qid)))
        aligned.append(
            {
                "question_id": qid,
                "expected": q,
                "packet": pkt,
                "aligned_by": aligned_by if pkt else "missing",
            }
        )
    return aligned


def structure_accounting_answer(packet: Optional[dict]) -> Dict[str, Any]:
    """Stage 7 accounting structuring from packet text blocks."""
    if not packet:
        return {
            "accounts": [],
            "journal_entries": [],
            "calculations": [],
            "totals": [],
            "reasoning": [],
        }

    lines: List[str] = []
    for blk in packet.get("text_blocks", []):
        text = str(blk.get("text", "") or "").strip()
        if not text:
            continue
        for ln in text.splitlines():
            ln = ln.strip()
            if ln:
                lines.append(ln)

    accounts = set()
    journal_entries: List[dict] = []
    calculations: List[str] = []
    totals: List[dict] = []
    reasoning: List[str] = []

    for line in lines:
        m_to = TO_ACCOUNT_RE.match(line)
        m_by = BY_ACCOUNT_RE.match(line)
        side = None
        acc_name = None
        if m_to:
            side = "Dr"
            acc_name = m_to.group(1).strip()
        elif m_by:
            side = "Cr"
            acc_name = m_by.group(1).strip()
        if acc_name:
            accounts.add(acc_name)
            amt_m = AMOUNT_RE.search(line)
            amount = amt_m.group(1).replace(",", "") if amt_m else None
            journal_entries.append({"side": side, "account": acc_name, "amount": amount, "line": line})

        low = line.lower()
        if "total" in low or "balance c/d" in low or "balance b/d" in low:
            amt_m = AMOUNT_RE.search(line)
            totals.append({"line": line, "amount": (amt_m.group(1).replace(",", "") if amt_m else None)})

        if FORMULA_RE.search(line) and any(ch.isdigit() for ch in line):
            calculations.append(line)
        if WORKING_NOTE_RE.search(line):
            reasoning.append(line)

    return {
        "accounts": sorted(accounts),
        "journal_entries": journal_entries,
        "calculations": calculations,
        "totals": totals,
        "reasoning": reasoning,
    }


def run_answer_packet_pipeline(
    answer_images: List[str],
    questions: List[dict],
    question_paper_pdf_bytes: Optional[bytes] = None,
) -> Dict[str, Any]:
    """
    Run stage 1-9 packet pipeline from in-memory images.
    Returns stage artifacts + final question-wise structured payload.
    """
    blueprint = build_question_blueprint_from_exam_questions(questions)
    allow_pdf_enrich = os.getenv("ANSWER_PACKET_ALLOW_PDF_ENRICH", "false").lower() in ("1", "true", "yes", "on")
    if question_paper_pdf_bytes and allow_pdf_enrich:
        pdf_blueprint = build_question_blueprint_from_pdf(question_paper_pdf_bytes)
        if blueprint and pdf_blueprint:
            by_q_exam = {int(q["question_id"]): q for q in blueprint if q.get("question_id") is not None}
            by_q_pdf = {int(q["question_id"]): q for q in pdf_blueprint if q.get("question_id") is not None}
            merged = []
            for qid in sorted(by_q_exam.keys()):
                q_exam = by_q_exam[qid]
                q_pdf = by_q_pdf.get(qid) or {}
                merged.append(
                    {
                        **q_exam,
                        # Enrich text/type only for existing exam question IDs.
                        "question_text": q_exam.get("question_text") or q_pdf.get("question_text", ""),
                        "rubric": q_exam.get("rubric") or q_pdf.get("rubric", ""),
                        "type": q_exam.get("type") or q_pdf.get("type", "theory"),
                        "expected_components": q_exam.get("expected_components") or q_pdf.get("expected_components", []),
                    }
                )
            dropped_qids = sorted(set(by_q_pdf.keys()) - set(by_q_exam.keys()))
            if dropped_qids:
                logger.warning(
                    "Ignoring %s PDF-only blueprint question IDs not present in exam blueprint: %s",
                    len(dropped_qids),
                    dropped_qids[:20],
                )
            blueprint = merged

    clean_pages = normalize_answer_pages(answer_images)
    page_layout = detect_page_layout(clean_pages)
    region_text = run_region_ocr(clean_pages, page_layout)
    packets = build_packets(region_text, blueprint)
    aligned = align_packets_to_blueprint(blueprint, packets)

    final_rows: List[dict] = []
    for row in aligned:
        packet = row.get("packet")
        structured = structure_accounting_answer(packet)
        conf = float(packet.get("mapping_confidence", 0.0) or 0.0) if packet else 0.0
        issues: List[str] = []
        if not packet:
            issues.append("missing_packet")
        elif conf < 0.6:
            issues.append("low_mapping_confidence")
        if structured.get("totals"):
            for t in structured["totals"]:
                if t.get("amount") is None:
                    issues.append("uncertain_total")
                    break
        final_rows.append(
            {
                "question_id": int(row["question_id"]),
                "expected": row["expected"],
                "student_answer_structured": structured,
                "confidence": round(conf, 4),
                "issues": sorted(set(issues)),
                "aligned_by": row.get("aligned_by"),
                "packet": packet,
            }
        )

    return {
        "question_blueprint": blueprint,
        "clean_pages_count": len(clean_pages),
        "page_layout": page_layout,
        "region_text": region_text,
        "packets": packets,
        "aligned_answers": aligned,
        "final_output": final_rows,
    }


def pipeline_result_to_question_map(pipeline_result: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    """Convert pipeline packets into the question map contract used by grading service."""
    packets = (pipeline_result or {}).get("packets", {}) or {}
    out: Dict[int, Dict[str, Any]] = {}
    for qn, pkt in packets.items():
        if not isinstance(qn, int):
            continue
        text_blocks = pkt.get("text_blocks", []) or []
        segments = [
            {
                "segment_id": blk.get("block_id"),
                "page": blk.get("page_number"),
                "text": blk.get("text", ""),
                "x1": (blk.get("bbox") or [0, 0, 0, 0])[0],
                "y1": (blk.get("bbox") or [0, 0, 0, 0])[1],
                "x2": (blk.get("bbox") or [0, 0, 0, 0])[2],
                "y2": (blk.get("bbox") or [0, 0, 0, 0])[3],
                "tables": [{}] if blk.get("is_table") else [],
            }
            for blk in text_blocks
        ]
        out[int(qn)] = {
            "question_number": int(qn),
            "segments": segments,
            "subquestions": {s.get("sub_id"): s.get("segment_ids", []) for s in (pkt.get("subanswers") or []) if s.get("sub_id")},
            "subanswers": pkt.get("subanswers", []),
            "page_refs": pkt.get("pages", []),
            "tables": [{"segment_id": sid} for sid in (pkt.get("table_segments", []) or [])],
            "table_segments": pkt.get("table_segments", []),
            "working_note_segments": pkt.get("working_note_segments", []),
            "segment_ids": pkt.get("segment_ids", []),
            "combined_text": pkt.get("combined_text", ""),
            "extracted_text": pkt.get("combined_text", ""),
            "subquestion_count": int(pkt.get("subquestion_count", 0) or 0),
            "mapping_confidence": float(pkt.get("mapping_confidence", 0.0) or 0.0),
            "mapping_trace": pkt.get("mapping_trace", []),
            "start_anchor": pkt.get("start_anchor"),
            "end_anchor": pkt.get("end_anchor"),
        }
    meta = packets.get("_meta", {}) if isinstance(packets, dict) else {}
    out["_meta"] = {
        "mapping_coverage": float(meta.get("mapping_coverage", 0.0) or 0.0),
        "packets_generated": int(meta.get("packets_generated", len([k for k in out.keys() if isinstance(k, int)])) or 0),
        "subpacket_count": int(meta.get("subpacket_count", 0) or 0),
        "low_confidence_questions": meta.get("low_confidence_questions", []),
        "consistency_flags": meta.get("consistency_flags", []),
        "page_segment_index": meta.get("page_segment_index", []),
    }
    return out


__all__ = [
    "PIPELINE_ENABLED",
    "build_question_blueprint_from_exam_questions",
    "normalize_answer_pages",
    "pdf_to_clean_images",
    "detect_page_layout",
    "run_region_ocr",
    "build_packets",
    "align_packets_to_blueprint",
    "structure_accounting_answer",
    "run_answer_packet_pipeline",
    "pipeline_result_to_question_map",
]
