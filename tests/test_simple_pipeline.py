import io
import json

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

from app.services.simple_pipeline import run_simple_pipeline


def _make_pdf(lines):
    """Utility to generate an in-memory PDF containing the given lines."""
    buf = io.BytesIO()
    p = canvas.Canvas(buf, pagesize=letter)
    y = 750
    for ln in lines:
        p.drawString(100, y, ln)
        y -= 20
    p.showPage()
    p.save()
    return buf.getvalue()


def test_simple_mcq_correct():
    qp = _make_pdf(["Q1. Choose the correct option: A) one  B) two"])
    ans = _make_pdf(["A"])
    meta = {"1": {"type": "mcq", "correct_option": "A", "marks": 1}}
    results = run_simple_pipeline(qp, ans, question_meta=meta)
    assert len(results) == 1
    r = results[0]
    assert r["score"] == 1
    assert r["feedback"] == "Correct"


def test_simple_endpoint():
    # verify the FastAPI route returns the same result
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    qp = _make_pdf(["Q1. Pick A or B"])
    ans = _make_pdf(["A"])
    meta = json.dumps({"1": {"type": "mcq", "correct_option": "A", "marks": 2}})

    files = {
        "question_paper": ("q.pdf", qp, "application/pdf"),
        "answer_sheet": ("a.pdf", ans, "application/pdf"),
    }
    data = {"question_meta": meta}
    response = client.post("/api/simple/grade", files=files, data=data)
    assert response.status_code == 200
    out = response.json()
    assert out.get("question_results")
    assert out["question_results"][0]["score"] == 2


def test_simple_descriptive():
    qp = _make_pdf(["Q1. Explain gravity."])
    ans = _make_pdf(["Gravity is a force that attracts."])
    meta = {"1": {"type": "descriptive", "marks": 5}}
    results = run_simple_pipeline(qp, ans, question_meta=meta)
    assert len(results) == 1
    r = results[0]
    assert r["score"] == 5
    assert "Answer received" in r["feedback"]
