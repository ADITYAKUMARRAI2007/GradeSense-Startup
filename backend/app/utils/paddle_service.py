"""Paddle OCR service wrapper with optional table structure extraction."""

import base64
import io
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Dict, List, Any

import numpy as np
from PIL import Image

from app.config import logger


class PaddleOCRService:
    def __init__(self):
        self._ocr = None
        self._structure = None
        self._available = False
        self._init_attempted = False
        self._text_executor: ThreadPoolExecutor | None = None
        self._timeout_sec = float(os.getenv("PADDLE_OCR_TIMEOUT_SEC", "12"))
        self._init_timeout_sec = float(os.getenv("PADDLE_INIT_TIMEOUT_SEC", "12"))

    def _init_clients(self) -> None:
        if self._init_attempted:
            return
        self._init_attempted = True

        def _construct_clients():
            from paddleocr import PaddleOCR

            use_angle_cls = os.getenv("PADDLE_USE_ANGLE_CLS", "true").lower() in ("1", "true", "yes", "on")
            lang = os.getenv("PADDLE_LANG", "en").strip() or "en"
            paddle_kwargs: Dict[str, Any] = {
                "use_angle_cls": use_angle_cls,
                "lang": lang,
                "show_log": False,
            }
            # Optional local model paths to avoid runtime downloads.
            for env_key, arg_key in (
                ("PADDLE_DET_MODEL_DIR", "det_model_dir"),
                ("PADDLE_REC_MODEL_DIR", "rec_model_dir"),
                ("PADDLE_CLS_MODEL_DIR", "cls_model_dir"),
            ):
                value = (os.getenv(env_key) or "").strip()
                if value:
                    paddle_kwargs[arg_key] = value

            ocr = PaddleOCR(**paddle_kwargs)
            structure = None

            enable_tables = os.getenv("OCR_ENABLE_TABLES", "true").lower() in ("1", "true", "yes", "on")
            if enable_tables:
                try:
                    try:
                        # paddleocr>=2.7 exposes PPStructure at top level.
                        from paddleocr import PPStructure  # type: ignore
                    except Exception:
                        # Keep compatibility with alternate package layouts.
                        from paddleocr.ppstructure.predict_system import PPStructure  # type: ignore
                    structure_kwargs: Dict[str, Any] = {"show_log": False}
                    value = (os.getenv("PADDLE_TABLE_MODEL_DIR") or "").strip()
                    if value:
                        structure_kwargs["table_model_dir"] = value
                    structure = PPStructure(**structure_kwargs)
                except Exception as e:
                    logger.warning(f"PPStructure unavailable, continuing without tables: {e}")
            return ocr, structure

        try:
            if self._init_timeout_sec > 0:
                init_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="paddle-init")
                try:
                    future = init_executor.submit(_construct_clients)
                    self._ocr, self._structure = future.result(timeout=self._init_timeout_sec)
                except FuturesTimeoutError:
                    logger.error(
                        "PaddleOCR initialization timed out after %.1fs; disabling paddle provider",
                        self._init_timeout_sec,
                    )
                    self._available = False
                    self._ocr = None
                    self._structure = None
                    return
                finally:
                    init_executor.shutdown(wait=False, cancel_futures=True)
            else:
                self._ocr, self._structure = _construct_clients()

            self._available = True
            self._text_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="paddle-ocr")
            logger.info("✅ PaddleOCR initialized")
            if self._structure is not None:
                logger.info("✅ PaddleOCR PPStructure initialized")
        except Exception as e:
            self._available = False
            self._ocr = None
            self._structure = None
            if self._text_executor is not None:
                self._text_executor.shutdown(wait=False, cancel_futures=True)
                self._text_executor = None
            logger.warning(f"⚠️ PaddleOCR not available: {e}")

    def is_available(self) -> bool:
        self._init_clients()
        return self._available

    def _decode_image(self, image_base64: str):
        img_bytes = base64.b64decode(image_base64)
        pil_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        max_side = int(os.getenv("PADDLE_MAX_SIDE", "1800"))
        if max_side > 0:
            w, h = pil_img.size
            longest = max(w, h)
            if longest > max_side:
                scale = max_side / float(longest)
                pil_img = pil_img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        # PaddleOCR/PPStructure expect OpenCV-style ndarray input.
        np_img = np.ascontiguousarray(np.array(pil_img)[:, :, ::-1])  # RGB -> BGR
        return pil_img, np_img

    @staticmethod
    def _bbox_from_points(points: List[List[float]]) -> List[float]:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return [min(xs), min(ys), max(xs), max(ys)]

    def detect_text_from_base64(self, image_base64: str) -> Dict[str, Any]:
        self._init_clients()
        if not self._available or self._ocr is None:
            return {"words": [], "lines": [], "provider": "paddle", "reason": "unavailable"}

        try:
            pil_img, np_img = self._decode_image(image_base64)
            width, height = pil_img.size
            if self._timeout_sec > 0:
                if self._text_executor is None:
                    self._text_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="paddle-ocr")
                future = self._text_executor.submit(self._ocr.ocr, np_img, cls=True)
                try:
                    result = future.result(timeout=self._timeout_sec)
                except FuturesTimeoutError:
                    logger.error(
                        "PaddleOCR text detection timed out after %.1fs; disabling paddle provider for this process",
                        self._timeout_sec,
                    )
                    self._available = False
                    self._ocr = None
                    if self._text_executor is not None:
                        self._text_executor.shutdown(wait=False, cancel_futures=True)
                        self._text_executor = None
                    return {"words": [], "lines": [], "provider": "paddle", "reason": "timeout"}
            else:
                result = self._ocr.ocr(np_img, cls=True)

            words: List[Dict[str, Any]] = []
            lines: List[Dict[str, Any]] = []
            ocr_items: List[Any] = []
            if isinstance(result, list) and result:
                first = result[0]
                if isinstance(first, list):
                    ocr_items = first
                else:
                    ocr_items = result

            for line_idx, line_item in enumerate(ocr_items, start=1):
                if not isinstance(line_item, (list, tuple)) or len(line_item) < 2:
                    continue
                points, payload = line_item[0], line_item[1]
                if not isinstance(payload, (list, tuple)) or len(payload) < 2:
                    continue
                text = str(payload[0] or "").strip()
                conf = float(payload[1] or 0.0)
                if not text:
                    continue
                x1, y1, x2, y2 = self._bbox_from_points(points)
                lines.append({
                    "text": text,
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "conf": conf,
                    "confidence": conf,
                    "page": 1,
                    "line_id": f"L{line_idx}",
                })
                tokens = text.split()
                if len(tokens) <= 1:
                    words.append({
                        "text": text,
                        "x1": x1,
                        "y1": y1,
                        "x2": x2,
                        "y2": y2,
                        "conf": conf,
                        "confidence": conf,
                        "page": 1,
                    })
                else:
                    token_w = max(1.0, (x2 - x1) / max(1, len(tokens)))
                    cursor = x1
                    for tok in tokens:
                        tok_w = token_w * max(1, len(tok) / 4)
                        words.append({
                            "text": tok,
                            "x1": cursor,
                            "y1": y1,
                            "x2": min(x2, cursor + tok_w),
                            "y2": y2,
                            "conf": conf,
                            "confidence": conf,
                            "page": 1,
                        })
                        cursor = min(x2, cursor + tok_w + 2)

            return {
                "words": words,
                "lines": lines,
                "provider": "paddle",
                "width": width,
                "height": height,
            }
        except Exception as e:
            logger.error(f"PaddleOCR text detection failed: {type(e).__name__}: {e!r}")
            return {"words": [], "lines": [], "provider": "paddle", "reason": str(e)}

    def detect_structure_from_base64(self, image_base64: str) -> Dict[str, Any]:
        self._init_clients()
        if not self._available or self._structure is None:
            return {"tables": [], "provider": "paddle"}

        try:
            _, np_img = self._decode_image(image_base64)
            structure = self._structure(np_img)
            tables: List[Dict[str, Any]] = []
            for item in structure or []:
                if str(item.get("type", "")).lower() != "table":
                    continue
                bbox = item.get("bbox") or [0, 0, 0, 0]
                cells = []
                html = (item.get("res") or {}).get("html", "")
                # Keep structure minimal and deterministic for downstream usage.
                cells.append({
                    "row": 1,
                    "col": 1,
                    "text": html[:5000],
                    "bbox": bbox,
                    "conf": 1.0,
                })
                tables.append({
                    "bbox": bbox,
                    "page": 1,
                    "cells": cells,
                })
            return {"tables": tables, "provider": "paddle"}
        except Exception as e:
            logger.warning(f"Paddle structure detection failed: {type(e).__name__}: {e!r}")
            return {"tables": [], "provider": "paddle", "reason": str(e)}


_service = PaddleOCRService()


def get_paddle_service() -> PaddleOCRService:
    return _service
