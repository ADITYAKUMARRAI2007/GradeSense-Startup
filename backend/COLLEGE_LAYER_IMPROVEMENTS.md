# College Layer Question Extraction Improvements

## Overview

This document describes the comprehensive improvements made to the college layer question extraction system to handle diverse subjects including accounting, language, mathematics, and science.

## Problem Statement

The original college layer had several critical issues:

1. **Overly Strict Anchor Detection**: Relied exclusively on question number patterns (Q1, Q2, etc.)
2. **Limited Pattern Recognition**: Only recognized basic question formats
3. **No Subject Awareness**: Treated all subjects identically
4. **Poor Layout Handling**: Struggled with tables, diagrams, and multi-column layouts
5. **No Semantic Understanding**: Purely pattern-based with no content analysis
6. **Blueprint Dependency**: Required perfect question paper extraction

### Impact by Subject

- **Accounting**: T-accounts and ledger formats without question numbers were missed
- **Language**: Passages and essay questions with non-standard formats failed
- **Mathematics**: Equations broke OCR, multi-step problems had unclear boundaries
- **Science**: Diagrams treated as separate blocks, experiment formats not recognized

## Implemented Solutions

### Phase 1: High Impact Quick Wins ✅

#### 1. Subject-Specific Pattern Recognition

**File**: `backend/app/layers/college/region_ocr.py`

Added comprehensive pattern detection for different subjects:

```python
# Accounting patterns
ACCOUNTING_MARKERS = re.compile(
    r"\b(?:journal\s+entry|ledger\s+account|trial\s+balance|particulars|"
    r"balance\s+sheet|profit\s+and\s+loss|trading\s+account|"
    r"cash\s+book|bank\s+reconciliation)\b",
    re.IGNORECASE
)

# Language patterns
LANGUAGE_MARKERS = re.compile(
    r"\b(?:passage|comprehension|essay|letter\s+to|translate|grammar|"
    r"read\s+the\s+following|write\s+a|compose)\b",
    re.IGNORECASE
)

# Mathematics patterns
MATHS_MARKERS = re.compile(
    r"\b(?:solve|prove\s+that|calculate|find\s+the|show\s+that|verify|"
    r"evaluate|simplify|factorize|integrate|differentiate)\b",
    re.IGNORECASE
)

# Science patterns
SCIENCE_MARKERS = re.compile(
    r"\b(?:diagram|experiment|observation|aim|apparatus|procedure|"
    r"conclusion|label|draw|identify|describe\s+the)\b",
    re.IGNORECASE
)
```

**Benefits**:
- Detects questions even without explicit numbering
- Subject-aware content classification
- Better handling of domain-specific terminology

#### 2. Sequence-Based Question Inference

**File**: `backend/app/layers/college/packet_builder.py`

Implemented intelligent question inference:

```python
def _infer_missing_questions(valid_qids, found_qids, regions):
    """
    If Q1 and Q3 are found, infer Q2 is between them.
    Uses spatial positioning and content markers.
    """
```

**How it works**:
1. Identifies gaps in question sequence (e.g., found Q1 and Q3, missing Q2)
2. Analyzes regions between found questions
3. Looks for question-like content using subject markers
4. Creates packets for inferred questions

**Benefits**:
- Recovers questions missed by anchor detection
- Uses spatial context for better accuracy
- Reduces dependency on perfect OCR

#### 3. Content-Based Question Matching

**File**: `backend/app/layers/college/recovery.py`

Added content similarity matching:

```python
def recover_missing_by_content_matching(question_blueprint, packets, regions, missing_qids):
    """
    Match missing questions to unassigned regions by content similarity.
    Uses word-based similarity with subject-specific boosting.
    """
```

**How it works**:
1. Compares blueprint question text with unassigned regions
2. Calculates word-based similarity scores
3. Boosts scores for regions with subject-specific markers
4. Matches questions above similarity threshold (>0.15)

**Benefits**:
- Recovers questions without clear anchors
- Works even with OCR errors (fuzzy matching)
- Subject-aware scoring improves accuracy

### Phase 2: Medium Impact Enhancements ✅

#### 4. Enhanced Layout Detection

**File**: `backend/app/layers/college/layout.py`

Added layout type detection and adaptive processing:

```python
def _detect_layout_type(binary_inv, blocks):
    """
    Detects: single_column, multi_column, table_heavy, diagram_heavy
    """

def _merge_related_blocks(blocks, layout_type):
    """
    Merges blocks that belong together based on layout type.
    Accounting: merges ledger entries
    Language: merges passage + questions
    """
```

**Layout Types**:
- **single_column**: Standard text layout
- **multi_column**: Language papers with side-by-side content
- **table_heavy**: Accounting papers with ledgers/journals
- **diagram_heavy**: Science/math papers with large diagrams

**Benefits**:
- Better handling of complex layouts
- Reduces fragmentation of related content
- Improves accounting ledger detection

#### 5. Enhanced Region Metadata

**File**: `backend/app/layers/college/region_ocr.py`

Each OCR region now includes:

```python
{
    "is_accounting_entry": bool,      # Detected To/By format
    "is_question_content": bool,      # Question-like text
    "has_accounting_marker": bool,    # Contains accounting terms
    "has_language_marker": bool,      # Contains language terms
    "has_maths_marker": bool,         # Contains math terms
    "has_science_marker": bool,       # Contains science terms
}
```

**Benefits**:
- Rich metadata for downstream processing
- Enables subject-aware packet building
- Improves recovery strategies

#### 6. Multi-Strategy Recovery System

**File**: `backend/app/layers/college/recovery.py`

Implemented layered recovery approach:

```python
def run_recovery(question_blueprint, packets, aligned_answers, region_text, packet_conf_min):
    """
    Strategy 1: Expand low-confidence packets (boundary expansion)
    Strategy 2: Content-based matching for missing questions
    Strategy 3: Re-align and recompute confidence
    """
```

**Recovery Strategies**:
1. **Boundary Expansion**: Extends low-confidence packets to next anchor
2. **Content Matching**: Matches missing questions by text similarity
3. **Confidence Recomputation**: Updates scores after recovery

**Benefits**:
- Multiple fallback mechanisms
- Higher question recovery rate
- Better handling of edge cases

## Performance Improvements

### Expected Outcomes

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Anchor Detection Rate | 60-70% | 70-80% | +10-20% |
| Overall Extraction Rate | 70-80% | 85-95% | +15-20% |
| Accounting Questions | 50-60% | 80-90% | +30-40% |
| Language Questions | 60-70% | 85-95% | +25% |
| Math Questions | 70-80% | 85-95% | +15% |
| Science Questions | 65-75% | 85-95% | +20% |

### Key Metrics Tracked

1. **found_via_anchor**: Questions detected by traditional anchor patterns
2. **found_via_inference**: Questions inferred by sequence analysis
3. **content_matched_count**: Questions recovered by content matching
4. **mapping_coverage**: Percentage of page regions assigned to questions
5. **average_confidence**: Average confidence across all packets

## Testing

### Test Script

Run the comprehensive test suite:

```bash
cd backend
python scripts/test_college_extraction.py
```

This tests extraction across all subject types and provides detailed metrics.

### Manual Testing

To test with real answer sheets:

```python
from app.layers.college.engine import run_college_pipeline_v2

# Prepare your data
exam_questions = [...]  # Your question blueprint
answer_images = [...]   # Base64 encoded images

# Run pipeline
pipeline_result, question_map = run_college_pipeline_v2(
    exam_id="test_exam",
    exam_questions=exam_questions,
    answer_images=answer_images
)

# Check results
gate = pipeline_result["gate"]
print(f"Status: {gate['mapping_status']}")
print(f"Found: {gate['mapped_question_ratio']*100:.1f}%")
print(f"Missing: {gate['unresolved_questions']}")
```

## Configuration

### Environment Variables

```bash
# Confidence thresholds
COLLEGE_V2_PACKET_CONF_MIN=0.60          # Minimum packet confidence
COLLEGE_V2_BLUEPRINT_HEALTH_THRESHOLD=0.92  # Blueprint completeness

# Recovery settings
MAPPED_QUESTION_RATIO_MIN=0.85           # Minimum mapped ratio
MAPPING_COVERAGE_GATE_MIN=0.75           # Minimum coverage
UNRESOLVED_RATIO_MAX=0.10                # Maximum unresolved ratio
```

### Tuning Recommendations

**For Accounting Papers**:
- Lower `COLLEGE_V2_PACKET_CONF_MIN` to 0.50 (ledgers have lower OCR confidence)
- Increase table detection sensitivity

**For Language Papers**:
- Increase `MAPPING_COVERAGE_GATE_MIN` to 0.80 (more text content)
- Enable multi-column layout detection

**For Math/Science Papers**:
- Keep default settings
- Monitor diagram detection accuracy

## Future Enhancements (Phase 3)

### 1. LLM-Based Semantic Detection

Add Gemini-based question boundary detection as final fallback:

```python
def detect_questions_with_llm(page_text, subject_type):
    """
    Use Gemini to identify question boundaries when patterns fail.
    Provides semantic understanding of question structure.
    """
```

**Benefits**:
- Handles completely non-standard formats
- Understands context and intent
- Works across all subjects

### 2. Subject Type Auto-Detection

Automatically detect subject from exam metadata and content:

```python
def detect_subject_type(exam_questions, exam_metadata):
    """
    Analyze question patterns, keywords, and metadata.
    Return: accounting, language, maths, science, general
    """
```

**Benefits**:
- No manual configuration needed
- Automatic optimization per subject
- Better handling of mixed-subject exams

### 3. Adaptive Confidence Thresholds

Learn optimal thresholds per subject and teacher:

```python
def get_adaptive_thresholds(subject_type, teacher_id, historical_data):
    """
    Analyze past grading results to optimize thresholds.
    Adapts to teacher preferences and subject characteristics.
    """
```

**Benefits**:
- Personalized to each teacher
- Improves over time with usage
- Reduces false positives/negatives

## Monitoring and Debugging

### Key Metrics to Monitor

1. **Extraction Rate by Subject**: Track success rate per subject type
2. **Recovery Strategy Usage**: Which strategies are most effective
3. **Confidence Distribution**: Are packets meeting quality thresholds
4. **Missing Question Patterns**: Common reasons for failures

### Debug Endpoints

```python
# Get detailed extraction diagnostics
GET /api/exams/{exam_id}/extraction-diagnostics

# View recovery attempts
GET /api/submissions/{submission_id}/recovery-trace

# Analyze failed extractions
GET /api/analytics/extraction-failures
```

### Logging

Enhanced logging for debugging:

```python
logger.info("[COLLEGE-V2] Found via anchor: %d", anchor_count)
logger.info("[COLLEGE-V2] Found via inference: %d", inference_count)
logger.info("[COLLEGE-V2] Content matched: %d", content_matched)
logger.warning("[COLLEGE-V2] Missing questions: %s", missing_qids)
```

## Migration Guide

### For Existing Deployments

1. **Backup Current Data**: Export existing submissions and results
2. **Update Code**: Pull latest changes to college layer
3. **Test on Sample Data**: Run test script with representative papers
4. **Gradual Rollout**: Enable for new exams first
5. **Monitor Metrics**: Track extraction rates and quality
6. **Adjust Thresholds**: Fine-tune based on results

### Backward Compatibility

All changes are backward compatible:
- Existing packet structure unchanged
- New fields are optional additions
- Old submissions continue to work
- No database migrations required

## Troubleshooting

### Low Extraction Rate

**Symptoms**: Many questions marked as "unresolved"

**Solutions**:
1. Check OCR quality (low confidence regions)
2. Verify blueprint completeness
3. Lower confidence thresholds
4. Enable more aggressive recovery

### False Positives

**Symptoms**: Wrong content assigned to questions

**Solutions**:
1. Increase confidence thresholds
2. Tighten content similarity requirements
3. Improve anchor detection patterns
4. Review layout detection accuracy

### Subject-Specific Issues

**Accounting**: Enable secondary table detector, lower confidence threshold
**Language**: Enable multi-column detection, increase coverage requirement
**Math**: Improve equation OCR, handle special symbols
**Science**: Better diagram detection, merge diagram + labels

## Support

For issues or questions:
1. Check logs for detailed error messages
2. Run test script to validate setup
3. Review extraction diagnostics endpoint
4. Contact development team with specific examples

## Changelog

### Version 2.0 (Current)

- ✅ Subject-specific pattern recognition
- ✅ Sequence-based question inference
- ✅ Content-based matching recovery
- ✅ Enhanced layout detection
- ✅ Multi-strategy recovery system
- ✅ Comprehensive test suite

### Version 1.0 (Original)

- Basic anchor-only detection
- Single recovery strategy
- No subject awareness
- Limited layout handling

## References

- Original Implementation: `backend/app/layers/college/`
- Test Suite: `backend/scripts/test_college_extraction.py`
- Documentation: `backend/EXPLANATION.md`
- API Reference: `backend/README.md`
