#!/usr/bin/env python3
"""Test script to verify line-ID annotation system"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()  # Load .env before importing app modules

from app.services.grading import grade_with_ai
from app.services.gridfs_helpers import get_exam_model_answer_images
from app.services.extraction import get_exam_model_answer_text
from app.database import db, fs
from bson import ObjectId
import pickle


async def test_line_id_system():
    """Test grading with line-ID system on real submission"""
    
    print("\n" + "="*80)
    print("TESTING LINE-ID ANNOTATION SYSTEM")
    print("="*80 + "\n")
    
    # Get a graded submission with GridFS images
    sub = await db.submissions.find_one(
        {'images_gridfs_id': {'$exists': True}},
        projection={'_id': 0}
    )
    
    if not sub:
        print("❌ No graded submissions found in database")
        return
    
    exam = await db.exams.find_one({'exam_id': sub['exam_id']}, projection={'_id': 0})
    
    print(f"📄 Submission: {sub['submission_id']}")
    print(f"👤 Student: {sub['student_name']}")
    print(f"📝 Exam: {exam['exam_name']}")
    print(f"❓ Questions: {len(exam.get('questions', []))}")
    
    # Get answer images
    answer_images = sub.get('answer_images')
    if not answer_images and sub.get('images_gridfs_id'):
        img_oid = ObjectId(sub['images_gridfs_id'])
        grid_out = fs.get(img_oid)
        answer_images = pickle.loads(grid_out.read())
    
    if not answer_images:
        print("❌ No answer images found")
        return
    
    print(f"📄 Answer pages: {len(answer_images)}")
    
    # Skip first 2 pages (usually cover/instructions), test pages with actual answers
    test_images = answer_images[2:4] if len(answer_images) > 3 else answer_images[:2]
    print(f"📄 Testing pages: 3-4 (skipping cover pages)")
    
    
    # Get model answer
    model_imgs = await get_exam_model_answer_images(exam['exam_id'])
    model_text = await get_exam_model_answer_text(exam['exam_id'])
    
    print(f"📖 Model answer pages: {len(model_imgs) if model_imgs else 0}")
    print(f"📖 Model answer text: {'Yes' if model_text else 'No'}")
    
    print("\n" + "="*80)
    print("🚀 STARTING GRADING WITH LINE-ID SYSTEM...")
    print("="*80 + "\n")
    
    scores = await grade_with_ai(
        images=test_images,
        model_answer_images=model_imgs,
        questions=exam.get('questions', [])[:5],  # First 5 questions only
        grading_mode='balanced',
        total_marks=exam.get('total_marks', 100),
        model_answer_text=model_text,
        skip_cache=True
    )
    
    print("\n" + "="*80)
    print("✅ GRADING COMPLETE")
    print("="*80 + "\n")
    
    print(f"📊 Questions graded: {len(scores)}\n")
    
    for s in scores:
        print(f"  Q{s.question_number}: {s.obtained_marks} marks")
        print(f"    Annotations: {len(s.annotations)}")
        
        if s.annotations:
            print("    Details:")
            for idx, ann in enumerate(s.annotations[:5], 1):  # Show first 5 annotations
                line_ref = ""
                if ann.line_id:
                    line_ref = f"LineID={ann.line_id}"
                elif ann.line_id_start or ann.line_id_end:
                    line_ref = f"Lines={ann.line_id_start} to {ann.line_id_end}"
                else:
                    line_ref = f"Anchor={ann.anchor_text[:30] if ann.anchor_text else 'None'}"
                
                print(f"      {idx}. {ann.type} | {line_ref}")
        
        print()
    
    # Summary
    total_annotations = sum(len(s.annotations) for s in scores)
    line_id_annotations = sum(
        1 for s in scores 
        for ann in s.annotations 
        if ann.line_id or ann.line_id_start or ann.line_id_end
    )
    anchor_annotations = total_annotations - line_id_annotations
    
    print("="*80)
    print("📈 ANNOTATION SUMMARY")
    print("="*80)
    print(f"  Total annotations: {total_annotations}")
    print(f"  ✅ Line-ID based: {line_id_annotations} ({line_id_annotations/max(total_annotations, 1)*100:.1f}%)")
    print(f"  📝 Anchor-text based: {anchor_annotations} ({anchor_annotations/max(total_annotations, 1)*100:.1f}%)")
    print("="*80 + "\n")
    
    if line_id_annotations > 0:
        print("✅ SUCCESS: Line-ID system is WORKING!")
    else:
        print("⚠️  WARNING: No line-ID annotations found. Check OCR and Gemini response.")


if __name__ == "__main__":
    asyncio.run(test_line_id_system())
