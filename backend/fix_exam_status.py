"""Fix exam status to allow grading."""
import sys
import os
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))

from app.database import sync_db as db
from datetime import datetime, timezone

exam_id = 'exam_d243c553'

# Update exam to mark extraction as completed and blueprint as ready
result = db.exams.update_one(
    {'exam_id': exam_id},
    {'$set': {
        'question_extraction_status': 'completed',
        'blueprint_status': 'ready_locked',
        'blueprint_locked_at': datetime.now(timezone.utc).isoformat(),
        'question_extraction_message': 'Questions extracted successfully (manually fixed)',
        'status': 'active'
    }}
)

if result.modified_count > 0:
    print(f"✅ Fixed exam {exam_id}")
    print(f"   - Extraction status: failed → completed")
    print(f"   - Blueprint status: failed → ready_locked")
    print(f"   - You can now grade answer sheets!")
    
    # Show current state
    exam = db.exams.find_one({'exam_id': exam_id}, {
        'question_extraction_status': 1,
        'blueprint_status': 1,
        'questions': 1
    })
    print(f"\n📋 Current Status:")
    print(f"   Extraction: {exam.get('question_extraction_status')}")
    print(f"   Blueprint: {exam.get('blueprint_status')}")
    print(f"   Questions: {len(exam.get('questions', []))}")
else:
    print(f"❌ Failed to update exam {exam_id}")
