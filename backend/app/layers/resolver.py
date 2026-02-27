"""Resolve grading layer context for UPSC vs college."""

from dataclasses import dataclass
from typing import Optional

from app.config import UNIVERSAL_PIPELINE_ENABLED, UNIVERSAL_PIPELINE_EXAM_TYPES
from app.layers.college import COLLEGE_SYSTEM_PROMPT
from app.layers.upsc.prompts import get_upsc_system_prompt
from app.utils.validation import infer_upsc_paper


@dataclass(frozen=True)
class GradingLayerContext:
    layer: str
    is_upsc: bool
    upsc_paper: Optional[str]
    base_prompt: str
    default_grading_mode: str


def resolve_grading_layer(
    exam_type: Optional[str],
    exam_name: Optional[str],
    subject_name: Optional[str],
) -> GradingLayerContext:
    """
    Resolve whether grading should use UPSC or college layer.
    Explicit exam_type takes precedence over inference.
    """
    exam_type_norm = str(exam_type or "").lower()
    upsc_paper = None
    is_upsc = False
    layer = "college"
    is_universal = bool(
        UNIVERSAL_PIPELINE_ENABLED
        and exam_type_norm
        and exam_type_norm in set(UNIVERSAL_PIPELINE_EXAM_TYPES)
        and exam_type_norm != "upsc"
    )

    if is_universal:
        layer = "universal"
        is_upsc = False
    elif exam_type_norm == "upsc":
        is_upsc = True
    elif exam_type_norm == "college":
        is_upsc = False
    else:
        upsc_paper = infer_upsc_paper(exam_name, subject_name)
        if upsc_paper:
            is_upsc = True
        if subject_name and "upsc" in subject_name.lower():
            is_upsc = True
        if exam_name and "upsc" in exam_name.lower():
            is_upsc = True

    base_prompt = get_upsc_system_prompt(upsc_paper) if is_upsc else COLLEGE_SYSTEM_PROMPT
    default_grading_mode = "strict" if is_upsc else "balanced"

    if is_upsc:
        layer = "upsc"
    elif layer != "universal":
        layer = "college"

    return GradingLayerContext(
        layer=layer,
        is_upsc=is_upsc,
        upsc_paper=upsc_paper,
        base_prompt=base_prompt,
        default_grading_mode=default_grading_mode,
    )
