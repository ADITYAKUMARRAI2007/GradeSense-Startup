import sys, base64, io
sys.path.insert(0, 'backend')
from PIL import Image
from app.services.annotation import generate_annotated_images_with_vision_ocr
from app.models.submission import QuestionScore

# make blank image
img = Image.new('RGB', (800,1200), (255,255,255))
buf = io.BytesIO(); img.save(buf, format='JPEG')
img_b64 = base64.b64encode(buf.getvalue()).decode()

words = [
    {"text": "Q1.", "x1": 40, "y1": 120, "x2": 80, "y2": 140},
    {"text": "Describe", "x1": 90, "y1": 120, "x2": 220, "y2": 140},
    {"text": "the", "x1": 230, "y1": 120, "x2": 260, "y2": 140},
    {"text": "process", "x1": 270, "y1": 120, "x2": 360, "y2": 140},
    {"text": "Answer", "x1": 60, "y1": 200, "x2": 240, "y2": 220},
]

class FakeVision:
    def is_available(self):
        return True
    def detect_text_from_base64(self, image_base64, languages=None):
        return {'words': words}

import app.services.annotation as ann_mod
ann_mod.get_vision_service = lambda: FakeVision()

qs = QuestionScore(question_number=1, max_marks=10, obtained_marks=8, ai_feedback='ok', page_number=1)

import asyncio
annotated = asyncio.get_event_loop().run_until_complete(
    generate_annotated_images_with_vision_ocr([img_b64], [qs], use_vision_ocr=True)
)
print('generated', type(annotated), len(annotated))
from PIL import Image
img2 = Image.open(io.BytesIO(base64.b64decode(annotated[0]))).convert('RGB')
w,h = img2.size
place_x = min(80 + 60, w - 48)
text_x = min(place_x + 34, w - 140)
mid_y = (120 + 140)//2
text_y = max(8, mid_y - 12)
print('expected text coords', text_x, text_y)
box = (int(text_x)-8, int(text_y)-8, int(text_x)+32, int(text_y)+8)
box = (max(0,box[0]), max(0,box[1]), min(w,box[2]), min(h,box[3]))
print('sample box', box)
px = img2.crop(box).getdata()
nonwhite = any(p != (255,255,255) for p in px)
print('non-white found near expected location?', nonwhite)
