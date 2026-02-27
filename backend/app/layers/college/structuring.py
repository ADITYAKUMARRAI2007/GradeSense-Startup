"""Phase 7: accounting-aware answer structuring for college V2 pipeline."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


TO_ACCOUNT_RE = re.compile(r"^\s*to\s+(.+?)(?:a\/?c|account)\b", re.IGNORECASE)
BY_ACCOUNT_RE = re.compile(r"^\s*by\s+(.+?)(?:a\/?c|account)\b", re.IGNORECASE)
AMOUNT_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*$")
FORMULA_RE = re.compile(r"[=+\-*/]")
WORKING_NOTE_RE = re.compile(r"\b(?:working\s*note|wn|note|calculation|working)\b", re.IGNORECASE)
DR_CR_RE = re.compile(r"\b(?:dr\.?|cr\.?|debit|credit)\b", re.IGNORECASE)


def _extract_lines(packet: Optional[Dict[str, Any]]) -> List[str]:
    if not packet:
        return []
    lines: List[str] = []
    for blk in packet.get("text_blocks", []) or []:
        text = str(blk.get("text", "") or "").strip()
        if not text:
            continue
        for ln in text.splitlines():
            ln = ln.strip()
            if ln:
                lines.append(ln)
    return lines


def structure_packet(packet: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not packet:
        return {
            "journal_entries": [],
            "ledger_accounts": [],
            "dr_cr_columns": [],
            "totals": [],
            "working_formulas": [],
            "reasoning_steps": [],
            "raw_line_count": 0,
        }

    lines = _extract_lines(packet)
    accounts = set()
    journal_entries: List[Dict[str, Any]] = []
    dr_cr_columns: List[str] = []
    totals: List[Dict[str, Any]] = []
    formulas: List[str] = []
    reasoning: List[str] = []

    for line in lines:
        m_to = TO_ACCOUNT_RE.match(line)
        m_by = BY_ACCOUNT_RE.match(line)
        side = None
        account = None
        if m_to:
            side = "Dr"
            account = m_to.group(1).strip()
        elif m_by:
            side = "Cr"
            account = m_by.group(1).strip()

        if account:
            accounts.add(account)
            amt = AMOUNT_RE.search(line)
            journal_entries.append(
                {
                    "side": side,
                    "account": account,
                    "amount": (amt.group(1).replace(",", "") if amt else None),
                    "line": line,
                }
            )

        if DR_CR_RE.search(line):
            dr_cr_columns.append(line)

        lower = line.lower()
        if "total" in lower or "balance c/d" in lower or "balance b/d" in lower:
            amt_m = AMOUNT_RE.search(line)
            totals.append(
                {
                    "line": line,
                    "amount": (amt_m.group(1).replace(",", "") if amt_m else None),
                }
            )

        if FORMULA_RE.search(line) and any(ch.isdigit() for ch in line):
            formulas.append(line)

        if WORKING_NOTE_RE.search(line):
            reasoning.append(line)

    return {
        "journal_entries": journal_entries,
        "ledger_accounts": sorted(accounts),
        "dr_cr_columns": dr_cr_columns,
        "totals": totals,
        "working_formulas": formulas,
        "reasoning_steps": reasoning,
        "raw_line_count": len(lines),
    }


def structure_aligned_answers(aligned_answers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in aligned_answers or []:
        packet = row.get("packet")
        structured = structure_packet(packet)
        out.append(
            {
                "question_id": int(row.get("question_id") or 0),
                "packet_id": row.get("packet_id"),
                "aligned_by": row.get("aligned_by", "missing"),
                "alignment_confidence": float(row.get("alignment_confidence", 0.0) or 0.0),
                "structured_answer": structured,
                "packet_pages": (packet or {}).get("pages", []),
                "packet_trace": (packet or {}).get("mapping_trace", []),
            }
        )
    return out


__all__ = ["structure_packet", "structure_aligned_answers"]
