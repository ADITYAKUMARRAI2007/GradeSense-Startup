"""Phase 2: answer-sheet normalization for college V2 pipeline."""

from __future__ import annotations

import base64
import io
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np
from pdf2image import convert_from_bytes


def _b64_to_cv2(image_base64: str) -> np.ndarray:
    data = base64.b64decode(image_base64)
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Failed to decode base64 image")
    return img


def _cv2_to_b64(img: np.ndarray, quality: int = 88) -> str:
    ok, enc = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise ValueError("Failed to encode image")
    return base64.b64encode(enc.tobytes()).decode()


def _detect_margin_ratio(binary_inv: np.ndarray) -> float:
    h, w = binary_inv.shape[:2]
    border = max(8, int(min(h, w) * 0.02))
    mask = np.zeros_like(binary_inv)
    mask[:border, :] = 255
    mask[-border:, :] = 255
    mask[:, :border] = 255
    mask[:, -border:] = 255
    border_pixels = cv2.countNonZero(cv2.bitwise_and(binary_inv, mask))
    total_border = max(1, cv2.countNonZero(mask))
    return round(border_pixels / float(total_border), 4)


def normalize_answer_pages(answer_images: List[str]) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Normalize already-rendered answer images and return metrics."""
    clean_pages: List[str] = []
    metrics: List[Dict[str, Any]] = []

    for idx, image_b64 in enumerate(answer_images or [], start=1):
        page_metric: Dict[str, Any] = {
            "page": idx,
            "ok": True,
            "width": 0,
            "height": 0,
            "skew_angle": 0.0,
            "shadow_removed": False,
            "margin_ratio": 0.0,
            "contrast_gain": 0.0,
        }
        try:
            bgr = _b64_to_cv2(image_b64)
            h, w = bgr.shape[:2]
            page_metric["width"] = int(w)
            page_metric["height"] = int(h)

            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            gray_std = float(np.std(gray))

            # Shadow suppression by background normalization.
            blur = cv2.GaussianBlur(gray, (3, 3), 0)
            bg = cv2.medianBlur(blur, 25)
            norm = cv2.divide(blur, bg, scale=255)
            page_metric["shadow_removed"] = True

            # Contrast enhancement.
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(norm)
            enh_std = float(np.std(enhanced))
            if gray_std > 0:
                page_metric["contrast_gain"] = round(enh_std / gray_std, 4)

            # Deskew from dominant foreground angle.
            th = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
            coords = cv2.findNonZero(th)
            angle = 0.0
            if coords is not None and len(coords) > 500:
                angle = float(cv2.minAreaRect(coords)[-1])
                if angle < -45:
                    angle = 90 + angle
                if abs(angle) > 0.1:
                    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
                    enhanced = cv2.warpAffine(
                        enhanced,
                        m,
                        (w, h),
                        flags=cv2.INTER_CUBIC,
                        borderMode=cv2.BORDER_REPLICATE,
                    )
                    th = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
            page_metric["skew_angle"] = round(angle, 3)
            page_metric["margin_ratio"] = _detect_margin_ratio(th)

            out = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)
            clean_pages.append(_cv2_to_b64(out, quality=88))
        except Exception:
            page_metric["ok"] = False
            clean_pages.append(image_b64)
        metrics.append(page_metric)

    return clean_pages, metrics


def pdf_to_clean_pages(pdf_bytes: bytes, dpi: int = 300) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Render PDF at fixed DPI and normalize pages."""
    rendered: List[str] = []
    pages = convert_from_bytes(pdf_bytes, dpi=dpi, fmt="jpeg")
    for page in pages:
        buf = io.BytesIO()
        page.save(buf, format="JPEG", quality=88, optimize=True)
        rendered.append(base64.b64encode(buf.getvalue()).decode())
    return normalize_answer_pages(rendered)


__all__ = ["normalize_answer_pages", "pdf_to_clean_pages"]
