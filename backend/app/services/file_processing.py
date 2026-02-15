"""
PDF-to-image conversion and rotation correction.
"""

import io
import base64
from typing import List

import fitz
from PIL import Image

from app.config import logger


def pdf_to_images(pdf_bytes: bytes) -> List[str]:
    """Convert PDF pages to base64 images with compression - NO PAGE LIMIT"""
    images = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    
    # Process ALL pages - no limit
    for page_num in range(len(doc)):
        page = doc[page_num]
        # Use 1.5x zoom for balance between quality and token efficiency
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
        img_bytes = pix.tobytes("jpeg")
        
        # Compress the image to save storage (40-60% reduction)
        img = Image.open(io.BytesIO(img_bytes))
        
        # Compress with quality=60 (good balance of quality vs size)
        compressed_buffer = io.BytesIO()
        img.save(compressed_buffer, format="JPEG", quality=60, optimize=True)
        compressed_bytes = compressed_buffer.getvalue()
        
        # Convert to base64
        img_base64 = base64.b64encode(compressed_bytes).decode()
        images.append(img_base64)
    
    doc.close()
    logger.info(f"Converted PDF with {len(images)} pages to compressed images")
    return images

def detect_and_correct_rotation(image_base64: str) -> str:
    """
    Detect if an image is rotated and correct it.
    Uses PIL to analyze image orientation and rotate if needed.
    """
    from PIL import Image
    import io
    import base64
    
    try:
        # Decode base64 to image
        img_bytes = base64.b64decode(image_base64)
        img = Image.open(io.BytesIO(img_bytes))
        
        # Check EXIF orientation tag if available
        try:
            from PIL import ExifTags
            for orientation in ExifTags.TAGS.keys():
                if ExifTags.TAGS[orientation] == 'Orientation':
                    break
            exif = img._getexif()
            if exif is not None:
                orientation_value = exif.get(orientation)
                if orientation_value == 3:
                    img = img.rotate(180, expand=True)
                elif orientation_value == 6:
                    img = img.rotate(270, expand=True)
                elif orientation_value == 8:
                    img = img.rotate(90, expand=True)
        except (AttributeError, KeyError, IndexError):
            pass
        
        # Heuristic: Check if image is landscape but contains portrait text
        # Most answer sheets are portrait, so if width > height significantly, it might be rotated
        width, height = img.size
        if width > height * 1.3:  # Landscape orientation
            # Rotate 90 degrees counter-clockwise to make it portrait
            img = img.rotate(90, expand=True)
            logger.info(f"Rotated landscape image to portrait")
        
        # Convert back to base64
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        return base64.b64encode(buffer.getvalue()).decode()
        
    except Exception as e:
        logger.error(f"Error in rotation detection: {e}")
        return image_base64  # Return original if detection fails

def correct_all_images_rotation(images: List[str]) -> List[str]:
    """Apply rotation correction to all images in a list."""
    corrected = []
    for idx, img in enumerate(images):
        corrected_img = detect_and_correct_rotation(img)
        corrected.append(corrected_img)
    return corrected
