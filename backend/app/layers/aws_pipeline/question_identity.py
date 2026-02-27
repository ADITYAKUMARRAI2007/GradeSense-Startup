"""Deterministic question UUID generation for stable identity."""

from __future__ import annotations

import hashlib
import uuid


def generate_question_uuid(anchor_text: str, page: int, preview_text: str) -> str:
    """Generate a deterministic UUID based on anchor text, page, and preview text."""
    seed = f"{anchor_text}|{page}|{preview_text[:200]}"
    namespace = uuid.UUID("12345678-1234-5678-1234-567812345678")
    return str(uuid.uuid5(namespace, seed))


def stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

