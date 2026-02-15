"""
Background task worker — polls for pending tasks and processes them.
"""

import asyncio

from app.config import logger


async def worker_loop():
    """
    Main worker loop. Runs indefinitely, polling for background tasks.
    Currently a no-op placeholder — grading jobs are dispatched directly
    via asyncio.create_task in the route handlers.
    """
    logger.info("🔄 Task worker loop started (idle polling)")
    while True:
        await asyncio.sleep(60)
