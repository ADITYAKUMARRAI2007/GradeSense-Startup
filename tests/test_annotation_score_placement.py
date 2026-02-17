import base64
import io
from PIL import Image

from app.services.annotation import generate_annotated_images_with_vision_ocr
from app.models.submission import QuestionScore


def _make_blank_image(w=800, h=1200, color=(255, 255, 255)):
    img = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return base64.b64encode(buf.getvalue()).decode()


class _FakeVisionService:
    def __init__(self, words):
        self._words = words

    def is_available(self):
        return True

    def detect_text_from_base64(self, image_base64: str, languages=None):
        return {"words": self._words}


def test_score_circle_placed_next_to_question_start(monkeypatch):
    """Ensure SCORE_CIRCLE + MARGIN_NOTE are placed beside the question START (Qn) line."""
    # Create blank image
    img_b64 = _make_blank_image(800, 1200)

    # Fake OCR words: header 'Q1.' at top, followed by answer text lines
    words = [
        {"text": "Q1.", "x1": 40, "y1": 120, "x2": 80, "y2": 140},
        {"text": "Describe", "x1": 90, "y1": 120, "x2": 220, "y2": 140},
        {"text": "the", "x1": 230, "y1": 120, "x2": 260, "y2": 140},
        {"text": "process", "x1": 270, "y1": 120, "x2": 360, "y2": 140},
        {"text": "Answer", "x1": 60, "y1": 200, "x2": 240, "y2": 220},
        {"text": "continues", "x1": 60, "y1": 230, "x2": 300, "y2": 250},
    ]

    # Monkeypatch vision service used inside annotation module
    from app.services import annotation as ann_mod
    monkeypatch.setattr(ann_mod, "get_vision_service", lambda: _FakeVisionService(words))

    # Build QuestionScore for Q1 on page 1
    qs = QuestionScore(question_number=1, max_marks=10, obtained_marks=8, ai_feedback="ok", page_number=1)

    # Generate annotated image (should use OCR and place score near Q1 start)
    annotated = None
    annotated_list = None
    import asyncio

    annotated_list = asyncio.get_event_loop().run_until_complete(
        generate_annotated_images_with_vision_ocr([img_b64], [qs], use_vision_ocr=True)
    )
    assert isinstance(annotated_list, list) and len(annotated_list) == 1
    annotated = annotated_list[0]

    # Decode annotated image and check for non-white pixels near expected MARGIN_NOTE location
    img_bytes = base64.b64decode(annotated)
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    w, h = img.size

    # Calculate expected text coordinates using same heuristics as annotation.py
    # start_line x2 ~= 80 -> place_x = min(80 + 60, w - 48) = 140
    place_x = min(80 + 60, w - 48)
    text_x = min(place_x + 34, w - 140)
    mid_y = (120 + 140) // 2
    text_y = max(8, mid_y - 12)

    # Sample a small box around the expected text location and assert presence of non-white pixels
    found_non_white = False
    sample_box = (int(text_x) - 8, int(text_y) - 8, int(text_x) + 32, int(text_y) + 8)
    sample_box = (
        max(0, sample_box[0]), max(0, sample_box[1]), min(w, sample_box[2]), min(h, sample_box[3])
    )
    pixels = img.crop(sample_box).getdata()
    for px in pixels:
        if px != (255, 255, 255):
            found_non_white = True
            break

    assert found_non_white, f"No annotation pixels found near expected coords {text_x},{text_y}"
