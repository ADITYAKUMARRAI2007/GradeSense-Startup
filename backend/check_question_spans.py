"""Check what question spans were extracted from the question paper."""
import sys
import os
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))

from app.database import sync_db as db

exam_id = 'exam_d243c553'
exam = db.exams.find_one({'exam_id': exam_id})

if exam:
    print(f"\n📋 Exam: {exam.get('exam_name', exam_id)}")
    print(f"="*70)
    
    # Check question extraction metadata
    print(f"\n🔍 Question Extraction Status:")
    print(f"  Status: {exam.get('question_extraction_status')}")
    print(f"  Count: {exam.get('question_extraction_count')}")
    print(f"  Source: {exam.get('question_extraction_source')}")
    print(f"  Message: {exam.get('question_extraction_message')}")
    
    # Check if there are question spans stored
    question_spans = exam.get('question_spans', [])
    print(f"\n📄 Question Spans: {len(question_spans)}")
    
    if question_spans:
        for i, span in enumerate(question_spans, 1):
            print(f"\n  Span {i}:")
            print(f"    Pages: {span.get('start_page')} - {span.get('end_page')}")
            print(f"    Question Number: {span.get('question_number')}")
            print(f"    Anchor Text: {span.get('anchor_text', 'N/A')[:100]}")
            print(f"    Score: {span.get('score')}")
    
    # Check actual questions
    questions = exam.get('questions', [])
    print(f"\n📝 Actual Questions: {len(questions)}")
    
    if questions:
        for q in questions[:3]:  # Show first 3
            print(f"\n  Q{q.get('question_number')}:")
            print(f"    ID: {q.get('question_id')}")
            print(f"    Text: {q.get('question_text')[:100]}")
            print(f"    Marks: {q.get('marks')}")
    
    # Check question paper images
    qp_images = exam.get('question_paper_images', [])
    print(f"\n🖼️  Question Paper Images: {len(qp_images)}")
    
else:
    print(f"❌ Exam {exam_id} not found")
