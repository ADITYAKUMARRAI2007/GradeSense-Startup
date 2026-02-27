"""Check grading job status."""
import sys
import os
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))

from app.database import sync_db as db

job_id = 'job_b2c618ca384d'
job = db.grading_jobs.find_one({'job_id': job_id})

if job:
    print(f"\n📊 Grading Job Status: {job_id}")
    print(f"   Status: {job.get('status')}")
    print(f"   Total papers: {job.get('total_papers')}")
    print(f"   Processed: {job.get('processed_papers')}")
    print(f"   Successful: {job.get('successful')}")
    print(f"   Failed: {job.get('failed')}")
    print(f"   Created: {job.get('created_at')}")
    print(f"   Updated: {job.get('updated_at')}")
    
    submissions = job.get('submissions', [])
    if submissions:
        print(f"\n📝 Submissions:")
        for sub in submissions:
            print(f"   - {sub.get('submission_id')}: {sub.get('status')}")
    
    errors = job.get('errors', [])
    if errors:
        print(f"\n❌ Errors:")
        for err in errors[:5]:  # Show first 5 errors
            print(f"   - {err}")
    
    if job.get('status') == 'completed':
        print(f"\n✅ Job completed! Check the submissions in the frontend.")
    elif job.get('status') == 'processing':
        print(f"\n⏳ Job is still processing...")
    elif job.get('status') == 'failed':
        print(f"\n❌ Job failed!")
else:
    print(f'❌ Job {job_id} not found')
