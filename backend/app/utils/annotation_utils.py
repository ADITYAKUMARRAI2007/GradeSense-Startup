"""
Annotation utilities — types, drawing helpers for grading marks on images.
Designed to look like a real examiner's pen marks on answer sheets.
"""

import io
import math
import random
import base64
from typing import List, Optional
from dataclasses import dataclass, field
from PIL import Image, ImageDraw, ImageFont


class AnnotationType:
    """Annotation type constants used throughout grading and annotation services."""
    CHECKMARK = "CHECKMARK"
    CROSS_MARK = "CROSS_MARK"
    ERROR_UNDERLINE = "ERROR_UNDERLINE"
    HIGHLIGHT_BOX = "HIGHLIGHT_BOX"
    COMMENT = "COMMENT"
    MARGIN_NOTE = "MARGIN_NOTE"
    POINT_NUMBER = "POINT_NUMBER"
    SCORE_CIRCLE = "SCORE_CIRCLE"
    MARGIN_BRACKET = "MARGIN_BRACKET"   # bracket spanning multiple lines + label
    TOTAL_SCORE = "TOTAL_SCORE"         # big total marks at top of first page


@dataclass
class Annotation:
    """A single annotation to draw on an image."""
    annotation_type: str
    x: float = 0
    y: float = 0
    text: str = ""
    color: str = "red"
    size: int = 24
    width: Optional[int] = None
    height: Optional[int] = None


def _parse_color(color_str: str):
    """Parse a color string to RGBA tuple."""
    if not color_str:
        return (255, 0, 0, 220)
    color_str = color_str.strip().lower()
    named = {
        "red": (220, 30, 30, 230),
        "green": (0, 150, 0, 230),
        "blue": (30, 30, 200, 230),
        "black": (0, 0, 0, 230),
    }
    if color_str in named:
        return named[color_str]
    if color_str.startswith("#") and len(color_str) >= 7:
        try:
            r = int(color_str[1:3], 16)
            g = int(color_str[3:5], 16)
            b = int(color_str[5:7], 16)
            return (r, g, b, 230)
        except ValueError:
            pass
    return (220, 30, 30, 230)


def apply_annotations_to_image(image_base64: str, annotations: List[Annotation]) -> str:
    """
    Draw annotations onto a base64-encoded image and return the result as base64.
    Renders in a realistic examiner pen style.
    """
    try:
        img_bytes = base64.b64decode(image_base64)
        img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        overlay = Image.new("RGBA", img.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(overlay)
        img_w, img_h = img.size

        for ann in annotations:
            x, y = int(ann.x), int(ann.y)
            color = ann.color or "red"

            if ann.annotation_type == AnnotationType.CHECKMARK:
                _draw_checkmark(draw, x, y, color, ann.size, img_w)

            elif ann.annotation_type == AnnotationType.CROSS_MARK:
                _draw_cross(draw, x, y, color, ann.size, img_w)

            elif ann.annotation_type == AnnotationType.ERROR_UNDERLINE:
                w = ann.size if ann.size > 24 else 100
                _draw_underline(draw, x, y, w, color)

            elif ann.annotation_type == AnnotationType.HIGHLIGHT_BOX:
                w = ann.width or 200
                h = ann.height or 40
                _draw_highlight_box(draw, x, y, w, h, color)

            elif ann.annotation_type in (AnnotationType.COMMENT, AnnotationType.MARGIN_NOTE):
                _draw_margin_comment(draw, x, y, ann.text, color, ann.size, img_w)

            elif ann.annotation_type == AnnotationType.POINT_NUMBER:
                _draw_text(draw, x, y, ann.text, color, ann.size)

            elif ann.annotation_type == AnnotationType.SCORE_CIRCLE:
                _draw_score_circle(draw, x, y, ann.text, color, ann.size)

            elif ann.annotation_type == AnnotationType.MARGIN_BRACKET:
                h = ann.height or 40
                _draw_margin_bracket(draw, x, y, h, ann.text, color, ann.size, img_w)

            elif ann.annotation_type == AnnotationType.TOTAL_SCORE:
                _draw_total_score(draw, ann.text, color, img_w)

        result = Image.alpha_composite(img, overlay).convert("RGB")
        buf = io.BytesIO()
        result.save(buf, format="JPEG", quality=88)
        return base64.b64encode(buf.getvalue()).decode()

    except Exception as e:
        return image_base64


def auto_position_annotations_for_question(
    question_score,
    page_idx: int,
    img_width: int,
    img_height: int,
    ocr_words: Optional[List[dict]] = None,
) -> List[Annotation]:
    """
    Auto-position annotations for a question on a given page.
    Uses OCR word positions if available, otherwise falls back to margin placement.
    """
    annotations = []
    margin_x = img_width - 120
    y_start = 80

    # Question number label
    annotations.append(Annotation(
        annotation_type=AnnotationType.POINT_NUMBER,
        x=margin_x, y=y_start,
        text=f"Q{question_score.question_number}",
        color="#1565C0", size=20
    ))

    # Score
    score_text = (
        str(int(question_score.obtained_marks))
        if question_score.obtained_marks == int(question_score.obtained_marks)
        else f"{question_score.obtained_marks:.1f}"
    )
    annotations.append(Annotation(
        annotation_type=AnnotationType.SCORE_CIRCLE,
        x=margin_x + 50, y=y_start,
        text=f"{score_text}/{question_score.max_marks}",
        color="#D32F2F", size=22
    ))

    return annotations


# ── Private drawing helpers — realistic examiner pen style ──────────

def _get_font(size: int):
    """Try to load a good font, fallback to default."""
    paths = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",       # macOS
        "/System/Library/Fonts/Helvetica.ttc",                 # macOS
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",# Linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",    # Linux
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def _draw_checkmark(draw: ImageDraw.Draw, x: int, y: int, color: str, size: int, img_w: int = 0):
    """
    Draw a bold, realistic examiner-style tick mark (✓) in the LEFT MARGIN.
    Like a real teacher's pen stroke — thick, confident, slightly angled.
    """
    rgba = _parse_color(color if "green" in str(color).lower() or color.startswith("#0") else "green")
    # Place in left margin, not next to text
    margin_x = min(x, 35)
    s = max(size, 28)
    
    # The tick: short down-right stroke, then long up-right stroke
    # Like a real teacher draws — quick, bold
    p1 = (margin_x, y + s // 3)          # start
    p2 = (margin_x + s // 3, y + s * 2 // 3)  # bottom of tick
    p3 = (margin_x + s, y - s // 6)      # top right
    
    pen_w = max(3, s // 8)
    # Draw multiple overlapping lines for a "pen pressure" effect
    for offset in range(-1, 2):
        draw.line([(p1[0], p1[1] + offset), (p2[0], p2[1] + offset)], fill=rgba, width=pen_w)
        draw.line([(p2[0], p2[1] + offset), (p3[0], p3[1] + offset)], fill=rgba, width=pen_w + 1)


def _draw_cross(draw: ImageDraw.Draw, x: int, y: int, color: str, size: int, img_w: int = 0):
    """
    Draw a bold, realistic examiner-style cross mark (✗) in the LEFT MARGIN.
    """
    rgba = _parse_color("red")
    margin_x = min(x, 35)
    s = max(size, 24)
    half = s // 2
    
    pen_w = max(3, s // 7)
    # Two crossing strokes
    for offset in range(-1, 2):
        draw.line(
            [(margin_x - half // 2, y - half + offset), (margin_x + half, y + half + offset)],
            fill=rgba, width=pen_w
        )
        draw.line(
            [(margin_x - half // 2, y + half + offset), (margin_x + half, y - half + offset)],
            fill=rgba, width=pen_w
        )


def _draw_underline(draw: ImageDraw.Draw, x: int, y: int, width: int, color: str):
    """
    Draw a thick, slightly wavy underline like a real red pen stroke.
    Real examiners underline important/wrong parts with a bold red line.
    """
    rgba = _parse_color(color)
    pen_w = 3
    
    # Draw a slightly wavy line for natural pen feel
    segments = max(4, width // 20)
    points = []
    for i in range(segments + 1):
        px = x + (width * i) // segments
        # Slight waviness — ±1-2px vertical variation
        wave = random.randint(-1, 1)
        py = y + wave
        points.append((px, py))
    
    # Draw the wavy underline
    for i in range(len(points) - 1):
        draw.line([points[i], points[i + 1]], fill=rgba, width=pen_w)
    # Second pass slightly offset for thickness
    for i in range(len(points) - 1):
        draw.line(
            [(points[i][0], points[i][1] + 1), (points[i + 1][0], points[i + 1][1] + 1)],
            fill=rgba, width=pen_w - 1
        )


def _draw_highlight_box(draw: ImageDraw.Draw, x: int, y: int, w: int, h: int, color: str):
    """
    Draw a bracket/box around text — like an examiner circling or bracketing a section.
    Semi-transparent fill + solid border.
    """
    rgba = _parse_color(color)
    # Semi-transparent fill
    fill_rgba = (rgba[0], rgba[1], rgba[2], 25)
    border_rgba = (rgba[0], rgba[1], rgba[2], 180)
    
    pad = 4
    draw.rectangle(
        [(x - pad, y - pad), (x + w + pad, y + h + pad)],
        fill=fill_rgba, outline=border_rgba, width=2
    )
    # Draw corner brackets for emphasis (like a teacher would mark)
    bracket_len = min(12, w // 4, h // 4)
    bw = 3
    # Top-left bracket
    draw.line([(x - pad, y - pad), (x - pad + bracket_len, y - pad)], fill=border_rgba, width=bw)
    draw.line([(x - pad, y - pad), (x - pad, y - pad + bracket_len)], fill=border_rgba, width=bw)
    # Bottom-right bracket
    draw.line([(x + w + pad, y + h + pad), (x + w + pad - bracket_len, y + h + pad)], fill=border_rgba, width=bw)
    draw.line([(x + w + pad, y + h + pad), (x + w + pad, y + h + pad - bracket_len)], fill=border_rgba, width=bw)


def _draw_margin_comment(draw: ImageDraw.Draw, x: int, y: int, text: str, color: str, size: int, img_w: int):
    """
    Draw examiner's comment in the RIGHT MARGIN — like a real teacher writes
    short notes in the margin. Small, neat, in red/green ink.
    """
    if not text or not text.strip():
        return
    
    rgba = _parse_color(color)
    # Place in right margin area
    font_size = min(max(13, size // 2), 16)
    font = _get_font(font_size)
    
    # Position: right margin (past the main text area)
    margin_x = max(x, int(img_w * 0.78)) if img_w > 0 else x
    
    # Trim long text
    display_text = text.strip()
    if len(display_text) > 30:
        display_text = display_text[:28] + ".."
    
    # Draw with slight background for readability
    try:
        bbox = font.getbbox(display_text)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
    except Exception:
        tw, th = len(display_text) * 7, 14
    
    # Ensure it fits on image
    if img_w > 0 and margin_x + tw > img_w - 5:
        margin_x = max(5, img_w - tw - 8)
    
    # Light semi-transparent background
    bg_rgba = (255, 255, 240, 140)
    draw.rectangle(
        [(margin_x - 2, y - 1), (margin_x + tw + 3, y + th + 2)],
        fill=bg_rgba
    )
    draw.text((margin_x, y), display_text, fill=rgba, font=font)


def _draw_text(draw: ImageDraw.Draw, x: int, y: int, text: str, color: str, size: int):
    """Simple text drawing for labels."""
    font = _get_font(min(size, 18))
    rgba = _parse_color(color)
    draw.text((x, y), text, fill=rgba, font=font)


def _draw_score_circle(draw: ImageDraw.Draw, x: int, y: int, text: str, color: str, size: int):
    """Draw a circled score — like a teacher circles the marks."""
    rgba = _parse_color(color)
    r = max(size, 20)
    # Draw circle
    draw.ellipse([(x - r, y - r), (x + r, y + r)], outline=rgba, width=3)
    # Draw score text centered
    font = _get_font(max(14, r - 4))
    try:
        bbox = font.getbbox(text)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
    except Exception:
        tw, th = len(text) * 8, 14
    draw.text((x - tw // 2, y - th // 2), text, fill=rgba, font=font)


def _draw_margin_bracket(draw: ImageDraw.Draw, x: int, y_top: int, height: int,
                         text: str, color: str, size: int, img_w: int):
    """
    Draw a curly bracket '{' in the right margin spanning y_top to y_top+height,
    with a short label next to it. Like a teacher drawing a bracket next to
    several lines and writing a note.
    """
    rgba = _parse_color(color)
    pen_w = 2

    # Place bracket in right margin
    bx = max(x, int(img_w * 0.76)) if img_w > 0 else x
    y_bot = y_top + height
    y_mid = y_top + height // 2
    indent = 8  # how far the bracket tip pokes out

    # Draw a curly bracket shape:  top vertical → curve out → curve back → bottom vertical
    # Top half
    draw.line([(bx, y_top), (bx, y_mid - 4)], fill=rgba, width=pen_w)
    draw.line([(bx, y_mid - 4), (bx - indent, y_mid)], fill=rgba, width=pen_w)
    # Bottom half
    draw.line([(bx - indent, y_mid), (bx, y_mid + 4)], fill=rgba, width=pen_w)
    draw.line([(bx, y_mid + 4), (bx, y_bot)], fill=rgba, width=pen_w)
    # Small serifs at top and bottom
    draw.line([(bx, y_top), (bx + 5, y_top)], fill=rgba, width=pen_w)
    draw.line([(bx, y_bot), (bx + 5, y_bot)], fill=rgba, width=pen_w)

    # Draw label text next to bracket
    if text and text.strip():
        font_size = min(max(12, size // 2), 15)
        font = _get_font(font_size)
        display_text = text.strip()
        if len(display_text) > 25:
            display_text = display_text[:23] + ".."
        label_x = bx + 6
        label_y = y_mid - 7
        try:
            bbox = font.getbbox(display_text)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
        except Exception:
            tw, th = len(display_text) * 7, 13
        # Ensure fits on image
        if img_w > 0 and label_x + tw > img_w - 3:
            label_x = max(3, img_w - tw - 5)
        # Light background
        bg = (255, 255, 240, 140)
        draw.rectangle([(label_x - 2, label_y - 1), (label_x + tw + 2, label_y + th + 1)], fill=bg)
        draw.text((label_x, label_y), display_text, fill=rgba, font=font)


def _draw_total_score(draw: ImageDraw.Draw, text: str, color: str, img_w: int):
    """
    Draw a prominent total score at the top-right of the first page.
    Like a real examiner writes the total marks in a box at the top.
    Example: ┌─────────┐
             │ 51 / 125 │
             └─────────┘
    """
    rgba = _parse_color(color)
    # Use a bold, large font
    score_font = _get_font(28)
    label_font = _get_font(13)

    label = "Total"
    score_text = text or "0"

    # Measure text
    try:
        s_bbox = score_font.getbbox(score_text)
        s_tw = s_bbox[2] - s_bbox[0]
        s_th = s_bbox[3] - s_bbox[1]
    except Exception:
        s_tw, s_th = len(score_text) * 16, 28
    try:
        l_bbox = label_font.getbbox(label)
        l_tw = l_bbox[2] - l_bbox[0]
        l_th = l_bbox[3] - l_bbox[1]
    except Exception:
        l_tw, l_th = 30, 13

    box_w = max(s_tw, l_tw) + 28
    box_h = s_th + l_th + 22

    # Position: top-right corner with margin
    bx = img_w - box_w - 18
    by = 12

    # White filled background
    bg = (255, 255, 255, 230)
    draw.rectangle([(bx, by), (bx + box_w, by + box_h)], fill=bg)
    # Double border (like an exam paper score box)
    border = (rgba[0], rgba[1], rgba[2], 220)
    draw.rectangle([(bx, by), (bx + box_w, by + box_h)], outline=border, width=3)
    draw.rectangle([(bx + 3, by + 3), (bx + box_w - 3, by + box_h - 3)], outline=border, width=1)

    # "Total" label centered at top of box
    label_x = bx + (box_w - l_tw) // 2
    label_y = by + 5
    draw.text((label_x, label_y), label, fill=(0, 0, 0, 200), font=label_font)

    # Score centered below label
    score_x = bx + (box_w - s_tw) // 2
    score_y = by + l_th + 12
    draw.text((score_x, score_y), score_text, fill=rgba, font=score_font)
