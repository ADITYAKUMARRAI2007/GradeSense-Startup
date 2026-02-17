#!/usr/bin/env python3
import os, sys, pickle, base64
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
from app.database import db, fs
from bson import ObjectId

submission_id = sys.argv[1] if len(sys.argv) > 1 else None
if not submission_id:
    print('Usage: dump_annotated_images.py <submission_id>')
    raise SystemExit(1)

sub = None
import asyncio

async def run():
    global sub
    sub = await db.submissions.find_one({'submission_id': submission_id}, {'_id':0})
    if not sub:
        print('Submission not found')
        return
    imgs = sub.get('annotated_images') or []
    if not imgs and sub.get('annotated_images_gridfs_id'):
        oid = ObjectId(sub['annotated_images_gridfs_id'])
        grid_out = fs.get(oid)
        imgs = pickle.loads(grid_out.read())
    print('Found', len(imgs), 'annotated pages')
    for i, b in enumerate(imgs[:10]):
        path = f'/tmp/regen_annot_page_{i+1}.jpg'
        with open(path, 'wb') as fh:
            fh.write(base64.b64decode(b))
        print('WROTE', path)

asyncio.run(run())
