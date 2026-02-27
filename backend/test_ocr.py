"""Quick OCR test to diagnose the issue."""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(__file__))

from app.utils.ocr_provider import get_ocr_provider

print("\n" + "="*70)
print("OCR PROVIDER TEST")
print("="*70)

try:
    ocr = get_ocr_provider()
    print(f"\n✅ OCR Provider initialized")
    print(f"   Primary: {ocr.primary}")
    print(f"   Fallback: {ocr.fallback}")
    print(f"   Vision available: {ocr._vision is not None}")
    print(f"   Paddle available: {ocr._paddle is not None}")
    
    # Create a simple test image (white background with black text)
    from PIL import Image, ImageDraw, ImageFont
    import base64
    import io
    
    # Create test image
    img = Image.new('RGB', (800, 200), color='white')
    draw = ImageDraw.Draw(img)
    
    # Draw some text
    try:
        # Try to use a default font
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 40)
    except:
        font = ImageFont.load_default()
    
    draw.text((50, 80), "Question 1: Test Question", fill='black', font=font)
    
    # Convert to base64
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG')
    test_image_b64 = base64.b64encode(buffer.getvalue()).decode()
    
    print(f"\n🧪 Testing with synthetic image...")
    print(f"   Image size: {len(test_image_b64)} bytes")
    
    # Test OCR
    result = ocr.detect(test_image_b64, min_conf=0.3, min_words=1, min_lines=1)
    
    print(f"\n📊 OCR Results:")
    print(f"   Provider: {result.get('provider')}")
    print(f"   Words found: {len(result.get('words', []))}")
    print(f"   Lines found: {len(result.get('lines', []))}")
    print(f"   Fallback used: {result.get('fallback_used')}")
    
    if result.get('words'):
        print(f"\n   Sample words:")
        for word in result['words'][:5]:
            print(f"      - '{word.get('text')}' (conf: {word.get('conf'):.2f})")
    
    if result.get('lines'):
        print(f"\n   Sample lines:")
        for line in result['lines'][:3]:
            print(f"      - '{line.get('text')}' (conf: {line.get('conf'):.2f})")
    
    if len(result.get('words', [])) == 0:
        print(f"\n❌ OCR FAILED - No text detected!")
        print(f"   This explains why question extraction is failing.")
        print(f"\n   Possible causes:")
        print(f"   1. GCP Vision API quota exceeded")
        print(f"   2. API key permissions insufficient")
        print(f"   3. Network/connectivity issues")
        print(f"   4. Image format incompatibility")
    else:
        print(f"\n✅ OCR is working correctly!")
        print(f"   The issue might be with the uploaded answer sheet images.")
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*70 + "\n")
