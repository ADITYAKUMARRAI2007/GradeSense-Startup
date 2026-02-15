"""
API metrics tracking and cleanup.
"""

import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict

from app.database import db
from app.config import logger


async def log_api_metric(endpoint: str, method: str, response_time_ms: int, 
                         status_code: int, error_type: Optional[str], 
                         user_id: Optional[str], ip_address: Optional[str]):
    """Log API metrics to database"""
    try:
        await db.api_metrics.insert_one({
            "endpoint": endpoint,
            "method": method,
            "response_time_ms": response_time_ms,
            "status_code": status_code,
            "error_type": error_type,
            "user_id": user_id,
            "ip_address": ip_address,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    except Exception as e:
        logger.error(f"Failed to log API metric: {e}")

async def log_user_event(event_type: str, user_id: str, role: str, 
                         ip_address: str, metadata: Dict = None):
    """Log user events for analytics"""
    try:
        # Get geo location from IP (simplified - you can use a proper geo IP service)
        country = "Unknown"
        region = "Unknown"
        
        await db.metrics_logs.insert_one({
            "event_id": f"evt_{uuid.uuid4().hex[:12]}",
            "event_type": event_type,
            "user_id": user_id,
            "role": role,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
            "ip_address": ip_address,
            "country": country,
            "region": region
        })
    except Exception as e:
        logger.error(f"Failed to log user event: {e}")


async def cleanup_old_metrics():
    """Delete metrics data older than 1 year, keep aggregated summaries"""
    try:
        one_year_ago = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
        
        # Delete old metrics logs
        result1 = await db.metrics_logs.delete_many({"timestamp": {"$lt": one_year_ago}})
        logger.info(f"Deleted {result1.deleted_count} old metrics_logs records")
        
        # Delete old API metrics
        result2 = await db.api_metrics.delete_many({"timestamp": {"$lt": one_year_ago}})
        logger.info(f"Deleted {result2.deleted_count} old api_metrics records")
        
        # Keep grading_analytics forever as it's valuable for long-term insights
        # but delete associated metadata that's less critical
        
        logger.info("✅ Data cleanup completed successfully")
    except Exception as e:
        logger.error(f"Error during data cleanup: {e}", exc_info=True)
