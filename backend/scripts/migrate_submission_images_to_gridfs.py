#!/usr/bin/env python3
"""
Migration script to move submission_images from embedded base64 to GridFS.
This fixes Atlas deployment "transaction too large" error.
"""

import os
import sys
from pymongo import MongoClient
from gridfs import GridFS
import base64
from datetime import datetime, timezone

def migrate_submission_images_to_gridfs():
    """Move file_images and annotated_images from submission_images to GridFS"""
    
    mongo_url = os.environ.get('MONGO_URL')
    db_name = os.environ.get('DB_NAME')
    
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL and DB_NAME environment variables required")
        sys.exit(1)
    
    client = MongoClient(mongo_url)
    db = client[db_name]
    fs = GridFS(db)
    
    print(f"Connected to database: {db_name}")
    
    # Get all submission_images
    submissions = list(db.submission_images.find({}))
    print(f"Found {len(submissions)} submission_images documents")
    
    migrated_count = 0
    already_migrated = 0
    errors = 0
    
    for submission in submissions:
        submission_id = submission.get('submission_id')
        
        try:
            updates = {}
            
            # 1. Migrate file_images array
            if 'file_images' in submission and isinstance(submission['file_images'], list):
                file_images = submission['file_images']
                
                # Check if already migrated (array of short IDs)
                if file_images and all(isinstance(img, str) and len(img) < 100 for img in file_images):
                    print(f"  {submission_id}: file_images already migrated")
                else:
                    # Migrate each image
                    image_ids = []
                    for idx, img_data in enumerate(file_images):
                        if not isinstance(img_data, str):
                            continue
                        
                        # Check if already migrated
                        if len(img_data) < 100:
                            image_ids.append(img_data)
                            continue
                        
                        try:
                            # Decode base64
                            if img_data.startswith('data:'):
                                img_data = img_data.split(',', 1)[1]
                            
                            img_bytes = base64.b64decode(img_data)
                            
                            # Store in GridFS
                            img_id = fs.put(
                                img_bytes,
                                filename=f"submission_{submission_id}_file_page_{idx+1}.png",
                                content_type="image/png",
                                metadata={
                                    "submission_id": submission_id,
                                    "image_type": "file_image",
                                    "page_number": idx + 1,
                                    "migrated_at": datetime.now(timezone.utc).isoformat()
                                }
                            )
                            
                            image_ids.append(str(img_id))
                        
                        except Exception as e:
                            print(f"  {submission_id}: ERROR migrating file_image {idx}: {e}")
                            errors += 1
                            image_ids.append(img_data)  # Keep original on error
                    
                    if image_ids:
                        updates['file_images'] = image_ids
                        print(f"  {submission_id}: Migrated {len(image_ids)} file_images to GridFS")
            
            # 2. Migrate annotated_images array
            if 'annotated_images' in submission and isinstance(submission['annotated_images'], list):
                annotated_images = submission['annotated_images']
                
                # Check if already migrated
                if annotated_images and all(isinstance(img, str) and len(img) < 100 for img in annotated_images):
                    print(f"  {submission_id}: annotated_images already migrated")
                else:
                    # Migrate each image
                    image_ids = []
                    for idx, img_data in enumerate(annotated_images):
                        if not isinstance(img_data, str):
                            continue
                        
                        # Check if already migrated
                        if len(img_data) < 100:
                            image_ids.append(img_data)
                            continue
                        
                        try:
                            # Decode base64
                            if img_data.startswith('data:'):
                                img_data = img_data.split(',', 1)[1]
                            
                            img_bytes = base64.b64decode(img_data)
                            
                            # Store in GridFS
                            img_id = fs.put(
                                img_bytes,
                                filename=f"submission_{submission_id}_annotated_page_{idx+1}.png",
                                content_type="image/png",
                                metadata={
                                    "submission_id": submission_id,
                                    "image_type": "annotated_image",
                                    "page_number": idx + 1,
                                    "migrated_at": datetime.now(timezone.utc).isoformat()
                                }
                            )
                            
                            image_ids.append(str(img_id))
                        
                        except Exception as e:
                            print(f"  {submission_id}: ERROR migrating annotated_image {idx}: {e}")
                            errors += 1
                            image_ids.append(img_data)  # Keep original on error
                    
                    if image_ids:
                        updates['annotated_images'] = image_ids
                        print(f"  {submission_id}: Migrated {len(image_ids)} annotated_images to GridFS")
            
            # Update document with GridFS references
            if updates:
                db.submission_images.update_one(
                    {"_id": submission['_id']},
                    {"$set": updates}
                )
                migrated_count += 1
            else:
                already_migrated += 1
        
        except Exception as e:
            print(f"ERROR processing {submission_id}: {e}")
            errors += 1
    
    print("\n" + "="*60)
    print(f"Migration Summary:")
    print(f"  Total documents: {len(submissions)}")
    print(f"  Migrated: {migrated_count}")
    print(f"  Already migrated: {already_migrated}")
    print(f"  Errors: {errors}")
    print("="*60)
    
    if errors > 0:
        print("\nWARNING: Some documents had errors during migration")
        sys.exit(1)
    
    print("\n✅ Migration completed successfully!")

if __name__ == "__main__":
    migrate_submission_images_to_gridfs()
