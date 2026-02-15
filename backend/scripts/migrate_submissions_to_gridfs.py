#!/usr/bin/env python3
"""
Migration script to move submissions file_data and file_images to GridFS.
"""

import os
import sys
from pymongo import MongoClient
from gridfs import GridFS
import base64
from datetime import datetime, timezone

def migrate_submissions_to_gridfs():
    """Move file_data and file_images from submissions to GridFS"""
    
    mongo_url = os.environ.get('MONGO_URL')
    db_name = os.environ.get('DB_NAME')
    
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL and DB_NAME environment variables required")
        sys.exit(1)
    
    client = MongoClient(mongo_url)
    db = client[db_name]
    fs = GridFS(db)
    
    print(f"Connected to database: {db_name}")
    
    # Get all submissions
    submissions = list(db.submissions.find({}))
    print(f"Found {len(submissions)} submissions documents")
    
    migrated_count = 0
    already_migrated = 0
    
    for submission in submissions:
        submission_id = submission.get('submission_id')
        
        try:
            updates = {}
            
            # Migrate file_data if large
            if 'file_data' in submission and isinstance(submission['file_data'], str):
                file_data = submission['file_data']
                
                if len(file_data) < 100:
                    # Already migrated
                    pass
                else:
                    try:
                        if file_data.startswith('data:'):
                            file_data = file_data.split(',', 1)[1]
                        
                        file_bytes = base64.b64decode(file_data)
                        
                        gridfs_id = fs.put(
                            file_bytes,
                            filename=f"submission_{submission_id}_file.pdf",
                            content_type="application/pdf",
                            metadata={
                                "submission_id": submission_id,
                                "migrated_at": datetime.now(timezone.utc).isoformat()
                            }
                        )
                        
                        updates['file_data'] = str(gridfs_id)
                        print(f"  {submission_id}: Migrated file_data to GridFS ({len(file_bytes)/1024:.1f}KB)")
                    except Exception as e:
                        print(f"  {submission_id}: ERROR migrating file_data: {e}")
            
            # Migrate file_images if large
            if 'file_images' in submission and isinstance(submission['file_images'], list):
                file_images = submission['file_images']
                
                if file_images and all(isinstance(img, str) and len(img) < 100 for img in file_images):
                    # Already migrated
                    pass
                else:
                    image_ids = []
                    for idx, img_data in enumerate(file_images):
                        if not isinstance(img_data, str) or len(img_data) < 100:
                            image_ids.append(img_data)
                            continue
                        
                        try:
                            if img_data.startswith('data:'):
                                img_data = img_data.split(',', 1)[1]
                            
                            img_bytes = base64.b64decode(img_data)
                            
                            img_id = fs.put(
                                img_bytes,
                                filename=f"submission_{submission_id}_page_{idx+1}.png",
                                content_type="image/png",
                                metadata={
                                    "submission_id": submission_id,
                                    "page_number": idx + 1,
                                    "migrated_at": datetime.now(timezone.utc).isoformat()
                                }
                            )
                            
                            image_ids.append(str(img_id))
                        except Exception as e:
                            print(f"  {submission_id}: ERROR migrating image {idx}: {e}")
                            image_ids.append(img_data)
                    
                    if image_ids:
                        updates['file_images'] = image_ids
                        print(f"  {submission_id}: Migrated {len(image_ids)} file_images to GridFS")
            
            if updates:
                db.submissions.update_one(
                    {"_id": submission['_id']},
                    {"$set": updates}
                )
                migrated_count += 1
            else:
                already_migrated += 1
        
        except Exception as e:
            print(f"ERROR processing {submission_id}: {e}")
    
    print("\n" + "="*60)
    print(f"Migration Summary:")
    print(f"  Total: {len(submissions)}")
    print(f"  Migrated: {migrated_count}")
    print(f"  Already migrated: {already_migrated}")
    print("="*60)
    print("\n✅ Migration completed!")

if __name__ == "__main__":
    migrate_submissions_to_gridfs()
