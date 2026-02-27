"""Show all questions in the English exam."""
import sys
import os
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))

from app.database import sync_db as db

exam_id = 'exam_d243c553'
exam = db.exams.find_one({'exam_id': exam_id}, {'questions': 1, 'exam_name': 1})

if exam:
    print(f"\n📋 Exam: {exam.get('exam_name', exam_id)}")
    print(f"="*70)
    
    questions = exam.get('questions', [])
    print(f"\nTotal Questions: {len(questions)}\n")
    
    for q in questions:
        print(f"Question {q.get('question_number')}:")
        print(f"  ID: {q.get('question_id')}")
        print(f"  Text: {q.get('question_text')}")
        print(f"  Marks: {q.get('marks')}")
        print(f"  Topic: {q.get('topic')}")
        print(f"  Type: {q.get('question_type')}")
        print(f"  Difficulty: {q.get('difficulty')}")
        print(f"  Has subparts: {q.get('has_subparts')}")
        if q.get('subparts'):
            print(f"  Subparts: {len(q.get('subparts'))}")
        print()
else:
    print(f"❌ Exam {exam_id} not found")
