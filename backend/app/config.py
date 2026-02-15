"""
Configuration - env vars, constants, API key setup.
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv
import google.generativeai as genai

ROOT_DIR = Path(__file__).parent.parent
load_dotenv(ROOT_DIR / '.env')

# ============ GCP CREDENTIALS SETUP ============
# This ensures Google Cloud Vision API can authenticate
gcp_credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
if gcp_credentials_path:
    # Make path absolute relative to ROOT_DIR if needed
    if not Path(gcp_credentials_path).is_absolute():
        gcp_credentials_path = ROOT_DIR / gcp_credentials_path
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(gcp_credentials_path)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger_setup = logging.getLogger("gradesense")
    logger_setup.info(f"✅ GCP credentials configured at: {gcp_credentials_path}")

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("gradesense")

# LLM API Key
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    logger.warning("⚠️ No GEMINI_API_KEY found - AI grading will fail")
else:
    genai.configure(api_key=GEMINI_API_KEY)


def get_llm_api_key():
    """Get the LLM API key from environment variables."""
    return GEMINI_API_KEY


def get_version_info():
    """Get deployment version information."""
    git_commit = os.environ.get("GIT_COMMIT_SHA")
    if not git_commit:
        try:
            if os.path.exists(".git_commit"):
                with open(".git_commit", "r") as f:
                    git_commit = f.read().strip()
        except Exception:
            pass

    if not git_commit:
        logger.warning("GIT_COMMIT_SHA not set and .git_commit not found. Build pipeline issue?")
        git_commit = "unknown"

    build_time = os.environ.get("BUILD_TIME", "unknown")
    env = os.environ.get("ENV", os.environ.get("ENVIRONMENT", "development"))

    return {
        "git_commit": git_commit,
        "build_time": build_time,
        "environment": env
    }
