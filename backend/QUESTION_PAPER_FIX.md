# Question Paper Extraction Fix

## The Real Issue

You were uploading a **QUESTION PAPER** (the exam questions themselves), not an **ANSWER SHEET** (student's written answers).

The system has TWO different pipelines:
1. **Question Paper Extraction** - Extracts question structure from the exam paper
2. **Answer Sheet Grading** (College Layer) - Grades student answers

## What Was Happening

From the logs:
```
[EXTRACT-ANCHOR] candidates=59 scored=12 kept=12 low_score_reject=37
[EXTRACT-SPAN] Built 8 question spans from 12 anchors
```

- Found 59 potential question markers
- Only 12 scored high enough (threshold was 3)
- 37 were rejected due to low scores
- The 12 anchors resulted in 8 question spans (some questions are multi-part)

## Root Cause

The question paper extraction scoring system was TOO STRICT:

### Scoring System
- Left margin position: +2 points
- Isolated question prefix (e.g., "Q1." alone on line): +2 points
- Sequence penalties (out of order): -1 to -2 points
- Subpart pattern (like "a)", "i)"): -3 points
- Inside table: -3 points
- Inline sentence or small font: -2 points
- Has marks pattern (like "[5 marks]"): -2 points

### The Problem
**Minimum score required: 3 points**

To get 3 points, a question needed:
- Be in left margin (+2) AND
- Be isolated on its own line (+2) AND
- Have NO penalties

This rejected many valid questions that:
- Had marks annotations
- Were in tables
- Had slightly different formatting
- Appeared after section headers

## Fix Applied

**File**: `backend/app/services/extraction.py`

Lowered the scoring threshold:
```python
# Before:
if int(score) >= 3:
    scored_candidates.append(cand)

# After:
min_score = 0 if section_boundary_detected else 1
if int(score) >= min_score:
    scored_candidates.append(cand)
```

Now:
- Questions near section boundaries: score >= 0 (very lenient)
- Other questions: score >= 1 (more lenient than 3)

This will catch more valid questions while still filtering out obvious false positives.

## Expected Results

After this fix, when you re-upload the question paper:
- More of the 59 candidates will pass scoring
- Should extract closer to the actual number of questions
- Section-based questions will be handled better

## How to Test

1. **Re-extract questions** from the same exam:
   - Go to the exam in the frontend
   - Click "Re-extract Questions" or re-upload the question paper
   
2. **Watch the logs** for:
   ```
   [EXTRACT-ANCHOR] candidates=X scored=Y kept=Y low_score_reject=Z
   ```
   - `scored` should be higher than 12
   - `low_score_reject` should be lower than 37

3. **Check the result**:
   - Should see more than 8 questions extracted
   - Questions should match the actual exam structure

## Important Distinction

### Question Paper Extraction (What you're doing)
- Upload: The exam question paper PDF
- Purpose: Extract question structure, marks, topics
- Pipeline: Universal extraction service
- Output: Question blueprint for the exam

### Answer Sheet Grading (What I fixed earlier)
- Upload: Student's written answer sheets
- Purpose: Grade student answers against rubric
- Pipeline: College layer with subject-specific detection
- Output: Scores and feedback for each question

The college layer improvements I made earlier are for **answer sheet grading**, not question paper extraction.

## Next Steps

1. Backend has auto-reloaded with the fix
2. Go to your exam in the frontend
3. Re-upload the question paper or click "Re-extract Questions"
4. Should see more questions extracted

## If Still Not Enough Questions

If you're still not getting all questions, we can:

1. **Lower the threshold even more**:
   ```python
   min_score = -1  # Allow some penalties
   ```

2. **Adjust specific penalties**:
   - Reduce marks pattern penalty (currently -2)
   - Reduce table penalty (currently -3)
   - Reduce inline sentence penalty (currently -2)

3. **Check the question paper format**:
   - Are questions clearly numbered?
   - Are they in a consistent format?
   - Are there section headers?

Let me know how many questions should actually be in the paper, and I can tune the extraction further.
