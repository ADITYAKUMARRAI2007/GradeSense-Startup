"""
GradeSense API — main entry point.
Creates FastAPI app, sets up lifespan (background worker), CORS, metrics middleware,
registers all routes.
"""

import os
import time
import asyncio
import subprocess
import shutil

from fastapi import FastAPI, APIRouter, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import logger, get_version_info
from app.database import client
from app.services.background import run_background_worker
from app.services.metrics import log_api_metric
from app.routes import register_all_routes

# Global reference to the background worker task
_worker_task = None


async def lifespan(app: FastAPI):
    """Application lifespan manager - starts/stops background worker"""
    global _worker_task

    # Startup: Check system dependencies
    logger.info("🚀 FastAPI app starting up...")
    logger.info("REGISTERED ROUTES: %s", [r.path for r in app.routes])
    logger.info("🔍 Checking system dependencies...")

    # Check if poppler-utils is installed
    if not shutil.which("pdftoppm"):
        logger.warning("⚠️  poppler-utils not found. Attempting to install...")
        try:
            subprocess.run(
                ["sudo", "apt-get", "update", "-qq"],
                check=True, capture_output=True
            )
            subprocess.run(
                ["sudo", "apt-get", "install", "-y", "poppler-utils"],
                check=True, capture_output=True
            )
            logger.info("✅ poppler-utils installed successfully")
        except Exception as e:
            logger.error(f"❌ Failed to install poppler-utils: {e}")
            logger.error("⚠️  PDF processing may not work correctly!")
    else:
        logger.info("✅ poppler-utils is already installed")

    logger.info("🔄 Starting integrated background task worker...")
    _worker_task = asyncio.create_task(run_background_worker())
    logger.info("🔄 Background worker started")
    logger.info("=" * 60)

    yield

    # Shutdown: Cancel the background worker
    logger.info("🛑 FastAPI app shutting down...")
    if _worker_task and not _worker_task.done():
        logger.info("⏹️  Stopping background task worker...")
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            logger.info("✅ Background task worker stopped cleanly")


# Create the main app with lifespan
app = FastAPI(title="GradeSense API", lifespan=lifespan)

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")


@api_router.get("/version")
async def get_version():
    """Public version endpoint for deployment verification"""
    return get_version_info()


# Register all route modules on the api_router
register_all_routes(api_router)

# Include the api_router on the app
app.include_router(api_router)


# Root-level health check endpoint (for Kubernetes probes)
@app.get("/health")
async def root_health_check():
    """Health check for Kubernetes liveness/readiness probes"""
    return {"status": "healthy", "service": "GradeSense API"}


# ============== METRICS TRACKING MIDDLEWARE ==============

@app.middleware("http")
async def metrics_tracking_middleware(request: Request, call_next):
    """Track API metrics for all requests"""
    start_time = time.time()

    user_id = None
    try:
        if request.url.path != "/api/auth/me":
            auth_header = request.headers.get("cookie", "")
            if "session" in auth_header:
                pass
    except:
        pass

    response = None
    error_type = None
    status_code = 500

    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception as e:
        error_type = type(e).__name__
        status_code = 500
        logger.error(f"Request failed: {str(e)}")
        raise
    finally:
        response_time_ms = int((time.time() - start_time) * 1000)

        asyncio.create_task(log_api_metric(
            endpoint=request.url.path,
            method=request.method,
            response_time_ms=response_time_ms,
            status_code=status_code,
            error_type=error_type,
            user_id=user_id,
            ip_address=request.client.host if request.client else None
        ))

    return response


# ============== CORS ==============

cors_origins_env = os.environ.get("CORS_ORIGINS")
cors_origins = [origin.strip() for origin in cors_origins_env.split(",")] if cors_origins_env else [
    "http://localhost:3000",
    "http://127.0.0.1:3000"
]

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
