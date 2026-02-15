import os; from dotenv import load_dotenv; load_dotenv()
from pymongo import MongoClient
client = MongoClient(os.getenv('MONGO_URL', 'mongodb://localhost:27017'))
db = client['gradesense']
for sub in db.submissions.find({"status": {"$in": ["graded", "ai_graded"]}}, {"submission_id":1, "student_name":1, "status":1}).limit(5):
    full = db.submissions.find_one({"submission_id": sub["submission_id"]})
    fi = full.get("file_images", [])
    imgs = full.get("images", [])
    print(f'{sub["submission_id"]}: {sub["student_name"]}, file_images={len(fi)}, images={len(imgs)}')
