"""
Configuration - env vars, constants, API key setup.
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

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


def _env_flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


COLLEGE_V2_PIPELINE_ENABLED = _env_flag("COLLEGE_V2_PIPELINE_ENABLED", "true")
COLLEGE_V2_HARD_STOP = _env_flag("COLLEGE_V2_HARD_STOP", "true")
UNIVERSAL_PIPELINE_ENABLED = _env_flag("UNIVERSAL_PIPELINE_ENABLED", "false")
UNIVERSAL_HARD_STOP = _env_flag("UNIVERSAL_HARD_STOP", "true")
UNIVERSAL_PIPELINE_EXAM_TYPES = [
    item.strip().lower()
    for item in os.getenv("UNIVERSAL_PIPELINE_EXAM_TYPES", "college,school,universal").split(",")
    if item.strip()
]
UNIVERSAL_ORPHAN_BLOCK_RATIO_THRESHOLD = float(os.getenv("UNIVERSAL_ORPHAN_BLOCK_RATIO_THRESHOLD", "0.15"))
UNIVERSAL_CONTINUITY_SPATIAL_WEIGHT = float(os.getenv("UNIVERSAL_CONTINUITY_SPATIAL_WEIGHT", "0.4"))
UNIVERSAL_CONTINUITY_STRUCTURAL_WEIGHT = float(os.getenv("UNIVERSAL_CONTINUITY_STRUCTURAL_WEIGHT", "0.3"))
UNIVERSAL_CONTINUITY_SEMANTIC_WEIGHT = float(os.getenv("UNIVERSAL_CONTINUITY_SEMANTIC_WEIGHT", "0.3"))
UNIVERSAL_CONTINUITY_ATTACH_THRESHOLD = float(os.getenv("UNIVERSAL_CONTINUITY_ATTACH_THRESHOLD", "0.65"))
UNIVERSAL_CONTINUITY_MAX_PAGE_GAP = int(os.getenv("UNIVERSAL_CONTINUITY_MAX_PAGE_GAP", "1"))
UNIVERSAL_CONTINUITY_SEMANTIC_PROVIDER = os.getenv("UNIVERSAL_CONTINUITY_SEMANTIC_PROVIDER", "gemini").strip().lower()

# AWS Textract pipeline flags
AWS_PIPELINE_ENABLED = _env_flag("AWS_PIPELINE_ENABLED", "false")
AWS_PIPELINE_EXAM_TYPES = [
    item.strip().lower()
    for item in os.getenv("AWS_PIPELINE_EXAM_TYPES", "college").split(",")
    if item.strip()
]
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET", "")
AWS_TEXTRACT_ROLE_ARN = os.getenv("AWS_TEXTRACT_ROLE_ARN", "")
AWS_TEXTRACT_POLL_INTERVAL_SECS = int(os.getenv("AWS_TEXTRACT_POLL_INTERVAL_SECS", "2"))
AWS_TEXTRACT_POLL_TIMEOUT_SECS = int(os.getenv("AWS_TEXTRACT_POLL_TIMEOUT_SECS", "900"))
AWS_TEXTRACT_ENABLE_TABLES = _env_flag("AWS_TEXTRACT_ENABLE_TABLES", "false")

# Marking scheme validation
MARK_VALIDATION_ENABLED = _env_flag("MARK_VALIDATION_ENABLED", "true")


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
