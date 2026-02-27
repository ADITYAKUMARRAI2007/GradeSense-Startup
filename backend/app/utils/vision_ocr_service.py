"""Google Cloud Vision OCR service wrapper."""

import base64
import os
from typing import List, Dict

from app.config import logger


class VisionOCRService:
    """Wrapper around Google Cloud Vision API for text detection."""

    def __init__(self):
        self._client = None
        self._available = False
        self._init_attempted = False

    def _init_client(self):
        """Lazily initialize the Vision client."""
        if self._init_attempted:
            return
        self._init_attempted = True
        try:
            from google.api_core.client_options import ClientOptions
            from google.cloud import vision
            transport = os.getenv("VISION_TRANSPORT", "rest").strip().lower() or "rest"
            client_options = ClientOptions(api_endpoint="vision.googleapis.com")
            self._client = vision.ImageAnnotatorClient(
                client_options=client_options,
                transport=transport
            )
            self._available = True
            logger.info("✅ Google Cloud Vision OCR initialized")
        except Exception as e:
            logger.warning(f"⚠️ Google Cloud Vision not available: {e}")
            self._available = False

    def is_available(self) -> bool:
        self._init_client()
        return self._available

    def detect_text_from_base64(
        self,
        image_base64: str,
        languages: List[str] = None,
        mode: str = "auto",
        handwriting: bool = False,
        min_confidence: float = 0.5,
    ) -> Dict:
        """
        Detect text in a base64-encoded image.

        Args:
            image_base64: JPEG/PNG content in base64.
            languages: language hints for Vision.
            mode: "document" | "text" | "auto" (default tries document, then text).
            handwriting: hint that content is handwritten; toggles Document OCR preference.
            min_confidence: drop words below this confidence (0-1 range).

        Returns a normalized payload:
            {
              "words": [{text,x1,y1,x2,y2,conf,confidence,page}],
              "lines": [{text,x1,y1,x2,y2,conf,confidence,page}],
              "provider": "vision"
            }
        """
        self._init_client()
        if not self._available:
            return {"words": [], "lines": [], "provider": "vision"}

        try:
            from google.cloud import vision

            img_bytes = base64.b64decode(image_base64)
            image = vision.Image(content=img_bytes)

            image_context = vision.ImageContext(language_hints=languages or ["en"])

            def _document_call():
                return self._client.document_text_detection(image=image, image_context=image_context)

            def _text_call():
                return self._client.text_detection(image=image, image_context=image_context)

            response = None
            errors = []

            if mode in ("document", "auto"):
                try:
                    response = _document_call()
                except Exception as doc_err:
                    errors.append(doc_err)
            if response is None and mode in ("text", "auto"):
                try:
                    response = _text_call()
                except Exception as txt_err:
                    errors.append(txt_err)

            if response is None:
                if errors:
                    logger.error(f"Vision OCR error chain: {[str(e) for e in errors]}")
                return {"words": [], "lines": [], "provider": "vision"}

            words = []
            lines = []
            annotation = response.full_text_annotation
            if not annotation:
                return {"words": [], "lines": [], "provider": "vision"}

            for page_idx, page in enumerate(annotation.pages):
                for block in page.blocks:
                    for paragraph in block.paragraphs:
                        paragraph_words = []
                        for word in paragraph.words:
                            text = "".join([s.text for s in word.symbols])
                            vertices = word.bounding_box.vertices
                            confidence = getattr(word, "confidence", 0.0) or 0.0
                            if confidence < min_confidence:
                                continue
                            if not vertices:
                                continue
                            item = {
                                "text": text,
                                "x1": vertices[0].x,
                                "y1": vertices[0].y,
                                "x2": vertices[2].x,
                                "y2": vertices[2].y,
                                "conf": confidence,
                                "confidence": confidence,
                                "page": page_idx + 1,
                            }
                            words.append(item)
                            paragraph_words.append(item)

                        if paragraph_words:
                            xs = [w["x1"] for w in paragraph_words] + [w["x2"] for w in paragraph_words]
                            ys = [w["y1"] for w in paragraph_words] + [w["y2"] for w in paragraph_words]
                            text = " ".join(w["text"] for w in paragraph_words).strip()
                            line_conf = sum(w.get("conf", 0.0) for w in paragraph_words) / max(1, len(paragraph_words))
                            lines.append({
                                "text": text,
                                "x1": min(xs),
                                "y1": min(ys),
                                "x2": max(xs),
                                "y2": max(ys),
                                "conf": line_conf,
                                "confidence": line_conf,
                                "page": page_idx + 1,
                            })

            return {"words": words, "lines": lines, "provider": "vision"}

        except Exception as e:
            logger.error(f"Vision OCR error: {e}")
            return {"words": [], "lines": [], "provider": "vision"}


# Singleton instance
_service = VisionOCRService()


def get_vision_service() -> VisionOCRService:
    return _service
