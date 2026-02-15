"""
Google Cloud Vision OCR service wrapper.
Provides text detection from images for precise annotation positioning.
"""

import base64
from typing import List, Dict, Optional

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
            from google.cloud import vision
            self._client = vision.ImageAnnotatorClient()
            self._available = True
            logger.info("✅ Google Cloud Vision OCR initialized")
        except Exception as e:
            logger.warning(f"⚠️ Google Cloud Vision not available: {e}")
            self._available = False

    def is_available(self) -> bool:
        self._init_client()
        return self._available

    def detect_text_from_base64(self, image_base64: str, languages: List[str] = None) -> Dict:
        """
        Detect text in a base64-encoded image.
        Returns dict with 'words' list, each having 'text', 'x1', 'y1', 'x2', 'y2'.
        """
        self._init_client()
        if not self._available:
            return {"words": []}

        try:
            from google.cloud import vision

            img_bytes = base64.b64decode(image_base64)
            image = vision.Image(content=img_bytes)

            context = None
            if languages:
                context = vision.ImageContext(language_hints=languages)

            response = self._client.text_detection(image=image, image_context=context)

            words = []
            for page in response.full_text_annotation.pages:
                for block in page.blocks:
                    for paragraph in block.paragraphs:
                        for word in paragraph.words:
                            text = "".join([s.text for s in word.symbols])
                            vertices = word.bounding_box.vertices
                            words.append({
                                "text": text,
                                "x1": vertices[0].x,
                                "y1": vertices[0].y,
                                "x2": vertices[2].x,
                                "y2": vertices[2].y,
                            })

            return {"words": words}

        except Exception as e:
            logger.error(f"Vision OCR error: {e}")
            return {"words": []}


# Singleton instance
_service = VisionOCRService()


def get_vision_service() -> VisionOCRService:
    return _service
