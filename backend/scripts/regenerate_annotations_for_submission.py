#!/usr/bin/env python3
"""Regenerate annotated images for a submission and update DB.
Usage: python scripts/regenerate_annotations_for_submission.py [submission_id]
If no submission_id provided, the script picks the most recent submission with images.
"""
import os
import sys
import pickle
from bson import ObjectId
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

# Ensure backend package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.database import db, fs
from app.services.annotation import generate_annotated_images_with_vision_ocr


async def pick_submission(submission_id=None):
    if submission_id:
        sub = await db.submissions.find_one({'submission_id': submission_id}, {'_id': 0})
        return sub
    sub = await db.submissions.find_one({'images_gridfs_id': {'$exists': True}}, sort=[('graded_at', -1)], projection={'_id': 0})
    return sub


async def main(submission_id=None):
    sub = await pick_submission(submission_id)
    if not sub:
        print('No submission found to re-generate annotations for.')
        return
    print('Selected submission:', sub['submission_id'])

    # load images
    images = sub.get('file_images') or []
    if not images and sub.get('images_gridfs_id'):
        try:
            oid = ObjectId(sub['images_gridfs_id'])
            grid_out = fs.get(oid)
            images = pickle.loads(grid_out.read())
        except Exception as e:
            print('Failed to load images from GridFS:', e)
            return

    question_scores = sub.get('question_scores', [])

    # Ensure question_scores are Pydantic QuestionScore objects (the OCR path expects models)
    from app.models.submission import QuestionScore as QSModel
    normalized_qs = []
    for q in question_scores:
        if isinstance(q, dict):
            try:
                normalized_qs.append(QSModel.model_validate(q))
            except Exception:
                # minimal fallback mapping
                normalized_qs.append(QSModel(**{k: v for k, v in q.items() if k in QSModel.model_fields}))
        else:
            normalized_qs.append(q)

    # Call annotation generator (vision OCR enabled)
    print('Regenerating annotated images (this may take a moment)...')
    try:
        annotated = await generate_annotated_images_with_vision_ocr(images, normalized_qs, use_vision_ocr=True)
    except Exception as e:
        print('Vision OCR path failed:', e)
        print('Falling back to basic annotated images')
        from app.services.annotation import generate_annotated_images
        annotated = generate_annotated_images(images, normalized_qs)

    # store back to GridFS
    try:
        data = pickle.dumps(annotated)
        aid = fs.put(data, filename=f"{sub['submission_id']}_annotated_regen.pkl", submission_id=sub['submission_id'])
        db.submissions.update_one({'submission_id': sub['submission_id']}, {'$set': {'annotated_images_gridfs_id': str(aid), 'annotated_images': annotated}})
        print('Updated submission with regenerated annotated images (gridfs id:', aid, ')')
    except Exception as e:
        print('Failed to store annotated images:', e)


if __name__ == '__main__':
    import asyncio
    sid = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(main(sid))
