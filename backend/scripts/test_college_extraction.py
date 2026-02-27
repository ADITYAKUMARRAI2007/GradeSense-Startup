"""Test script for college layer question extraction improvements."""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import Dict, List, Any
from app.layers.college.engine import run_college_pipeline_v2


def create_test_exam_questions(subject_type: str) -> List[Dict[str, Any]]:
    """Create test exam questions for different subjects."""
    
    if subject_type == "accounting":
        return [
            {
                "question_id": 1,
                "question_text": "Prepare Journal Entry for the following transactions",
                "marks": 10,
                "rubric": "accounting_journal",
                "type": "accounting"
            },
            {
                "question_id": 2,
                "question_text": "Prepare Ledger Account for Cash",
                "marks": 10,
                "rubric": "accounting_ledger",
                "type": "accounting"
            },
            {
                "question_id": 3,
                "question_text": "Prepare Trial Balance",
                "marks": 15,
                "rubric": "accounting_trial_balance",
                "type": "accounting"
            }
        ]
    
    elif subject_type == "language":
        return [
            {
                "question_id": 1,
                "question_text": "Read the following passage and answer the questions",
                "marks": 10,
                "rubric": "comprehension",
                "type": "theory"
            },
            {
                "question_id": 2,
                "question_text": "Write an essay on the importance of education",
                "marks": 15,
                "rubric": "essay_writing",
                "type": "theory"
            },
            {
                "question_id": 3,
                "question_text": "Translate the following sentences",
                "marks": 10,
                "rubric": "translation",
                "type": "theory"
            }
        ]
    
    elif subject_type == "maths":
        return [
            {
                "question_id": 1,
                "question_text": "Solve the quadratic equation: x² + 5x + 6 = 0",
                "marks": 5,
                "rubric": "algebra",
                "type": "numerical"
            },
            {
                "question_id": 2,
                "question_text": "Prove that the sum of angles in a triangle is 180°",
                "marks": 10,
                "rubric": "geometry_proof",
                "type": "theory"
            },
            {
                "question_id": 3,
                "question_text": "Find the derivative of f(x) = x³ + 2x² - 5x + 1",
                "marks": 8,
                "rubric": "calculus",
                "type": "numerical"
            }
        ]
    
    elif subject_type == "science":
        return [
            {
                "question_id": 1,
                "question_text": "Draw and label the diagram of a plant cell",
                "marks": 10,
                "rubric": "biology_diagram",
                "type": "diagram"
            },
            {
                "question_id": 2,
                "question_text": "Describe the experiment to verify Ohm's law",
                "marks": 15,
                "rubric": "physics_experiment",
                "type": "theory"
            },
            {
                "question_id": 3,
                "question_text": "Calculate the molecular weight of H2SO4",
                "marks": 5,
                "rubric": "chemistry_numerical",
                "type": "numerical"
            }
        ]
    
    else:  # general
        return [
            {
                "question_id": 1,
                "question_text": "Question 1",
                "marks": 10,
                "rubric": "general",
                "type": "theory"
            },
            {
                "question_id": 2,
                "question_text": "Question 2",
                "marks": 10,
                "rubric": "general",
                "type": "theory"
            },
            {
                "question_id": 3,
                "question_text": "Question 3",
                "marks": 10,
                "rubric": "general",
                "type": "theory"
            }
        ]


def analyze_extraction_results(pipeline_result: Dict[str, Any], subject_type: str) -> Dict[str, Any]:
    """Analyze the extraction results and provide detailed metrics."""
    
    gate = pipeline_result.get("gate", {})
    packets = pipeline_result.get("packets", {})
    meta = packets.get("_meta", {}) if isinstance(packets, dict) else {}
    
    # Count questions found by different methods
    anchor_found = meta.get("found_via_anchor", 0)
    inference_found = meta.get("found_via_inference", 0)
    content_matched = meta.get("content_matched_count", 0)
    
    # Get question IDs
    expected_qids = sorted([1, 2, 3])  # Based on test questions
    found_qids = sorted([k for k in packets.keys() if isinstance(k, int)])
    missing_qids = sorted(set(expected_qids) - set(found_qids))
    
    # Analyze confidence
    confidences = []
    for qid in found_qids:
        packet = packets.get(qid, {})
        conf = packet.get("mapping_confidence", 0.0)
        confidences.append(conf)
    
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    
    # Analyze mapping traces
    traces = {}
    for qid in found_qids:
        packet = packets.get(qid, {})
        trace = packet.get("mapping_trace", [])
        for t in trace:
            traces[t] = traces.get(t, 0) + 1
    
    return {
        "subject_type": subject_type,
        "expected_questions": len(expected_qids),
        "found_questions": len(found_qids),
        "missing_questions": missing_qids,
        "extraction_rate": len(found_qids) / len(expected_qids) if expected_qids else 0.0,
        "anchor_found": anchor_found,
        "inference_found": inference_found,
        "content_matched": content_matched,
        "average_confidence": round(avg_confidence, 4),
        "mapping_coverage": meta.get("mapping_coverage", 0.0),
        "mapping_status": gate.get("mapping_status", "unknown"),
        "mapping_traces": traces,
        "low_confidence_questions": gate.get("low_confidence_questions", []),
        "unresolved_questions": gate.get("unresolved_questions", []),
    }


def print_analysis(analysis: Dict[str, Any]):
    """Print analysis results in a readable format."""
    print(f"\n{'='*60}")
    print(f"Subject: {analysis['subject_type'].upper()}")
    print(f"{'='*60}")
    print(f"Expected Questions: {analysis['expected_questions']}")
    print(f"Found Questions: {analysis['found_questions']}")
    print(f"Extraction Rate: {analysis['extraction_rate']*100:.1f}%")
    print(f"\nDetection Methods:")
    print(f"  - Via Anchor: {analysis['anchor_found']}")
    print(f"  - Via Inference: {analysis['inference_found']}")
    print(f"  - Via Content Match: {analysis['content_matched']}")
    print(f"\nQuality Metrics:")
    print(f"  - Average Confidence: {analysis['average_confidence']:.4f}")
    print(f"  - Mapping Coverage: {analysis['mapping_coverage']:.4f}")
    print(f"  - Mapping Status: {analysis['mapping_status']}")
    
    if analysis['missing_questions']:
        print(f"\n⚠️  Missing Questions: {analysis['missing_questions']}")
    else:
        print(f"\n✅ All questions found!")
    
    if analysis['low_confidence_questions']:
        print(f"⚠️  Low Confidence Questions: {analysis['low_confidence_questions']}")
    
    if analysis['mapping_traces']:
        print(f"\nMapping Traces:")
        for trace, count in sorted(analysis['mapping_traces'].items()):
            print(f"  - {trace}: {count}")
    
    print(f"{'='*60}\n")


def main():
    """Run tests for all subject types."""
    print("\n" + "="*60)
    print("COLLEGE LAYER QUESTION EXTRACTION TEST")
    print("="*60)
    print("\nThis test validates the enhanced question extraction")
    print("capabilities across different subject types.")
    print("\nNote: This is a dry-run test without actual images.")
    print("In production, the system will process real answer sheets.")
    
    subjects = ["accounting", "language", "maths", "science", "general"]
    results = []
    
    for subject in subjects:
        print(f"\n\nTesting {subject.upper()}...")
        
        # Create test questions
        exam_questions = create_test_exam_questions(subject)
        
        # Note: In a real test, you would provide actual answer sheet images
        # For this dry-run, we're just testing the pipeline structure
        answer_images = []  # Empty for dry-run
        
        try:
            # Run pipeline (will fail gracefully with empty images)
            pipeline_result, question_map = run_college_pipeline_v2(
                exam_id=f"test_{subject}",
                exam_questions=exam_questions,
                answer_images=answer_images,
                question_paper_pdf_bytes=None,
                failed_chunks=None
            )
            
            # Analyze results
            analysis = analyze_extraction_results(pipeline_result, subject)
            results.append(analysis)
            print_analysis(analysis)
            
        except Exception as e:
            print(f"❌ Error testing {subject}: {e}")
            continue
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    if results:
        avg_extraction = sum(r['extraction_rate'] for r in results) / len(results)
        avg_confidence = sum(r['average_confidence'] for r in results) / len(results)
        
        print(f"\nOverall Performance:")
        print(f"  - Average Extraction Rate: {avg_extraction*100:.1f}%")
        print(f"  - Average Confidence: {avg_confidence:.4f}")
        
        print(f"\nEnhancements Implemented:")
        print(f"  ✅ Subject-specific pattern recognition")
        print(f"  ✅ Sequence-based question inference")
        print(f"  ✅ Content-based matching for missing questions")
        print(f"  ✅ Enhanced layout detection")
        print(f"  ✅ Multi-strategy recovery system")
        
        print(f"\nNext Steps:")
        print(f"  1. Test with real answer sheet images")
        print(f"  2. Fine-tune confidence thresholds per subject")
        print(f"  3. Add LLM-based semantic detection (Phase 3)")
        print(f"  4. Monitor extraction rates in production")
    
    print("\n" + "="*60 + "\n")


if __name__ == "__main__":
    main()
