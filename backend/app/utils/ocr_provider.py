import base64
import hashlib
import io
import os
import time
from typing import Dict, List, Any, Tuple

from PIL import Image

from app.config import logger
from app.utils.vision_ocr_service import get_vision_service


class OCRProvider:
    def __init__(self):
        self._vision = get_vision_service()
        self._cache: Dict[str, Dict[str, Any]] = {}
        # Accountancy pipeline default: PaddleOCR first, Vision fallback.
        # If Paddle is unavailable, init logic below safely downgrades to vision.
        self.primary = (os.getenv("OCR_PRIMARY", "paddle").strip().lower() or "paddle")
        self.fallback = (os.getenv("OCR_FALLBACK", "vision").strip().lower() or "vision")
        self._paddle = None
        self._paddle_error = ""
        self.min_conf_default = float(os.getenv("OCR_MIN_CONF", "0.5"))
        self.min_words_default = int(os.getenv("OCR_MIN_WORDS", "20"))
        self.min_lines_default = int(os.getenv("OCR_MIN_LINES", "5"))
        self.enable_tables = os.getenv("OCR_ENABLE_TABLES", "true").lower() in ("1", "true", "yes", "on")
        self.table_min_lines = int(os.getenv("OCR_TABLE_MIN_LINES", "8"))
        self.fallback_only_if_empty = os.getenv("OCR_FALLBACK_ONLY_IF_EMPTY", "true").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

        # Lazy/guarded Paddle init so backend can still boot in vision-only mode.
        if self.primary == "paddle" or self.fallback == "paddle":
            try:
                from app.utils.paddle_service import get_paddle_service  # local import by design
                self._paddle = get_paddle_service()
            except Exception as e:
                self._paddle_error = str(e)
                logger.warning(
                    "PaddleOCR unavailable (%s). Falling back to vision-only OCR.",
                    self._paddle_error,
                )
                if self.primary == "paddle":
                    self.primary = "vision"
                if self.fallback == "paddle":
                    self.fallback = ""

    @staticmethod
    def _hash(image_base64: str, min_conf: float, min_words: int, min_lines: int) -> str:
        raw = f"{min_conf:.3f}|{min_words}|{min_lines}|{image_base64}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    @staticmethod
    def _norm_item(item: Dict[str, Any], page: int = 1) -> Dict[str, Any]:
        conf = float(item.get("conf", item.get("confidence", 0.0)) or 0.0)
        return {
            "text": str(item.get("text", "")).strip(),
            "x1": float(item.get("x1", 0.0)),
            "y1": float(item.get("y1", 0.0)),
            "x2": float(item.get("x2", 0.0)),
            "y2": float(item.get("y2", 0.0)),
            "conf": conf,
            "confidence": conf,
            "page": int(item.get("page", page) or page),
            "line_id": item.get("line_id"),
        }

    def _decode_dims(self, image_base64: str) -> Tuple[int, int]:
        img_bytes = base64.b64decode(image_base64)
        with Image.open(io.BytesIO(img_bytes)) as im:
            return im.size

    @staticmethod
    def _merge_tokens(primary: List[Dict[str, Any]], secondary: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not primary and not secondary:
            return []
        merged: Dict[str, Dict[str, Any]] = {}
        for item in primary + secondary:
            text = str(item.get("text", "")).strip().lower()
            x1 = int(round(float(item.get("x1", 0.0))))
            y1 = int(round(float(item.get("y1", 0.0))))
            x2 = int(round(float(item.get("x2", 0.0))))
            y2 = int(round(float(item.get("y2", 0.0))))
            key = f"{text}|{x1}|{y1}|{x2}|{y2}"
            existing = merged.get(key)
            if existing is None or float(item.get("conf", 0.0)) > float(existing.get("conf", 0.0)):
                merged[key] = item
        out = list(merged.values())
        out.sort(key=lambda i: (float(i.get("y1", 0.0)), float(i.get("x1", 0.0))))
        return out

    def _call_vision(self, image_base64: str, min_conf: float) -> Dict[str, Any]:
        start = time.time()
        res = self._vision.detect_text_from_base64(
            image_base64=image_base64,
            languages=["en"],
            mode="auto",
            handwriting=True,
            min_confidence=min_conf,
        )
        words = [self._norm_item(w) for w in (res.get("words") or []) if str(w.get("text", "")).strip()]
        lines = [self._norm_item(l) for l in (res.get("lines") or []) if str(l.get("text", "")).strip()]
        return {
            "words": words,
            "lines": lines,
            "tables": [],
            "provider": "vision",
            "latency_ms": int((time.time() - start) * 1000),
        }

    def _call_paddle(self, image_base64: str) -> Dict[str, Any]:
        start = time.time()
        if self._paddle is None:
            raise RuntimeError(f"PaddleOCR unavailable: {self._paddle_error or 'not initialized'}")
        logger.info("[OCR] starting paddle text OCR")
        text_res = self._paddle.detect_text_from_base64(image_base64)
        words = [self._norm_item(w) for w in (text_res.get("words") or []) if str(w.get("text", "")).strip()]
        lines = [self._norm_item(l) for l in (text_res.get("lines") or []) if str(l.get("text", "")).strip()]
        logger.info("[OCR] paddle text complete: words=%s lines=%s", len(words), len(lines))
        tables: List[Dict[str, Any]] = []
        if self.enable_tables and self._should_extract_tables(lines):
            logger.info("[OCR] running paddle structure/table extraction")
            struct_res = self._paddle.detect_structure_from_base64(image_base64)
            tables = struct_res.get("tables") or []
            logger.info("[OCR] paddle table extraction complete: tables=%s", len(tables))
        return {
            "words": words,
            "lines": lines,
            "tables": tables,
            "provider": "paddle",
            "latency_ms": int((time.time() - start) * 1000),
        }

    def _should_extract_tables(self, lines: List[Dict[str, Any]]) -> bool:
        if len(lines) < self.table_min_lines:
            return False
        probe = " ".join((l.get("text", "") or "").lower() for l in lines[:40])
        keywords = (
            "particulars", "ledger", "journal", "debit", "credit", "dr", "cr",
            "balance", "capital", "trial", "account"
        )
        return any(k in probe for k in keywords)

    def detect(
        self,
        image_base64: str,
        min_conf: float = None,
        min_words: int = None,
        min_lines: int = None,
        force_fallback: bool = False,
        allow_fallback: bool = True,
    ) -> Dict[str, Any]:
        min_conf = self.min_conf_default if min_conf is None else min_conf
        min_words = self.min_words_default if min_words is None else min_words
        min_lines = self.min_lines_default if min_lines is None else min_lines

        cache_key = self._hash(image_base64, min_conf, min_words, min_lines)
        if cache_key in self._cache:
            return self._cache[cache_key]

        width, height = self._decode_dims(image_base64)
        metrics = {
            "primary": self.primary,
            "fallback": self.fallback,
            "min_conf": min_conf,
            "min_words": min_words,
            "min_lines": min_lines,
            "tried": [],
        }

        primary_res = {"words": [], "lines": [], "tables": [], "provider": self.primary, "latency_ms": 0}
        fallback_res = {"words": [], "lines": [], "tables": [], "provider": self.fallback, "latency_ms": 0}
        fallback_used = False

        def call(name: str) -> Dict[str, Any]:
            if name == "vision":
                return self._call_vision(image_base64, min_conf=min_conf)
            if name == "paddle":
                return self._call_paddle(image_base64)
            return {"words": [], "lines": [], "tables": [], "provider": name, "latency_ms": 0}

        try:
            primary_res = call(self.primary)
        except Exception as e:
            logger.warning(f"Primary OCR '{self.primary}' failed: {e}")
            primary_res = {"words": [], "lines": [], "tables": [], "provider": self.primary, "latency_ms": 0}
        metrics["tried"].append({
            "provider": primary_res.get("provider"),
            "words": len(primary_res.get("words") or []),
            "lines": len(primary_res.get("lines") or []),
            "latency_ms": primary_res.get("latency_ms", 0),
        })

        primary_words = len(primary_res.get("words") or [])
        primary_lines = len(primary_res.get("lines") or [])
        
        # Determine if fallback is needed
        if force_fallback:
            # Always use fallback when explicitly requested
            needs_fallback = True
        elif self.fallback_only_if_empty:
            # Only fallback if completely empty (0 words AND 0 lines)
            needs_fallback = (primary_words == 0 and primary_lines == 0)
        else:
            # Fallback if below thresholds
            needs_fallback = (primary_words < min_words and primary_lines < min_lines)
        
        logger.info(
            "[OCR] primary=%s words=%s lines=%s thresholds=(%s,%s) only_if_empty=%s force_fallback=%s fallback_needed=%s",
            self.primary,
            primary_words,
            primary_lines,
            min_words,
            min_lines,
            self.fallback_only_if_empty,
            force_fallback,
            needs_fallback,
        )

        # Execute fallback if needed and available
        if allow_fallback and needs_fallback and self.fallback and self.fallback != self.primary:
            fallback_used = True
            logger.info("[OCR] invoking fallback provider=%s", self.fallback)
            try:
                fallback_res = call(self.fallback)
            except Exception as e:
                logger.warning(f"Fallback OCR '{self.fallback}' failed: {e}")
                fallback_res = {"words": [], "lines": [], "tables": [], "provider": self.fallback, "latency_ms": 0}
            metrics["tried"].append({
                "provider": fallback_res.get("provider"),
                "words": len(fallback_res.get("words") or []),
                "lines": len(fallback_res.get("lines") or []),
                "latency_ms": fallback_res.get("latency_ms", 0),
            })

        words = self._merge_tokens(primary_res.get("words") or [], fallback_res.get("words") or [])
        lines = self._merge_tokens(primary_res.get("lines") or [], fallback_res.get("lines") or [])
        tables = (primary_res.get("tables") or []) + (fallback_res.get("tables") or [])
        provider = primary_res.get("provider", self.primary)
        if fallback_used and len(fallback_res.get("words") or []) > len(primary_res.get("words") or []):
            provider = fallback_res.get("provider", self.fallback)
        if fallback_used and words and lines:
            provider = f"{self.primary}+{self.fallback}"

        result = {
            "words": words,
            "lines": lines,
            "tables": tables,
            "provider": provider,
            "fallback_used": fallback_used,
            "width": width,
            "height": height,
            "metrics": metrics,
        }

        self._cache[cache_key] = result
        logger.info(
            "[OCR] provider=%s fallback=%s words=%s lines=%s tables=%s",
            provider,
            fallback_used,
            len(words),
            len(lines),
            len(tables),
        )
        return result


_provider = OCRProvider()


def get_ocr_provider() -> OCRProvider:
    return _provider
