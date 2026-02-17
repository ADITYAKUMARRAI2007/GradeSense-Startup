"""Test that the annotation line-ID fix works by regrading a single paper."""
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()

from pymongo import MongoClient

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
client = MongoClient(MONGO_URL)
db = client["gradesense"]

# Find a submission that was previously graded
sub = db.submissions.find_one({"status": "graded"}, sort=[("created_at", -1)])
if not sub:
    import pytest
    pytest.skip("No graded submission found — skipping integration regrade test")

sub_id = sub["submission_id"]
exam_id = sub["exam_id"]
student_name = sub.get("student_name", "Unknown")
print(f"Testing with: {student_name} (sub={sub_id}, exam={exam_id})")

# Count annotations BEFORE regrade
scores = sub.get("scores", [])
total_anns_before = sum(len(s.get("annotations", [])) for s in scores)
line_id_anns_before = sum(
    1 for s in scores for a in s.get("annotations", [])
    if a.get("line_id") or a.get("line_id_start") or a.get("line_id_end")
)
print(f"Before: {total_anns_before} annotations, {line_id_anns_before} with line IDs")

# Trigger regrade via API
import requests
print(f"\nTriggering regrade via API...")
resp = requests.post(
    f"http://localhost:8000/api/submissions/{sub_id}/regrade",
    params={"exam_id": exam_id}
)
print(f"Regrade response: {resp.status_code}")
if resp.status_code != 200:
    # Try alternate endpoint
    resp = requests.post(
        f"http://localhost:8000/api/grading/regrade/{sub_id}",
        params={"exam_id": exam_id}
    )
    print(f"Alt regrade response: {resp.status_code}")
    if resp.status_code != 200:
        print(f"Response: {resp.text[:500]}")

# Wait and check results
import time
print("Waiting for regrade to complete (checking every 10s)...")
for attempt in range(12):  # 2 min max
    time.sleep(10)
    sub_after = db.submissions.find_one({"submission_id": sub_id})
    if sub_after and sub_after.get("status") == "graded":
        scores_after = sub_after.get("scores", [])
        total_anns_after = sum(len(s.get("annotations", [])) for s in scores_after)
        line_id_anns_after = sum(
            1 for s in scores_after for a in s.get("annotations", [])
            if a.get("line_id") or a.get("line_id_start") or a.get("line_id_end")
        )
        
        # Check annotated images
        annotated_imgs = sub_after.get("annotated_images", [])
        has_annotated = len(annotated_imgs) > 0
        
        print(f"\n=== REGRADE COMPLETE (attempt {attempt+1}) ===")
        print(f"After: {total_anns_after} annotations, {line_id_anns_after} with line IDs")
        print(f"Annotated images: {len(annotated_imgs)} (has data: {has_annotated})")
        
        # Check if annotated images differ from originals
        orig_imgs = sub_after.get("images", [])
        if annotated_imgs and orig_imgs:
            same_count = sum(1 for a, o in zip(annotated_imgs, orig_imgs) if a == o)
            diff_count = len(annotated_imgs) - same_count
            print(f"Images different from original: {diff_count}/{len(annotated_imgs)}")
            if diff_count > 0:
                print("✅ ANNOTATIONS ARE BEING DRAWN ON IMAGES!")
            else:
                print("❌ Annotated images same as originals - annotations not drawn")
        break
    print(f"  Still grading... (attempt {attempt+1})")
else:
    print("Timeout - regrade didn't complete in 2 min")
