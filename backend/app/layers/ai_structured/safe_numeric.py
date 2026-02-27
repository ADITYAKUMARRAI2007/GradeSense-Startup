"""Safe numeric parsing helpers for extraction/marking pipelines."""

from __future__ import annotations

import math
import re
from typing import Any, Optional, Tuple


_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$")
_SECTION_MATH_RE = re.compile(
    r"(?<!\d)(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+(?:\.\d+)?)\s*=\s*(\d+(?:\.\d+)?)(?!\d)",
    flags=re.IGNORECASE,
)


def safe_int(value: Any, default: int = 0) -> int:
    """Parse strict integer values only; rejects partial/embedded numbers."""
    try:
        if value is None:
            return int(default)
        if isinstance(value, bool):
            return int(default)
        if isinstance(value, int):
            return int(value)
        if isinstance(value, float):
            if not math.isfinite(value):
                return int(default)
            rounded = int(round(value))
            if abs(value - rounded) > 1e-9:
                return int(default)
            return rounded
        text = str(value).strip()
        if not _INT_RE.fullmatch(text):
            return int(default)
        return int(text)
    except Exception:
        return int(default)


def safe_float(value: Any, default: float = 0.0) -> float:
    """Parse strict float values only; rejects partial/embedded numbers."""
    try:
        if value is None:
            return float(default)
        if isinstance(value, bool):
            return float(default)
        if isinstance(value, (int, float)):
            f = float(value)
            if not math.isfinite(f):
                return float(default)
            return f
        text = str(value).strip()
        if not _FLOAT_RE.fullmatch(text):
            return float(default)
        f = float(text)
        if not math.isfinite(f):
            return float(default)
        return f
    except Exception:
        return float(default)


def parse_section_math_expression(expr: Any) -> Optional[Tuple[int, float, float]]:
    """Parse expressions like 12x1=12 or 7 × 2 = 14."""
    text = str(expr or "").strip()
    if not text:
        return None
    match = _SECTION_MATH_RE.search(text)
    if not match:
        return None
    count = safe_int(match.group(1), 0)
    each = safe_float(match.group(2), 0.0)
    total = safe_float(match.group(3), 0.0)
    if count <= 0 or each <= 0.0 or total <= 0.0:
        return None
    if abs((count * each) - total) > max(1.0, 0.15 * max(total, 1.0)):
        return None
    return count, round(each, 4), round(total, 4)


__all__ = ["safe_int", "safe_float", "parse_section_math_expression"]
