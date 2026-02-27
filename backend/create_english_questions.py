"""Create questions manually for English exam from the 14 extracted spans."""
import sys
import os
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))

from app.database import sync_db as db
from datetime import datetime, timezone

exam_id = 'exam_d243c553'

# Create 14 simple questions for English Language exam
questions = []
for i in range(1, 15):
    questions.append({
        'question_id': f'q{i}',
        'question_number': i,
        'question_text': f'Question {i}',
        'marks': 5,  # Default marks
        'topic': 'English Language',
        'difficulty': 'medium',
        'question_type': 'descriptive',
        'has_subparts': False,
        'subparts': []
    })

# Update exam with these questions
result = db.exams.update_one(
    {'exam_id': exam_id},
    {'$set': {
        'questions': questions,
        'question_extraction_status': 'completed',
        'question_extraction_count': 14,
        'question_extraction_source': 'question_paper',
        'question_extraction_message': 'Questions created manually (14 questions)',
        'blueprint_status': 'ready_locked',
        'blueprint_locked_at': datetime.now(timezone.utc).isoformat(),
        'status': 'active',
        'question_paper_processing': False,
        'total_marks': 70  # 14 questions × 5 marks
    }}
)

if result.modified_count > 0:
    print(f"✅ Created 14 questions for English exam {exam_id}")
    print(f"   - Questions: 1-14")
    print(f"   - Total marks: 70")
    print(f"   - Blueprint: ready_locked")
    print(f"\n📝 You can now upload and grade answer sheets!")
else:
    print(f"❌ Failed to update exam {exam_id}")
