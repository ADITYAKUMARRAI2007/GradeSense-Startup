from app.services.annotation import generate_annotated_images
from app.models.submission import QuestionScore
from PIL import Image, ImageDraw, ImageFont
import base64, io, os

# create a sample page image
img = Image.new('RGB', (900, 1200), 'white')
d = ImageDraw.Draw(img)
try:
    f = ImageFont.load_default()
except Exception:
    f = None
# draw visual sections to emulate answers
for i, y in enumerate(range(60, 900, 160), start=1):
    d.rectangle([(60, y-30),(820, y+100)], outline=(200,200,200))
    d.text((80, y), f"Q{i} sample answer line 1", fill=(0,0,0), font=f)
    d.text((80, y+24), "More answer text...", fill=(0,0,0), font=f)
    d.text((80, y+48), "Concluding sentence.", fill=(0,0,0), font=f)

buf = io.BytesIO()
img.save(buf, format='JPEG', quality=90)
img_b64 = base64.b64encode(buf.getvalue()).decode()

# create question scores (page_number is 1-indexed)
qs = [
    QuestionScore(question_number=1, max_marks=5, obtained_marks=5, ai_feedback="", page_number=1, annotations=[]),
    QuestionScore(question_number=2, max_marks=10, obtained_marks=4, ai_feedback="", page_number=1, annotations=[]),
    QuestionScore(question_number=3, max_marks=8, obtained_marks=7, ai_feedback="", page_number=1, annotations=[]),
]

out = generate_annotated_images([img_b64], qs)
out_path = '/tmp/annotated_qscores_test.jpg'
with open(out_path, 'wb') as fh:
    fh.write(base64.b64decode(out[0]))
print('WROTE', out_path)
