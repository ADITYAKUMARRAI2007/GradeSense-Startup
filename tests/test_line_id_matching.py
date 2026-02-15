#!/usr/bin/env python3
"""Test if line IDs from grading match line IDs during annotation placement"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from app.services.grading import grade_with_ai
from app.services.annotation import generate_annotated_images_with_vision_ocr
from app.services.gridfs_helpers import get_exam_model_answer_images
from app.services.extraction import get_exam_model_answer_text
from app.database import db, fs
from app.utils.vision_ocr_service import VisionOCRService
from bson import ObjectId
import pickle
import re


async def test_line_id_matching():
    """Test end-to-end line ID generation and matching"""
    
    print("\n" + "="*80)
    print("TESTING LINE-ID GRADING → ANNOTATION MATCHING")
    print("="*80 + "\n")
    
    # Get a submission with GridFS images
    sub = await db.submissions.find_one(
        {'images_gridfs_id': {'$exists': True}},
        projection={'_id': 0}
    )
    
    if not sub:
        print("❌ No submissions with GridFS images found")
        return
    
    exam = await db.exams.find_one({'exam_id': sub['exam_id']}, projection={'_id': 0})
    
    print(f"📄 Submission: {sub['submission_id']}")
    print(f"👤 Student: {sub['student_name']}")
    print(f"📝 Exam: {exam['exam_name']}")
    
    # Get answer images
    img_oid = ObjectId(sub['images_gridfs_id'])
    grid_out = fs.get(img_oid)
    answer_images = pickle.loads(grid_out.read())
    
    # Test with ONE page only (page 4 - has actual answers)
    test_page_idx = 3  # Page 4 (0-indexed)
    test_images = [answer_images[test_page_idx]]
    
    print(f"\n🧪 Testing with page {test_page_idx + 1} only")
    print("="*80)
    
    # Get model answer
    model_imgs = await get_exam_model_answer_images(exam['exam_id'])
    model_text = await get_exam_model_answer_text(exam['exam_id'])
    
    # STEP 1: Run grading to get line IDs from Gemini
    print("\n📊 STEP 1: Grading to get line IDs from Gemini...")
    print("-"*80)
    
    scores = await grade_with_ai(
        images=test_images,
        model_answer_images=model_imgs,
        questions=exam.get('questions', [])[:3],  # First 3 questions only
        grading_mode='balanced',
        total_marks=exam.get('total_marks', 100),
        model_answer_text=model_text,
        skip_cache=True
    )
    
    # Extract line IDs from grading results
    grading_line_ids = set()
    grading_annotations = []
    
    for q in scores:
        for ann in q.annotations:
            if ann.page_index == 0:  # Our test page (index 0 in single-page array)
                grading_annotations.append(ann)
                if ann.line_id:
                    grading_line_ids.add(ann.line_id)
                if ann.line_id_start:
                    # Parse range
                    start_match = re.match(r"Q(\d+)-L(\d+)", ann.line_id_start)
                    end_match = re.match(r"Q(\d+)-L(\d+)", ann.line_id_end) if ann.line_id_end else start_match
                    if start_match and end_match:
                        q_num = int(start_match.group(1))
                        start_l = int(start_match.group(2))
                        end_l = int(end_match.group(2))
                        for l in range(start_l, end_l + 1):
                            grading_line_ids.add(f"Q{q_num}-L{l}")
    
    print(f"✅ Grading complete: {len(scores)} questions")
    print(f"✅ Annotations for test page: {len(grading_annotations)}")
    print(f"✅ Unique line IDs from grading: {len(grading_line_ids)}")
    print(f"\n📝 Line IDs from Gemini: {sorted(grading_line_ids)}")
    
    # STEP 2: Generate line IDs during annotation (OCR on same page)
    print("\n\n🖼️  STEP 2: Generating line IDs during annotation OCR...")
    print("-"*80)
    
    vision_service = VisionOCRService()
    
    # OCR the test page
    ocr_result = vision_service.detect_text_from_base64(test_images[0], ["en"])
    words = ocr_result.get("words", [])
    
    print(f"✅ OCR detected {len(words)} words")
    
    # Recreate line ID generation logic from annotation.py
    from PIL import Image
    import io
    import base64
    
    # Get image dimensions
    image_data = base64.b64decode(test_images[0])
    with Image.open(io.BytesIO(image_data)) as img:
        img_width, img_height = img.size
    
    y_threshold = max(10, int(img_height * 0.012))
    answer_start_y = int(img_height * 0.25)
    
    # Group words into lines
    items = []
    for w in words:
        try:
            x1, y1, x2, y2 = w.get("x1"), w.get("y1"), w.get("x2"), w.get("y2")
            if x1 is None or y1 is None or x2 is None or y2 is None:
                continue
            items.append({
                "text": w.get("text", ""),
                "x1": x1, "x2": x2,
                "y1": y1, "y2": y2,
                "yc": (y1 + y2) / 2
            })
        except Exception:
            continue
    
    items.sort(key=lambda i: (i["yc"], i["x1"]))
    
    lines = []
    for item in items:
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
        xs = [i["x1"] for i in line] + [i["x2"] for i in line]
        ys = [i["y1"] for i in line] + [i["y2"] for i in line]
        text = " ".join(i["text"] for i in line)
        line_boxes.append({
            "text": text,
            "x1": min(xs), "y1": min(ys),
            "x2": max(xs), "y2": max(ys)
        })
    
    # Assign line IDs (same logic as annotation.py)
    question_numbers = sorted({int(q.get("question_number")) for q in exam.get('questions', [])})
    question_patterns = {
        q_num: re.compile(rf"^\s*(?:Q\s*)?{q_num}\s*[\).:-]?\s*", re.IGNORECASE)
        for q_num in question_numbers
    }
    
    annotation_line_ids = {}
    current_q = question_numbers[0] if question_numbers else 1
    line_counts = {}
    
    for line in line_boxes:
        if line.get("y2", 0) < answer_start_y:
            continue
        text = (line.get("text") or "").strip()
        if text:
            for q_num, pattern in question_patterns.items():
                if pattern.match(text):
                    current_q = q_num
                    break
        line_counts[current_q] = line_counts.get(current_q, 0) + 1
        line_idx = line_counts[current_q]
        line_id = f"Q{current_q}-L{line_idx}"
        annotation_line_ids[line_id] = line["text"]
    
    print(f"✅ Generated {len(annotation_line_ids)} line IDs during annotation")
    print(f"\n📝 Line IDs from annotation OCR: {sorted(annotation_line_ids.keys())}")
    
    # STEP 3: Compare
    print("\n\n🔍 STEP 3: Comparing line IDs...")
    print("="*80)
    
    missing_in_annotation = grading_line_ids - set(annotation_line_ids.keys())
    extra_in_annotation = set(annotation_line_ids.keys()) - grading_line_ids
    matching = grading_line_ids & set(annotation_line_ids.keys())
    
    print(f"\n📊 COMPARISON RESULTS:")
    print(f"  ✅ Matching line IDs: {len(matching)} / {len(grading_line_ids)} ({len(matching)/max(len(grading_line_ids), 1)*100:.1f}%)")
    print(f"  ❌ Missing in annotation OCR: {len(missing_in_annotation)}")
    print(f"  ⚠️  Extra in annotation OCR: {len(extra_in_annotation)}")
    
    if missing_in_annotation:
        print(f"\n❌ LINE IDs FROM GRADING NOT FOUND IN ANNOTATION:")
        for line_id in sorted(missing_in_annotation)[:10]:
            print(f"   - {line_id}")
        if len(missing_in_annotation) > 10:
            print(f"   ... and {len(missing_in_annotation) - 10} more")
    
    if extra_in_annotation:
        print(f"\n⚠️  LINE IDs IN ANNOTATION BUT NOT IN GRADING:")
        for line_id in sorted(extra_in_annotation)[:10]:
            text = annotation_line_ids[line_id][:50]
            print(f"   - {line_id}: {text}")
        if len(extra_in_annotation) > 10:
            print(f"   ... and {len(extra_in_annotation) - 10} more")
    
    # STEP 4: Show annotation details
    print("\n\n📋 STEP 4: Annotation Placement Details...")
    print("="*80)
    
    placed = 0
    skipped = 0
    
    for ann in grading_annotations[:10]:
        line_ids_needed = []
        if ann.line_id:
            line_ids_needed = [ann.line_id]
        elif ann.line_id_start:
            start_match = re.match(r"Q(\d+)-L(\d+)", ann.line_id_start)
            end_match = re.match(r"Q(\d+)-L(\d+)", ann.line_id_end) if ann.line_id_end else start_match
            if start_match and end_match:
                q_num = int(start_match.group(1))
                start_l = int(start_match.group(2))
                end_l = int(end_match.group(2))
                line_ids_needed = [f"Q{q_num}-L{l}" for l in range(start_l, end_l + 1)]
        
        all_found = all(lid in annotation_line_ids for lid in line_ids_needed)
        status = "✅ WILL PLACE" if all_found else "❌ WILL SKIP"
        
        if all_found:
            placed += 1
        else:
            skipped += 1
        
        line_ref = ann.line_id or f"{ann.line_id_start} to {ann.line_id_end}"
        print(f"{status} | Type={ann.type:20s} | Lines={line_ref}")
    
    print(f"\n📈 PLACEMENT PREDICTION:")
    print(f"  ✅ Will place: {placed}")
    print(f"  ❌ Will skip: {skipped}")
    if placed + skipped > 0:
        print(f"  Success rate: {placed/(placed+skipped)*100:.1f}%")
    else:
        print(f"  (No annotations to place)")
    
    print("\n" + "="*80)
    if len(missing_in_annotation) == 0:
        print("✅ SUCCESS: All line IDs from grading are available in annotation!")
        print("   Annotations should appear correctly on images.")
    else:
        print("⚠️  WARNING: Some line IDs are missing!")
        print("   Possible causes:")
        print("   1. OCR results differ between grading and annotation time")
        print("   2. Question boundary detection inconsistency")
        print("   3. Line grouping threshold differences")
    print("="*80 + "\n")


if __name__ == "__main__":
    asyncio.run(test_line_id_matching())
