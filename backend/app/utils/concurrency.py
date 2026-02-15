"""
Concurrency utilities — semaphores for resource-limited operations.
"""

import asyncio

# Limits concurrent PDF-to-image conversions to avoid memory spikes
conversion_semaphore = asyncio.Semaphore(3)
