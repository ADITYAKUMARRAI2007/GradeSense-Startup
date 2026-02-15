#!/usr/bin/env python3
"""
Migration script to move large embedded data from exam_files to GridFS.
This fixes the Atlas deployment "transaction too large" error.

Run this BEFORE deployment to clean up the database.
"""

import os
import sys
from pymongo import MongoClient
from gridfs import GridFS
import base64
from datetime import datetime, timezone

def migrate_exam_files_to_gridfs():
    """Move file_data and images from exam_files documents to GridFS"""
    
    mongo_url = os.environ.get('MONGO_URL')
    db_name = os.environ.get('DB_NAME')
    
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL and DB_NAME environment variables required")
        sys.exit(1)
    
    client = MongoClient(mongo_url)
    db = client[db_name]
    fs = GridFS(db)
    
    print(f"Connected to database: {db_name}")
    
    # Get all exam_files
    exam_files = list(db.exam_files.find({}))
    print(f"Found {len(exam_files)} exam_files documents")
    
    migrated_count = 0
    already_migrated = 0
    errors = 0
    
    for exam_file in exam_files:
        exam_id = exam_file.get('exam_id')
        file_id = exam_file.get('file_id')
        
        try:
            updates = {}
            
            # 1. Migrate file_data if it's base64 string
            if 'file_data' in exam_file and isinstance(exam_file['file_data'], str):
                file_data = exam_file['file_data']
                
                # Check if it's already a GridFS ID (short string)
                if len(file_data) < 100:
                    print(f"  {exam_id}: file_data already migrated (ID: {file_data})")
                else:
                    # Store in GridFS
                    try:
                        # Decode base64 if needed
                        if file_data.startswith('data:'):
                            file_data = file_data.split(',', 1)[1]
                        
                        file_bytes = base64.b64decode(file_data)
                        
                        # Store in GridFS
                        gridfs_id = fs.put(
                            file_bytes,
                            filename=f"exam_{exam_id}_{file_id}.pdf",
                            content_type="application/pdf",
                            metadata={
                                "exam_id": exam_id,
                                "file_id": file_id,
                                "migrated_at": datetime.now(timezone.utc).isoformat()
                            }
                        )
                        
                        updates['file_data'] = str(gridfs_id)
                        print(f"  {exam_id}: Migrated file_data to GridFS ({len(file_bytes)} bytes -> {gridfs_id})")
                    
                    except Exception as e:
                        print(f"  {exam_id}: ERROR migrating file_data: {e}")
                        errors += 1
            
            # 2. Migrate images array if it contains base64 strings
            if 'images' in exam_file and isinstance(exam_file['images'], list):
                images = exam_file['images']
                
                # Check if already migrated (array of short IDs)
                if images and all(isinstance(img, str) and len(img) < 100 for img in images):
                    print(f"  {exam_id}: images already migrated")
                else:
                    # Migrate each image
                    image_ids = []
                    for idx, img_data in enumerate(images):
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
                                filename=f"exam_{exam_id}_{file_id}_page_{idx+1}.png",
                                content_type="image/png",
                                metadata={
                                    "exam_id": exam_id,
                                    "file_id": file_id,
                                    "page_number": idx + 1,
                                    "migrated_at": datetime.now(timezone.utc).isoformat()
                                }
                            )
                            
                            image_ids.append(str(img_id))
                        
                        except Exception as e:
                            print(f"  {exam_id}: ERROR migrating image {idx}: {e}")
                            errors += 1
                            image_ids.append(img_data)  # Keep original on error
                    
                    if image_ids:
                        updates['images'] = image_ids
                        print(f"  {exam_id}: Migrated {len(image_ids)} images to GridFS")
            
            # Update document with GridFS references
            if updates:
                db.exam_files.update_one(
                    {"_id": exam_file['_id']},
                    {"$set": updates}
                )
                migrated_count += 1
            else:
                already_migrated += 1
        
        except Exception as e:
            print(f"ERROR processing {exam_id}: {e}")
            errors += 1
    
    print("\n" + "="*60)
    print(f"Migration Summary:")
    print(f"  Total documents: {len(exam_files)}")
    print(f"  Migrated: {migrated_count}")
    print(f"  Already migrated: {already_migrated}")
    print(f"  Errors: {errors}")
    print("="*60)
    
    if errors > 0:
        print("\nWARNING: Some documents had errors during migration")
        sys.exit(1)
    
    print("\n✅ Migration completed successfully!")
    print("The database is now ready for Atlas deployment.")

if __name__ == "__main__":
    migrate_exam_files_to_gridfs()
