"""Phase 7 structured answer extraction for universal pipeline."""

from __future__ import annotations

import re
from typing import Any, Dict, List

DRCR_RE = re.compile(r"\b(?:dr\.?|cr\.?)\b", re.IGNORECASE)


def _extract_structured(packet: Dict[str, Any], q_type: str) -> Dict[str, Any]:
    text = str(packet.get("combined_text") or "")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    tables = packet.get("table_segments", []) or []

    out: Dict[str, Any] = {
        "raw_text": text,
        "table_segments": tables,
        "reasoning_steps": lines[:12],
        "working_formulas": [ln for ln in lines if any(ch in ln for ch in ["=", "+", "-", "*", "/"])][:20],
    }

    if q_type in ("table/numerical", "numerical"):
        out["journal_entries"] = [ln for ln in lines if DRCR_RE.search(ln)][:20]
        out["ledger_accounts"] = [ln for ln in lines if "account" in ln.lower()][:20]
        out["totals"] = [ln for ln in lines if "total" in ln.lower() or "balance" in ln.lower()][:10]

    if q_type in ("descriptive", "short"):
        out["essay_structure"] = {
            "intro": lines[:2],
            "body": lines[2:-2] if len(lines) > 4 else lines[2:],
            "conclusion": lines[-2:] if len(lines) > 2 else [],
        }

    return out


def structure_answers(question_blueprint: List[Dict[str, Any]], aligned: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_q = {int(a.get("question_id") or 0): a for a in (aligned or [])}
    out: List[Dict[str, Any]] = []
    for q in (question_blueprint or []):
        qid = int(q.get("question_id") or 0)
        row = by_q.get(qid) or {}
        packet = row.get("packet") or {}
        if not packet:
            out.append({"question_id": qid, "structured_answer": {}, "aligned_by": "missing", "packet": None})
            continue
        out.append(
            {
                "question_id": qid,
                "structured_answer": _extract_structured(packet, str(q.get("type") or "descriptive")),
                "aligned_by": row.get("aligned_by"),
                "packet": packet,
            }
        )
    return out


__all__ = ["structure_answers"]
