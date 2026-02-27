"""Check the latest submission for the English exam."""
import sys
import os
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))

from app.database import sync_db as db

exam_id = 'exam_d243c553'

# Find the most recent submission for this exam
submission = db.submissions.find_one(
    {'exam_id': exam_id},
    sort=[('created_at', -1)]
)

if submission:
    print(f"\n📄 Latest Submission for {exam_id}:")
    print(f"   ID: {submission.get('submission_id')}")
    print(f"   Student: {submission.get('student_name')}")
    print(f"   Status: {submission.get('status')}")
    print(f"   Created: {submission.get('created_at')}")
    print(f"   Total score: {submission.get('total_score')}/{submission.get('total_marks')}")
    
    # Check question scores
    question_scores = submission.get('question_scores', [])
    print(f"\n📊 Question Scores ({len(question_scores)} questions):")
    for qs in question_scores[:10]:  # Show first 10
        q_id = qs.get('question_id')
        score = qs.get('score', 0)
        max_marks = qs.get('max_marks', 0)
        status = qs.get('status', 'unknown')
        print(f"   {q_id}: {score}/{max_marks} - {status}")
    
    if len(question_scores) > 10:
        print(f"   ... and {len(question_scores) - 10} more questions")
    
    # Check mapping status
    print(f"\n🗺️  Mapping Status:")
    print(f"   Mapping status: {submission.get('mapping_status')}")
    print(f"   Mapped ratio: {submission.get('mapped_question_ratio', 0):.2%}")
    print(f"   Coverage: {submission.get('mapping_coverage', 0):.2%}")
    print(f"   Packets generated: {submission.get('packets_generated', 0)}")
    
    unresolved = submission.get('unresolved_questions', [])
    if unresolved:
        print(f"\n⚠️  Unresolved Questions ({len(unresolved)}):")
        for uq in unresolved[:5]:
            print(f"   - {uq}")
else:
    print(f"❌ No submissions found for exam {exam_id}")
