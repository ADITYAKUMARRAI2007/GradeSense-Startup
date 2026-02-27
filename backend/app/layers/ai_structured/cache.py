"""Simple in-memory cache for ai_structured stage artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass
class CacheEntry:
    key: Tuple[str, int, str]
    payload: Dict[str, Any]


_structure_cache: Dict[Tuple[str, int, str], CacheEntry] = {}
_alignment_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}


def get_structure_cache(exam_id: str, blueprint_version: int, extraction_hash: str) -> Optional[Dict[str, Any]]:
    entry = _structure_cache.get((exam_id, int(blueprint_version), extraction_hash))
    return entry.payload if entry else None


def set_structure_cache(exam_id: str, blueprint_version: int, extraction_hash: str, payload: Dict[str, Any]) -> None:
    key = (exam_id, int(blueprint_version), extraction_hash)
    _structure_cache[key] = CacheEntry(key=key, payload=payload)


def get_alignment_cache(submission_id: str, blueprint_signature: str) -> Optional[Dict[str, Any]]:
    return _alignment_cache.get((submission_id, blueprint_signature))


def set_alignment_cache(submission_id: str, blueprint_signature: str, payload: Dict[str, Any]) -> None:
    _alignment_cache[(submission_id, blueprint_signature)] = payload

