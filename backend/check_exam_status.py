"""Check exam extraction status."""
import sys
import os

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))

from app.database import sync_db as db

exam_id = 'exam_d243c553'
exam = db.exams.find_one({'exam_id': exam_id}, {
    'question_paper_processing': 1,
    'question_extraction_status': 1,
    'questions': 1,
    'status': 1,
    'blueprint_status': 1,
    'question_extraction_message': 1
})

if exam:
    print(f"\n📋 Exam Status for {exam_id}:")
    print(f"   question_paper_processing: {exam.get('question_paper_processing')}")
    print(f'   question_extraction_status: {exam.get("question_extraction_status")}')
    print(f'   question_extraction_message: {exam.get("question_extraction_message")}')
    print(f'   blueprint_status: {exam.get("blueprint_status")}')
    print(f'   exam status: {exam.get("status")}')
    print(f'   questions count: {len(exam.get("questions", []))}')
    
    if exam.get('questions'):
        print(f"\n📝 Sample Questions:")
        for q in exam.get('questions', [])[:3]:
            print(f"   Q{q.get('question_number')}: {q.get('question_text', '')[:60]}...")
    
    if exam.get('question_paper_processing') or exam.get('question_extraction_status') == 'processing':
        print(f"\n⚠️  Extraction still in progress - cannot grade yet")
        print(f"   Wait a few more seconds for background processing to complete")
    elif exam.get('question_extraction_status') == 'failed':
        print(f"\n❌ Extraction failed!")
        print(f"   Message: {exam.get('question_extraction_message')}")
    else:
        print(f"\n✅ Extraction complete - ready to grade!")
else:
    print(f'❌ Exam {exam_id} not found')
