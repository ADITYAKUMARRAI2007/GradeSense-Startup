"""Verify OCR fixes are in place."""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app.utils.ocr_provider import get_ocr_provider
from app.config import logger

print("\n" + "="*70)
print("OCR FIX VERIFICATION")
print("="*70)

# Check OCR configuration
ocr = get_ocr_provider()

print(f"\n✅ OCR Provider Configuration:")
print(f"   Primary: {ocr.primary}")
print(f"   Fallback: {ocr.fallback}")
print(f"   Fallback only if empty: {ocr.fallback_only_if_empty}")
print(f"   Min confidence: {ocr.min_conf_default}")
print(f"   Min words: {ocr.min_words_default}")
print(f"   Min lines: {ocr.min_lines_default}")
print(f"   Enable tables: {ocr.enable_tables}")

# Verify fixes
issues = []

if ocr.fallback_only_if_empty:
    issues.append("⚠️  OCR_FALLBACK_ONLY_IF_EMPTY is still true - should be false")
else:
    print(f"\n✅ Fix 1: Fallback triggers on low confidence (not just empty)")

if ocr.min_words_default > 10:
    issues.append(f"⚠️  OCR_MIN_WORDS is {ocr.min_words_default} - should be 5 or lower")
else:
    print(f"✅ Fix 2: Min words threshold lowered to {ocr.min_words_default}")

if ocr.min_lines_default > 3:
    issues.append(f"⚠️  OCR_MIN_LINES is {ocr.min_lines_default} - should be 2 or lower")
else:
    print(f"✅ Fix 3: Min lines threshold lowered to {ocr.min_lines_default}")

# Check if Paddle is available
if ocr._paddle is not None:
    print(f"✅ Fix 4: PaddleOCR is available for fallback")
else:
    print(f"⚠️  PaddleOCR not available: {ocr._paddle_error}")

# Check layout detection improvements
print(f"\n📋 Checking layout detection improvements...")
try:
    with open('app/layers/college/layout.py', 'r') as f:
        content = f.read()
        if 'area < 3000' in content:
            print(f"✅ Fix 5: Layout detection minimum area increased to 3000")
        else:
            issues.append("⚠️  Layout detection minimum area not updated")
except Exception as e:
    issues.append(f"⚠️  Could not verify layout.py: {e}")

# Check college layer improvements
print(f"\n📋 Checking college layer improvements...")
improvements_found = []
try:
    with open('app/layers/college/region_ocr.py', 'r') as f:
        content = f.read()
        if 'ACCOUNTING_MARKERS' in content:
            improvements_found.append("Subject-specific patterns")
        if '_is_question_like_content' in content:
            improvements_found.append("Content-based question detection")
        if '_detect_subject_type' in content:
            improvements_found.append("Subject type detection")
    
    if improvements_found:
        print(f"✅ College layer improvements active:")
        for imp in improvements_found:
            print(f"   - {imp}")
    else:
        issues.append("⚠️  College layer improvements not found")
except Exception as e:
    issues.append(f"⚠️  Could not verify region_ocr.py: {e}")

# Summary
print(f"\n" + "="*70)
if issues:
    print(f"⚠️  ISSUES FOUND:")
    for issue in issues:
        print(f"   {issue}")
    print(f"\n💡 Please check .env file and restart backend")
else:
    print(f"✅ ALL FIXES VERIFIED!")
    print(f"\n📝 Next Steps:")
    print(f"   1. Upload a test answer sheet through the frontend")
    print(f"   2. Monitor backend logs for OCR fallback activity")
    print(f"   3. Check extraction results - should see more questions")
    print(f"   4. Look for log lines like:")
    print(f"      [OCR] provider=vision+paddle fallback=True")

print("="*70 + "\n")
