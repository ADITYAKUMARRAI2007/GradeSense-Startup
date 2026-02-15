"""
File utilities — PDF/image conversion, ZIP extraction, Google Drive download.
"""

import io
import os
import re
import base64
import zipfile
import tempfile
import requests
from typing import List, Tuple, Optional

from app.config import logger
from app.services.file_processing import pdf_to_images


def convert_to_images(file_bytes: bytes, filename: str = "") -> List[str]:
    """
    Convert an uploaded file (PDF or image) to a list of base64 image strings.
    """
    ext = os.path.splitext(filename)[1].lower() if filename else ""

    if ext == ".pdf" or (not ext and file_bytes[:5] == b"%PDF-"):
        return pdf_to_images(file_bytes)

    # Single image file
    try:
        img_base64 = base64.b64encode(file_bytes).decode()
        return [img_base64]
    except Exception as e:
        logger.error(f"Failed to convert file to image: {e}")
        return []


def extract_zip_files(zip_bytes: bytes) -> List[Tuple[str, bytes]]:
    """
    Extract files from a ZIP archive.
    Returns list of (filename, file_bytes) tuples.
    """
    results = []
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for name in zf.namelist():
                # Skip directories and hidden files
                if name.endswith("/") or name.startswith("__MACOSX") or name.startswith("."):
                    continue
                ext = os.path.splitext(name)[1].lower()
                if ext in (".pdf", ".png", ".jpg", ".jpeg"):
                    results.append((os.path.basename(name), zf.read(name)))
    except Exception as e:
        logger.error(f"Error extracting ZIP: {e}")
    return results


def extract_file_id_from_url(url: str) -> Optional[str]:
    """Extract Google Drive file ID from various URL formats."""
    patterns = [
        r"/file/d/([a-zA-Z0-9_-]+)",
        r"id=([a-zA-Z0-9_-]+)",
        r"/d/([a-zA-Z0-9_-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def download_from_google_drive(file_id: str) -> Optional[bytes]:
    """Download a file from Google Drive using its file ID."""
    try:
        url = f"https://drive.google.com/uc?export=download&id={file_id}"
        session = requests.Session()
        response = session.get(url, stream=True, timeout=60)

        # Handle large file confirmation page
        for key, value in response.cookies.items():
            if key.startswith("download_warning"):
                url = f"https://drive.google.com/uc?export=download&confirm={value}&id={file_id}"
                response = session.get(url, stream=True, timeout=60)
                break

        if response.status_code == 200:
            content = response.content
            if len(content) > 0:
                return content
        logger.error(f"Google Drive download failed: status {response.status_code}")
        return None
    except Exception as e:
        logger.error(f"Error downloading from Google Drive: {e}")
        return None
