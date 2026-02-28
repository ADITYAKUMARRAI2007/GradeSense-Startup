"""
Concurrency utilities — semaphores for resource-limited operations.
"""

import asyncio
import os

# Limits concurrent PDF-to-image conversions to avoid memory spikes
_conversion_limit = int(os.getenv("PDF_CONVERSION_CONCURRENCY", "1") or 1)
conversion_semaphore = asyncio.Semaphore(max(1, _conversion_limit))
