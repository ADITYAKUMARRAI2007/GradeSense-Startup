"""
Background worker service.
Migrated from server.py run_background_worker (lines 420-435).
"""

from app.config import logger
from app.services.metrics import cleanup_old_metrics


async def run_background_worker():
    """Integrated background worker - processes tasks."""
    logger.info("🔄 Background worker started")
    logger.info("=" * 60)

    # Run cleanup once on startup
    await cleanup_old_metrics()

    try:
        from app.services.task_worker import worker_loop
        await worker_loop()  # runs forever, handles polling internally
    except Exception as e:
        logger.error(f"Background worker error: {e}", exc_info=True)
