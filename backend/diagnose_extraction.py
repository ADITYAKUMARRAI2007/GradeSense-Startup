"""Diagnostic script to analyze the extraction issue."""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app.config import logger
from app.database import sync_db as db
from bson import ObjectId
import json

print("\n" + "="*70)
print("EXTRACTION DIAGNOSTIC")
print("="*70)

# Get the most recent submission
submission = db.submissions.find_one(sort=[("created_at", -1)])

if not submission:
    print("\n❌ No submissions found in database")
    sys.exit(1)

print(f"\n📄 Most Recent Submission:")
print(f"   ID: {submission['_id']}")
print(f"   Exam: {submission.get('exam_id')}")
print(f"   Status: {submission.get('status')}")
print(f"   Created: {submission.get('created_at')}")

# Check what fields exist
print(f"\n📋 Submission Fields:")
for key in submission.keys():
    if key not in ['_id', 'created_at', 'updated_at']:
        value = submission[key]
        if isinstance(value, (str, int, float, bool)):
            print(f"   {key}: {value}")
        elif isinstance(value, list):
            print(f"   {key}: list with {len(value)} items")
        elif isinstance(value, dict):
            print(f"   {key}: dict with {len(value)} keys")
        else:
            print(f"   {key}: {type(value).__name__}")

# Check pipeline result
pipeline_result = submission.get('pipeline_result', {})
if not pipeline_result:
    # Try extraction_result instead
    pipeline_result = submission.get('extraction_result', {})
    if not pipeline_result:
        print(f"\n❌ No pipeline_result or extraction_result found")
        print(f"\n💡 Try uploading a new answer sheet to test the extraction")
        sys.exit(1)

print(f"\n📊 Pipeline Result:")
print(f"   Status: {pipeline_result.get('status')}")
print(f"   Total time: {pipeline_result.get('total_time_ms', 0)/1000:.2f}s")

# Analyze regions
regions = pipeline_result.get('regions', [])
print(f"\n🔍 Regions Analysis:")
print(f"   Total regions: {len(regions)}")

# Count regions by OCR result
empty_regions = [r for r in regions if not r.get('text') or len(r.get('text', '').strip()) == 0]
low_word_regions = [r for r in regions if r.get('text') and len(r.get('text', '').split()) <= 3]
good_regions = [r for r in regions if r.get('text') and len(r.get('text', '').split()) > 3]

print(f"   Empty regions (0 words): {len(empty_regions)}")
print(f"   Low-word regions (1-3 words): {len(low_word_regions)}")
print(f"   Good regions (>3 words): {len(good_regions)}")

# Analyze question anchors
anchored_regions = [r for r in regions if r.get('question_anchor') is not None]
print(f"\n🎯 Question Anchors Found: {len(anchored_regions)}")
for r in anchored_regions:
    print(f"   Q{r['question_anchor']}: '{r.get('text', '')[:60]}...'")

# Analyze packets
packets = pipeline_result.get('packets', [])
print(f"\n📦 Packets (Questions) Extracted: {len(packets)}")
for p in packets[:10]:  # Show first 10
    q_id = p.get('question_id')
    region_count = len(p.get('regions', []))
    has_table = any(r.get('is_table') for r in p.get('regions', []))
    print(f"   Q{q_id}: {region_count} regions, table={has_table}")

# Check page blocks
page_blocks = pipeline_result.get('page_blocks', [])
print(f"\n📄 Page Blocks:")
for page_idx, blocks in enumerate(page_blocks, 1):
    print(f"   Page {page_idx}: {len(blocks)} blocks")
    
    # Analyze block types
    block_types = {}
    for block in blocks:
        btype = block.get('type', 'unknown')
        block_types[btype] = block_types.get(btype, 0) + 1
    
    for btype, count in block_types.items():
        print(f"      - {btype}: {count}")

# Sample some empty regions to understand why they're empty
print(f"\n🔬 Sample Empty Regions (first 5):")
for i, r in enumerate(empty_regions[:5], 1):
    bbox = r.get('bbox', [])
    page = r.get('page_number')
    block_type = r.get('block_type')
    conf = r.get('ocr_confidence', 0)
    provider = r.get('ocr_provider', 'unknown')
    fallback = r.get('fallback_used', False)
    
    # Calculate region size
    if len(bbox) == 4:
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        area = width * height
        print(f"   {i}. Page {page}, Type: {block_type}")
        print(f"      Size: {width:.0f}x{height:.0f} (area: {area:.0f})")
        print(f"      OCR: {provider}, conf: {conf:.2f}, fallback: {fallback}")
        print(f"      BBox: {bbox}")

# Check if fallback was ever used
fallback_used_count = sum(1 for r in regions if r.get('fallback_used'))
print(f"\n🔄 Fallback Usage:")
print(f"   Regions with fallback: {fallback_used_count}/{len(regions)}")

# Recommendations
print(f"\n💡 Recommendations:")
if len(empty_regions) > len(regions) * 0.5:
    print(f"   ⚠️  Over 50% of regions are empty - likely an image quality or segmentation issue")
    print(f"   → Check if uploaded images are clear and high resolution")
    print(f"   → Consider adjusting layout detection thresholds")

if fallback_used_count == 0 and len(empty_regions) > 10:
    print(f"   ⚠️  Fallback OCR never triggered despite many empty regions")
    print(f"   → Check OCR_FALLBACK_ONLY_IF_EMPTY setting")
    print(f"   → Consider enabling force_fallback for low-confidence regions")

if len(anchored_regions) < 5:
    print(f"   ⚠️  Very few question anchors detected")
    print(f"   → This explains why only {len(packets)} questions were extracted")
    print(f"   → The college layer improvements should help with sequence inference")

print("\n" + "="*70 + "\n")
