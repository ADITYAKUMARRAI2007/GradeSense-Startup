# GradeSense Backend — Complete Functional Breakdown

This is a precise map of everything `server.py` does, organized by functional domain. Each section lists the exact endpoints, helper functions, and what they achieve. This will serve as the blueprint for the modular rewrite.

---

## 1. APP SETUP & INFRASTRUCTURE

**What it does:** Boots the FastAPI app, connects to MongoDB (async + sync for GridFS), configures Gemini API, starts a background worker, sets up CORS, and registers all routes under `/api`.

**Components:**
- `lifespan()` — Startup: checks for poppler-utils, starts background worker via `asyncio.create_task(run_background_worker())`. Shutdown: cancels worker.
- `run_background_worker()` — Runs `cleanup_old_metrics()` once, then delegates to `task_worker.worker_loop()` for the MongoDB-based task queue.
- `cleanup_old_metrics()` — Deletes metrics/api_metrics older than 1 year.
- `metrics_tracking_middleware()` — HTTP middleware that times every request and logs endpoint, method, response time, status code to `api_metrics` collection.
- `log_api_metric()` — Writes a single metric document to MongoDB.
- `log_user_event()` — Writes user events (login, actions) to `metrics_logs`.
- CORS configured from `CORS_ORIGINS` env var, defaults to localhost:3000.
- Two MongoDB clients: async (`motor`) for all app queries, sync (`pymongo`) for GridFS.
- In-memory caches: `grading_cache` dict, `model_answer_cache` dict.

**Endpoints:**
- `GET /health` — Kubernetes health check (root level, outside `/api`)
- `GET /api/version` — Returns git commit, build time, environment

---

## 2. AUTHENTICATION & USER MANAGEMENT

**What it does:** Handles Google OAuth login, email/password registration/login, session management, profile completion, and user lookup.

**Key helper:**
- `get_current_user(request)` — FastAPI dependency. Extracts session token from cookie or Authorization header. Tries JWT decode first (email/password users), falls back to session lookup in MongoDB (OAuth users). Checks account status (active/disabled/banned). Throttled `last_login` update (every 5 min).

**Endpoints:**
- `POST /api/auth/google/callback` — Exchanges Google auth code for access token, fetches user info from Google, creates or updates user in DB, creates session, sets httpOnly cookie. Handles existing students (created by teacher) vs new users.
- `POST /api/auth/session` — Validates a session_id (legacy Emergent auth compatibility).
- `POST /api/auth/register` — Email/password registration. Hashes password with bcrypt, creates JWT token, sets cookie.
- `POST /api/auth/set-password` — Lets Google OAuth users add a password to their account.
- `POST /api/auth/login` — Email/password login. Verifies password, creates JWT, sets cookie.
- `GET /api/auth/me` — Returns current user profile.
- `POST /api/auth/logout` — Deletes session from DB, clears cookie.
- `POST /api/auth/complete-profile` — Saves teacher type, exam category, contact info. Marks `profile_completed = true`.
- `GET /api/auth/check-profile` — Returns whether profile setup is complete.

---

## 3. BATCH MANAGEMENT

**What it does:** Teachers organize students into batches (classes/sections). Batches can be opened/closed.

**Endpoints:**
- `GET /api/batches` — List teacher's batches (with student count).
- `GET /api/batches/{batch_id}` — Get single batch with student details.
- `POST /api/batches` — Create batch.
- `PUT /api/batches/{batch_id}` — Update batch name.
- `DELETE /api/batches/{batch_id}` — Delete batch + cascade delete all exams and submissions in that batch.
- `POST /api/batches/{batch_id}/close` — Mark batch as closed.
- `POST /api/batches/{batch_id}/reopen` — Reopen a closed batch.
- `POST /api/batches/{batch_id}/add-student` — Add student to batch by email (creates student user if needed).
- `DELETE /api/batches/{batch_id}/students/{student_id}` — Remove student from batch.

---

## 4. SUBJECT MANAGEMENT

**What it does:** Teachers create subjects (Math, Physics, etc.) that exams are linked to.

**Endpoints:**
- `GET /api/subjects` — List teacher's subjects.
- `POST /api/subjects` — Create subject.

---

## 5. STUDENT MANAGEMENT

**What it does:** CRUD for student users. Teachers can create students, view their details, and see per-student analytics.

**Endpoints:**
- `GET /api/students` — List students (optionally filtered by batch).
- `GET /api/students/{student_user_id}` — Detailed student profile with exam history, scores, performance trends.
- `POST /api/students` — Create student user (teacher creates on behalf of student).
- `PUT /api/students/{student_user_id}` — Update student info.
- `DELETE /api/students/{student_user_id}` — Delete student + remove from all batches.

---

## 6. EXAM MANAGEMENT

**What it does:** Full exam lifecycle — create, configure, upload papers, extract questions, manage status.

**Endpoints:**
- `GET /api/exams` — List exams (filterable by batch_id, subject_id).
- `POST /api/exams` — Create exam (name, batch, subject, total marks, grading mode, exam mode).
- `GET /api/exams/{exam_id}` — Get exam details with questions.
- `PUT /api/exams/{exam_id}` — Update exam metadata (name, marks, questions, grading mode).
- `DELETE /api/exams/{exam_id}` — Delete exam + cascade delete all submissions, model answers, cache entries, grading jobs, GridFS files.
- `POST /api/exams/{exam_id}/close` — Close exam (no more submissions).
- `POST /api/exams/{exam_id}/reopen` — Reopen closed exam.
- `POST /api/exams/{exam_id}/extract-questions` — Trigger AI extraction of questions from uploaded question paper.
- `POST /api/exams/{exam_id}/re-extract-questions` — Force re-extraction (ignores cache).

**Student-upload mode:**
- `POST /api/student-exams` — Create exam where students upload their own papers.
- `GET /api/student-exams/{exam_id}/status` — Check if current student has submitted.
- `POST /api/student-exams/{exam_id}/submit` — Student uploads their answer paper.
- `DELETE /api/student-exams/{exam_id}/students/{student_id}` — Remove student from exam.
- `POST /api/student-exams/{exam_id}/grade` — Teacher triggers grading of all student submissions.

---

## 7. FILE UPLOAD & PROCESSING

**What it does:** Handles upload of question papers, model answers, and student papers. Converts PDFs to images. Stores large files in GridFS.

**Endpoints:**
- `POST /api/upload-model-answer` — Upload model answer PDF. Converts to images, stores in GridFS, triggers answer text extraction via Gemini OCR.
- `POST /api/upload-question-paper` — Upload question paper PDF. Converts to images, stores in GridFS, triggers question extraction via Gemini.
- `POST /api/upload-student-papers` — Upload student papers (multiple PDFs/images/ZIP). Converts each to images, extracts student info from first page.
- `POST /api/exams/{exam_id}/upload-more-papers` — Add more student papers to an existing exam (same logic as above).

**Key helpers:**
- `pdf_to_images(pdf_bytes)` — PyMuPDF conversion at 2x zoom → base64 JPEG.
- `detect_and_correct_rotation(image_base64)` — Pillow-based rotation correction.
- `extract_student_info_from_paper(file_images, filename)` — Sends first page to Gemini to extract student name and roll number.
- `parse_student_from_filename(filename)` — Regex fallback for extracting student info from filename.
- `get_or_create_student(...)` — Finds or creates student user, adds to batch.
- `get_exam_model_answer_images(exam_id)` — Retrieves model answer images from GridFS (with fallback to old inline storage).
- `get_exam_question_paper_images(exam_id)` — Same for question paper.

---

## 8. QUESTION & ANSWER EXTRACTION (AI)

**What it does:** Uses Gemini to extract structured questions from question papers and OCR model answer text.

**Key functions:**
- `extract_questions_from_question_paper(images, exam)` — Sends question paper images to Gemini with a structured prompt. Returns JSON array of questions with numbers, text, marks, rubrics, sub-questions.
- `extract_questions_from_model_answer(images, exam)` — Extracts questions from model answer sheet when no question paper is uploaded.
- `extract_question_structure_from_paper(images, exam)` — Extracts questions from student answer papers when neither question paper nor model answer is uploaded.
- `extract_model_answer_content(images, questions, exam_id)` — OCRs model answer text per question. Used for text-based grading (faster than image-based).
- `auto_extract_questions(exam_id, force)` — Orchestrator that tries question paper first, then model answer, then student papers.
- `get_exam_model_answer_text(exam_id)` — Retrieves cached model answer text.

---

## 9. GRADING ENGINE (AI) — The Core

**What it does:** Grades student papers using Gemini. This is the most complex part of the system.

**Key function:**
- `grade_with_ai(images, model_answer_images, questions, grading_mode, ...)` — The main grading function (~1500 lines). Does:
  1. Rotation correction on student images
  2. Fetches teacher's learned patterns (past corrections)
  3. Decides text-based vs image-based grading
  4. Builds the master system prompt (grading mode rules + UPSC/college context + annotation instructions)
  5. Chunks student paper into 10-page segments with 1-page overlap
  6. For each chunk: sends images + prompt to Gemini, parses JSON response, retries on failure (3 attempts with exponential backoff)
  7. Merges chunk results (handles "not found" across chunks)
  8. Validates marks (no exceeding max, sub-score sum checks)
  9. Applies UPSC caps in strict mode
  10. Caches results (in-memory + MongoDB)
  11. Returns list of QuestionScore objects

**Grading modes** (each has a detailed prompt):
- `strict` — UPSC-level. All or nothing. Perfect = full marks, any error = 0.
- `balanced` — Fair. 60% process, 40% outcome. Partial credit.
- `conceptual` — Understanding over execution. Alternative methods accepted.
- `lenient` — Effort-based. Floor marks for any attempt.

**UPSC detection:**
- `infer_upsc_paper(exam_name, subject_name)` — Detects GS-1 through GS-4, Essay papers from names.
- Separate system prompts for UPSC (with ARC framework, scoring ceilings, value indicators) vs college.

**Annotation generation within grading:**
- `normalize_ai_annotations(raw_annotations)` — Converts Gemini's annotation output into standardized AnnotationData objects. Handles multiple styles (TICK, CROSS, BOX_COMMENT, MARGIN_LEASH, MARGIN_NOTE, EMPHASIS_UNDERLINE, etc.). Limits density to 6 annotations per page.

---

## 10. BACKGROUND GRADING & JOB MANAGEMENT

**What it does:** Processes grading jobs asynchronously so the HTTP request doesn't timeout.

**Endpoints:**
- `POST /api/grade-papers` — Starts a background grading job. Creates job document, launches `asyncio.create_task`. Returns job_id immediately.
- `GET /api/grading-job/{job_id}` — Poll job status (processing/completed/failed, progress count).
- `POST /api/grading-job/{job_id}/cancel` — Cancel a running job.
- `POST /api/exams/{exam_id}/regrade-all` — Re-grades all submissions for an exam (skips cache).

**Key function:**
- `process_grading_job_in_background(job_id, exam_id, files_data, exam, teacher_id)` — For each student paper: converts to images, extracts student info, calls `grade_with_ai`, generates annotated images, saves submission to DB, updates job progress. Handles errors per-paper (one failure doesn't stop the batch). Creates notification on completion.

**Task worker (`task_worker.py`):**
- MongoDB-based task queue. Polls `tasks` collection for pending tasks.
- Handles `grade_papers` and `grade_single_paper` task types.
- `cleanup_stuck_jobs()` — Resets jobs stuck in "processing" for >30 minutes.

---

## 11. IMAGE ANNOTATION SYSTEM

**What it does:** Generates annotated versions of student papers with visual grading marks overlaid.

**Key function:**
- `generate_annotated_images_with_vision_ocr(images, question_scores, exam_id)` — For each page:
  1. Collects annotations from grading results
  2. Uses Google Cloud Vision OCR to find exact pixel coordinates of anchor text
  3. Draws annotations using Pillow (ticks, crosses, underlines, boxes, margin notes)
  4. Returns base64-encoded annotated images

**Fallback:**
- `generate_annotated_images(images, question_scores)` — Simpler annotation without OCR. Places marks in margins based on question order.
- `_generate_margin_annotations(images, question_scores)` — Generates margin-only annotations (score boxes, brief feedback).

---

## 12. SUBMISSION MANAGEMENT

**What it does:** CRUD for graded student submissions. Teachers can review, edit scores, approve.

**Endpoints:**
- `GET /api/submissions` — List submissions (filterable by exam_id, student_id).
- `GET /api/submissions/{submission_id}` — Get full submission with scores, annotated images, feedback.
- `PUT /api/submissions/{submission_id}` — Teacher edits scores/feedback on a submission.
- `DELETE /api/submissions/{submission_id}` — Delete a submission.
- `GET /api/exams/{exam_id}/submissions` — List all submissions for an exam.
- `POST /api/exams/{exam_id}/bulk-approve` — Approve all submissions in an exam.
- `POST /api/submissions/{submission_id}/unapprove` — Unapprove a submission.

**Helper:**
- `track_teacher_edits(submission_id, question_number, original_score, new_score, teacher_id)` — Logs when a teacher changes an AI grade (used for learning patterns).

---

## 13. RE-EVALUATION SYSTEM

**What it does:** Students can request re-evaluation of specific questions. Teachers review and resolve.

**Endpoints:**
- `GET /api/re-evaluations` — List re-evaluation requests (teacher sees their students', students see their own).
- `POST /api/re-evaluations` — Student submits re-evaluation request (submission_id, question numbers, reason).
- `PUT /api/re-evaluations/{request_id}` — Teacher resolves request (approve/reject with response).

---

## 14. GRADING FEEDBACK & TEACHER LEARNING

**What it does:** Teachers provide corrections to AI grading. These corrections are stored and fed back into future grading prompts as "learned patterns."

**Endpoints:**
- `POST /api/grading-feedback` — Submit feedback on a specific question's grading (expected grade, correction text).
- `POST /api/grading-feedback/apply-batch` — Apply a correction to all papers in a batch for a specific question.
- `POST /api/grading-feedback/apply-all` — Apply feedback to all papers (re-grades using AI with the correction as context).
- `POST /api/grading-feedback/apply-multiple-all` — Apply multiple feedback items to all papers at once.
- `GET /api/grading-feedback/my-feedback` — Get teacher's own feedback history.
- `GET /api/grading-feedback/patterns/{teacher_id}` — Get teacher's feedback patterns.
- `GET /api/grading-feedback/common-patterns` — Get common patterns across all teachers.

**Key helper:**
- `fetch_teacher_learning_patterns(teacher_id, subject_id, exam_id)` — Fetches past corrections for a teacher+subject combo. These are injected into the grading prompt so the AI learns the teacher's preferences.

---

## 15. ANALYTICS & REPORTING (Teacher)

**What it does:** Comprehensive analytics dashboards for teachers.

**Endpoints:**
- `GET /api/dashboard/analytics` — Overview stats (total exams, students, submissions, average scores).
- `GET /api/dashboard/class-snapshot` — Class performance snapshot (average, pass rate, trends, top/struggling students).
- `GET /api/dashboard/actionable-stats` — Actionable insights (pending reviews, quality concerns, at-risk students, hardest concepts).
- `GET /api/analytics/class-report` — Detailed class report (score distribution, per-question analysis, per-student breakdown).
- `GET /api/analytics/class-insights` — AI-generated insights about class performance.
- `GET /api/analytics/misconceptions` — Common misconceptions identified from grading feedback.
- `GET /api/analytics/topic-mastery` — Topic mastery heatmap (extracted from rubrics).
- `GET /api/analytics/student-deep-dive` — Deep dive into individual student performance.
- `GET /api/analytics/review-packet` — AI-generated practice questions based on weak areas.
- `POST /api/analytics/infer-topics` — AI infers topic tags for questions from rubrics.
- `PUT /api/analytics/update-topics` — Manually update question topic tags.
- `GET /api/batches/{batch_id}/stats` — Batch-level statistics.
- `GET /api/batches/{batch_id}/students` — Students in batch with performance data.
- `GET /api/students/{student_id}/analytics` — Per-student analytics across exams.

---

## 16. ANALYTICS & REPORTING (Student)

**What it does:** Student-facing dashboards and self-service analytics.

**Endpoints:**
- `GET /api/student/dashboard` — Student's own dashboard (exams, scores, trends).
- `GET /api/student/exams` — List exams the student is enrolled in.
- `GET /api/student/topic-drilldown` — Topic-level performance breakdown.
- `GET /api/student/question-drilldown` — Question-level performance breakdown.
- `GET /api/student/journey` — Performance journey over time.
- `POST /api/student/ask-ai` — AI-powered Q&A about the student's own performance.
- `GET /api/student/bluff-index` — "Bluff index" — detects if student's answers are superficially long but low quality.
- `GET /api/student/syllabus-coverage` — How much of the syllabus has been covered in exams.
- `GET /api/student/peer-groups` — Peer group suggestions based on performance similarity.
- `POST /api/student/peer-groups/email` — Send peer group study suggestions via email.

---

## 17. NATURAL LANGUAGE ANALYTICS ("Ask Your Data")

**What it does:** Teachers can ask questions in plain English and get data + visualizations.

**Endpoint:**
- `POST /api/analytics/ask` — Takes a natural language query (e.g., "Show me top 5 students in Math"). Sends query + context (exams, batches, subjects) to Gemini. Gemini returns a structured response with chart type, data, and interpretation. Backend executes the actual DB query and returns results.

---

## 18. STUDY MATERIALS

**What it does:** Simple CRUD for study materials linked to subjects.

**Endpoint:**
- `GET /api/study-materials` — List study materials (filterable by subject).

---

## 19. NOTIFICATION SYSTEM

**What it does:** In-app notifications for teachers and students.

**Endpoints:**
- `GET /api/notifications` — Get user's notifications (last 50, sorted by date).
- `PUT /api/notifications/{id}/read` — Mark as read.
- `PUT /api/notifications/mark-all-read` — Mark all as read.
- `DELETE /api/notifications/clear-all` — Delete all.
- `DELETE /api/notifications/{id}` — Delete one.

**Helper:**
- `create_notification(user_id, type, title, message, link)` — Creates notification document. Called after grading completes, re-evaluation resolved, etc.

---

## 20. GLOBAL SEARCH

**What it does:** Search across exams, students, batches, and submissions.

**Endpoint:**
- `POST /api/search` — Takes a query string, searches across multiple collections, returns categorized results.

---

## 21. RESULT PUBLISHING

**What it does:** Teachers can publish/unpublish exam results so students can see them.

**Endpoints:**
- `POST /api/exams/{exam_id}/publish-results` — Publish results (optionally notify students).
- `POST /api/exams/{exam_id}/unpublish-results` — Unpublish results.

---

## 22. ADMIN PANEL

**What it does:** Admin-only endpoints for platform management.

**Endpoints:**
- `GET /api/admin/check` — Check if current user is admin.
- `GET /api/admin/dashboard-stats` — Platform-wide stats (total users, exams, submissions).
- `GET /api/admin/users` — List all users.
- `GET /api/admin/users/{user_id}` — Detailed user info with usage stats.
- `PUT /api/admin/users/{user_id}/features` — Toggle feature flags for a user.
- `PUT /api/admin/users/{user_id}/quotas` — Set usage quotas.
- `PUT /api/admin/users/{user_id}/status` — Enable/disable/ban user.
- `GET /api/admin/feedback` — View all user feedback.
- `PUT /api/admin/feedback/{id}/resolve` — Resolve feedback item.
- `GET /api/admin/metrics` — Comprehensive platform metrics (usage, grading quality, costs, geographic distribution).
- `GET /api/admin/export-users` — Export users as JSON (API key auth, not session auth).

---

## 23. USER FEEDBACK & EVENT TRACKING

**What it does:** Collects user feedback (bugs, suggestions) and tracks frontend events for analytics.

**Endpoints:**
- `POST /api/feedback` — Submit feedback (type, data, metadata).
- `POST /api/events/track` — Track frontend event (button clicks, page views, feature usage).
- `POST /api/grading-analytics` — Log detailed grading analytics (AI vs teacher grade delta, cost, tokens, duration).

---

## 24. DEBUG & MAINTENANCE

**What it does:** Debug endpoints for development/troubleshooting.

**Endpoints:**
- `POST /api/exams/{exam_id}/force-reextract` — Force re-extraction of questions (clears cache).
- `GET /api/exams/{exam_id}/debug-questions` — View raw question data for debugging.
- `POST /api/debug/cleanup` — Clean up orphaned data.
- `GET /api/debug/status` — System status (DB connection, collections, counts).

---

## 25. HELPER FUNCTIONS (Shared)

These are used across multiple domains:

- `serialize_doc(doc)` — Converts MongoDB documents to JSON-safe dicts (handles ObjectId, nested docs).
- `get_llm_api_key()` — Returns Gemini API key from env.
- `get_version_info()` — Returns git commit, build time, environment.
- `infer_upsc_paper(exam_name, subject_name)` — Detects UPSC paper type from names.
- `validate_question_structure(questions)` — Validates question array (missing numbers, mark mismatches, duplicates).
- `exam_has_model_answer(exam_id)` — Checks if model answer exists.
- `get_paper_hash(...)` / `get_model_answer_hash(...)` — SHA256 hashing for cache keys.

---

## Summary: What Runs in Production

```
server.py (14,000 lines)
├── Imports from:
│   ├── file_utils.py        → PDF/ZIP/Drive file handling
│   ├── concurrency.py       → Semaphores for rate limiting
│   ├── annotation_utils.py  → Drawing marks on images
│   ├── vision_ocr_service.py → Google Cloud Vision text detection
│   ├── app/services/llm.py  → Gemini SDK wrapper (LlmChat, UserMessage, ImageContent)
│   └── auth_utils.py        → JWT/bcrypt password utilities
│
├── Starts background worker from:
│   └── task_worker.py       → MongoDB task queue processor
│
└── All 100+ endpoints defined inline
```

Everything else (`app/`, `main.py`, `app/services/`, `app/routes/`, `app/cache/`, `app/models/`) is the incomplete modular rewrite that is NOT running in production.
