# GradeSense Backend

AI-powered exam grading system built with FastAPI, MongoDB, and Google Gemini.

## Project Structure

```
backend/
├── main.py                  # FastAPI entry point
├── .env                     # Environment variables
├── requirements.txt         # Python dependencies
├── start_backend.sh         # Startup script
│
├── app/                     # Application package
│   ├── config.py            # Settings, env vars, logger, Gemini init
│   ├── database.py          # MongoDB & GridFS connection
│   ├── deps.py              # Dependency injection (auth middleware)
│   │
│   ├── models/              # Pydantic request/response models
│   │   ├── admin.py         # Admin panel models
│   │   ├── analytics.py     # Analytics & reporting models
│   │   ├── batch.py         # Batch/class models
│   │   ├── exam.py          # Exam & question models
│   │   ├── feedback.py      # Feedback & re-grading models
│   │   ├── reevaluation.py  # Re-evaluation request models
│   │   ├── subject.py       # Subject models
│   │   ├── submission.py    # Submission & score models
│   │   └── user.py          # User & auth models
│   │
│   ├── routes/              # API endpoint handlers
│   │   ├── admin.py         # Admin panel routes
│   │   ├── analytics.py     # Dashboard analytics & AI insights
│   │   ├── auth.py          # Google OAuth & email/password auth
│   │   ├── batches.py       # Batch/class management
│   │   ├── debug.py         # Debug & health check endpoints
│   │   ├── exams.py         # Exam CRUD & question paper upload
│   │   ├── feedback.py      # AI feedback & re-grading
│   │   ├── grading.py       # Paper grading orchestration
│   │   ├── notifications.py # In-app notifications
│   │   ├── re_evaluations.py# Student re-evaluation requests
│   │   ├── search.py        # Global search
│   │   ├── student_portal.py# Student-facing endpoints
│   │   ├── students.py      # Student management
│   │   ├── subjects.py      # Subject management
│   │   ├── submissions.py   # Submission CRUD & review
│   │   └── uploads.py       # File upload (PDF, ZIP, Google Drive)
│   │
│   ├── services/            # Business logic
│   │   ├── analytics.py     # Analytics computation
│   │   ├── annotation.py    # Image annotation overlays
│   │   ├── background.py    # Background task runner (lifespan)
│   │   ├── extraction.py    # Question & answer extraction via Gemini
│   │   ├── file_processing.py # Image rotation correction
│   │   ├── grading.py       # Core grading logic & prompt engineering
│   │   ├── gridfs_helpers.py# GridFS file storage helpers
│   │   ├── llm.py           # Gemini API wrapper (LlmChat)
│   │   ├── metrics.py       # Grading metrics & statistics
│   │   ├── notifications.py # Notification creation
│   │   ├── student_detection.py # Student name/ID extraction from papers
│   │   └── task_worker.py   # Background worker loop
│   │
│   └── utils/               # Pure utility functions
│       ├── annotation_utils.py  # Annotation types & image rendering
│       ├── auth.py              # JWT token utilities
│       ├── concurrency.py       # Semaphores for rate limiting
│       ├── file_utils.py        # PDF→images, ZIP extraction, GDrive download
│       ├── hashing.py           # Content hashing for caching
│       ├── serialization.py     # MongoDB ObjectId serialization
│       ├── validation.py        # Input validation helpers
│       └── vision_ocr_service.py# Google Cloud Vision OCR
│
└── scripts/                 # One-off migration scripts
    ├── migrate_large_files_to_gridfs.py
    ├── migrate_submission_images_to_gridfs.py
    └── migrate_submissions_to_gridfs.py
```

## Setup

### Prerequisites

- Python 3.11+
- MongoDB (local or Atlas)
- `poppler` for PDF processing: `brew install poppler` (macOS)

### Install & Run

```bash
cd backend

# Create virtual environment (first time only)
python3 -m venv .venv

# Activate it
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start the server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Environment Variables

Create a `.env` file in `backend/`:

```env
# MongoDB (required)
MONGO_URL=mongodb+srv://user:pass@cluster.mongodb.net/
DB_NAME=gradesense

# Google Gemini API (required for grading)
GEMINI_API_KEY=your_gemini_api_key

# Google Vision API (optional, for OCR annotations)
GOOGLE_VISION_API_KEY=your_vision_api_key

# Google OAuth (required for login)
GOOGLE_CLIENT_ID=your_client_id
GOOGLE_CLIENT_SECRET=your_client_secret

# Environment
ENV=development
```

## Architecture Notes

- Single-process architecture. Background tasks run inside the main process via `asyncio.create_task` during FastAPI lifespan.
- Routes are thin — validate input, call a service, return output. Services contain business logic. Utils are pure functions.
- Large files (images, PDFs) are stored in MongoDB GridFS.
- Gemini API calls are rate-limited via `asyncio.Semaphore` in `utils/concurrency.py`.
- Auth uses httpOnly cookies. Google OAuth is the primary method, email/password is the fallback.

## Grading Modes

| Mode | Use Case | Behavior |
|------|----------|----------|
| Strict | Technical exams | Every step required, no alternative methods |
| Balanced | General use (default) | Fair evaluation of method + answer |
| Conceptual | Understanding-focused | Minor errors forgiven, alternatives accepted |
| Lenient | Formative assessment | Effort-based, partial credit for any attempt |
