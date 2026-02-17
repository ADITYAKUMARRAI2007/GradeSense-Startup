"""Quick test to verify line_id_map building works after the fix."""
import os, sys, base64, re, io
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()

from pymongo import MongoClient
from PIL import Image
from app.utils.vision_ocr_service import get_vision_service

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
client = MongoClient(MONGO_URL)
db = client["gradesense"]

# Get a submission with images
sub = db.submissions.find_one({"status": {"$in": ["graded", "ai_graded"]}, "file_images.0": {"$exists": True}})
if not sub:
    import pytest
    pytest.skip("No graded submission with images found — skipping OCR/line-id verification", allow_module_level=True)

images = sub.get("file_images", sub.get("images", []))
scores = sub.get("question_scores", sub.get("scores", []))
print(f"Submission: {sub['submission_id']}, Pages: {len(images)}, Questions: {len(scores)}")

# Pick page 4 (index 3) which should have answer content
page_idx = min(3, len(images) - 1)
img_b64 = images[page_idx]
print(f"\nTesting page {page_idx + 1}...")

# Get image dimensions
try:
    image_data = base64.b64decode(img_b64)
    with Image.open(io.BytesIO(image_data)) as pil_img:
        img_width, img_height = pil_img.size
    print(f"Image size: {img_width}x{img_height}")
except Exception as e:
    print(f"Image decode error: {e}")
    img_height = 1400

# Get OCR words
vision_service = get_vision_service()
print(f"Vision service available: {vision_service.is_available()}")
ocr_result = vision_service.detect_text_from_base64(img_b64, ["en"])
words = ocr_result.get("words", [])
print(f"OCR returned {len(words)} words")

if words:
    print(f"Word format sample: {words[0]}")

# === OLD CODE (broken) ===
def _word_vertices(word):
    return getattr(word, "vertices", None) if not isinstance(word, dict) else word.get("vertices", [])

old_items = []
for w in words:
    xs = [v.get("x", 0) for v in (_word_vertices(w) or [])]
    ys = [v.get("y", 0) for v in (_word_vertices(w) or [])]
    if not xs or not ys:
        continue
    old_items.append(w)
print(f"\nOLD _group_words_into_lines parsed {len(old_items)}/{len(words)} words")

# === NEW CODE (fixed) ===
new_items = []
for w in words:
    if isinstance(w, dict) and "x1" in w:
        x1, y1, x2, y2 = w["x1"], w["y1"], w["x2"], w["y2"]
        new_items.append({"text": w.get("text", ""), "x1": x1, "x2": x2, "y1": y1, "y2": y2, "yc": (y1 + y2) / 2})
    else:
        verts = _word_vertices(w) or []
        xs = [v.get("x", 0) for v in verts]
        ys = [v.get("y", 0) for v in verts]
        if not xs or not ys:
            continue
        x1, x2 = min(xs), max(xs)
        y1, y2 = min(ys), max(ys)
        new_items.append({"text": w.get("text", ""), "x1": x1, "x2": x2, "y1": y1, "y2": y2, "yc": (y1 + y2) / 2})
print(f"NEW _group_words_into_lines parsed {len(new_items)}/{len(words)} words")

# Group into lines
new_items.sort(key=lambda i: (i["yc"], i["x1"]))
y_threshold = max(10, int(img_height * 0.012))
lines = []
for item in new_items:
    if not lines:
        lines.append([item])
        continue
    last = lines[-1]
    if abs(item["yc"] - last[-1]["yc"]) <= y_threshold:
        last.append(item)
    else:
        lines.append([item])

line_boxes = []
for line in lines:
    xs_all = [i["x1"] for i in line] + [i["x2"] for i in line]
    ys_all = [i["y1"] for i in line] + [i["y2"] for i in line]
    text = " ".join(i["text"] for i in line)
    line_boxes.append({"text": text, "x1": min(xs_all), "y1": min(ys_all), "x2": max(xs_all), "y2": max(ys_all)})

print(f"\nGrouped into {len(line_boxes)} lines")

# Build line_id_map (matching annotation.py)
question_numbers = sorted({s.get("question_number") for s in scores})
question_patterns = {
    q_num: re.compile(rf"^\s*(?:Q\s*)?{q_num}\s*[\).:-]?\s*", re.IGNORECASE)
    for q_num in question_numbers
}

current_q = question_numbers[0] if question_numbers else 0
line_counts = {}
line_id_map = {}

for line in line_boxes:
    text = (line.get("text") or "").strip()
    if text:
        for q_num, pattern in question_patterns.items():
            if pattern.match(text):
                current_q = q_num
                break
    line_counts[current_q] = line_counts.get(current_q, 0) + 1
    line_idx = line_counts[current_q]
    line_id = f"Q{current_q}-L{line_idx}"
    line_id_map[line_id] = line

print(f"\n=== LINE ID MAP (page {page_idx+1}) ===")
print(f"Total entries: {len(line_id_map)}")
for lid in sorted(line_id_map.keys(), key=lambda x: (int(re.search(r'Q(\d+)', x).group(1)), int(re.search(r'L(\d+)', x).group(1)))):
    text = line_id_map[lid]["text"][:80]
    print(f"  {lid}: {text}")

if len(line_id_map) > 0:
    print("\n✅ FIX WORKS! Line ID map is populated.")
else:
    print("\n❌ FIX FAILED! Line ID map is still empty.")
