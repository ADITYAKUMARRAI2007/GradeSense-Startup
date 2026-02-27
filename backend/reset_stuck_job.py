"""Reset stuck grading job."""
import sys
import os
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))

from app.database import sync_db as db

job_id = 'job_86b7492bfeaf'

# Delete the stuck job
result = db.grading_jobs.delete_one({'job_id': job_id})

if result.deleted_count > 0:
    print(f"✅ Deleted stuck job {job_id}")
    print(f"   You can now upload the answer sheet again")
else:
    print(f"❌ Job {job_id} not found")
