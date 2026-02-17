"""
Annotation service - generates annotated images with grading marks.
Migrated from server.py annotation functions (lines ~6828-7992).

These functions are very large and use Vision OCR + annotation_utils for
positioning grading marks on student answer images.
"""

from typing import List, Dict, Optional
import base64
import io
import re

from PIL import Image

from app.config import logger 
from app.models.submission import QuestionScore, AnnotationData
from app.utils.annotation_utils import (
    Annotation,
    AnnotationType,
    apply_annotations_to_image,
    auto_position_annotations_for_question
)
from app.utils.vision_ocr_service import get_vision_service


def _generate_margin_annotations(
    page_idx: int,
    page_questions: List[QuestionScore],
    img_height: int
) -> List[Annotation]:
    """Generate simple margin-based annotations when OCR fails"""
    annotations = []
    margin_x = 30
    section_height = img_height // max(1, len(page_questions))
    
    for q_idx, q_score in enumerate(page_questions):
        # Place the per-question score near the END of the question's section (right-margin)
        section_top = q_idx * section_height
        section_end_y = min(img_height - 60, (q_idx + 1) * section_height - 20)
        y_pos = section_end_y
        score_pct = (q_score.obtained_marks / q_score.max_marks * 100) if q_score.max_marks > 0 else 0
        
        annotations.append(Annotation(
            annotation_type=AnnotationType.POINT_NUMBER,
            x=margin_x,
            y=max(32, y_pos - 8),
            text=str(q_score.question_number),
            color="black",
            size=22
        ))
        
        score_text = str(int(q_score.obtained_marks)) if q_score.obtained_marks == int(q_score.obtained_marks) else f"{q_score.obtained_marks:.1f}"
        annotations.append(Annotation(
            annotation_type=AnnotationType.SCORE_CIRCLE,
            x=margin_x + 50,
            y=y_pos,
            text=f"{score_text}/{int(q_score.max_marks)}",
            color="green" if score_pct >= 50 else "red",
            size=28
        ))
    
    return annotations


def generate_annotated_images(
    original_images: List[str],
    question_scores: List[QuestionScore]
) -> List[str]:
    """
    Generate annotated images by overlaying grading annotations on original student answer images.
    Basic version without Vision OCR.
    """
    try:
        logger.info(f"Generating annotated images for {len(original_images)} pages")

        # Map questions to pages
        page_questions: Dict[int, List[QuestionScore]] = {i: [] for i in range(len(original_images))}
        for q_score in question_scores:
            if q_score.page_number and q_score.page_number > 0:
                page_idx = min(q_score.page_number - 1, len(original_images) - 1)
            else:
                page_idx = min(
                    int((q_score.question_number - 1) / max(1, len(question_scores) / len(original_images))),
                    len(original_images) - 1
                )
            page_questions[page_idx].append(q_score)

        annotated_images = []
        for page_idx, original_image in enumerate(original_images):
            try:
                image_data = base64.b64decode(original_image)
                with Image.open(io.BytesIO(image_data)) as img:
                    img_width, img_height = img.size
            except Exception as e:
                logger.warning(f"Could not get image dimensions: {e}, using defaults")
                img_width, img_height = 1000, 1400

            positioned_annotations: List[Annotation] = []
            auto_annotation_y = 140
            auto_annotation_step = 60
            comment_cursor_y = int(img_height * 0.12)
            comment_x = int(img_width * 0.72)
            comment_step = max(22, int(img_height * 0.02))

            for q_score in page_questions.get(page_idx, []):
                for ann_data in q_score.annotations:
                    if ann_data.page_index != page_idx:
                        continue
                    if ann_data.box_2d and len(ann_data.box_2d) == 4:
                        ymin, xmin, ymax, xmax = ann_data.box_2d
                        x_pos = int(xmin / 1000 * img_width)
                        y_pos = int(ymin / 1000 * img_height)
                    elif ann_data.x > 0 or ann_data.y > 0:
                        x_pos = ann_data.x if ann_data.x > 0 else 30
                        y_pos = ann_data.y if ann_data.y > 0 else 120
                    else:
                        if ann_data.type in {AnnotationType.COMMENT, AnnotationType.MARGIN_NOTE}:
                            x_pos = comment_x
                            y_pos = comment_cursor_y
                            comment_cursor_y += comment_step
                        else:
                            x_pos = 40
                            y_pos = auto_annotation_y
                            auto_annotation_y += auto_annotation_step
                    positioned_annotations.append(Annotation(
                        annotation_type=ann_data.type, x=x_pos, y=y_pos,
                        text=ann_data.text, color=ann_data.color, size=ann_data.size
                    ))

                for sub_score in q_score.sub_scores:
                    for ann_data in sub_score.annotations:
                        if ann_data.page_index != page_idx:
                            continue
                        if ann_data.box_2d and len(ann_data.box_2d) == 4:
                            ymin, xmin, ymax, xmax = ann_data.box_2d
                            x_pos = int(xmin / 1000 * img_width)
                            y_pos = int(ymin / 1000 * img_height)
                        elif ann_data.x > 0 or ann_data.y > 0:
                            x_pos = ann_data.x if ann_data.x > 0 else 30
                            y_pos = ann_data.y if ann_data.y > 0 else 120
                        else:
                            if ann_data.type in {AnnotationType.COMMENT, AnnotationType.MARGIN_NOTE}:
                                x_pos = comment_x
                                y_pos = comment_cursor_y
                                comment_cursor_y += comment_step
                            else:
                                x_pos = 40
                                y_pos = auto_annotation_y
                                auto_annotation_y += auto_annotation_step
                        positioned_annotations.append(Annotation(
                            annotation_type=ann_data.type, x=x_pos, y=y_pos,
                            text=ann_data.text, color=ann_data.color, size=ann_data.size
                        ))

            if not positioned_annotations:
                annotated_images.append(original_image)
                continue

            annotated_image = apply_annotations_to_image(original_image, positioned_annotations)
            annotated_images.append(annotated_image)

        logger.info(f"Successfully generated {len(annotated_images)} annotated images")
        return annotated_images
        
    except Exception as e:
        logger.error(f"Error generating annotated images: {e}", exc_info=True)
        return original_images


async def generate_annotated_images_with_vision_ocr(
    original_images: List[str],
    question_scores: List[QuestionScore],
    use_vision_ocr: bool = False,
    dense_red_pen: bool = False
) -> List[str]:
    """
    Generate annotated images using Vision OCR for precise text positioning.
    Falls back to basic annotation if OCR is unavailable.
    
    This is a large function (~700 lines) migrated from server.py.
    It uses Google Cloud Vision OCR to find exact text positions on the page
    and places annotations (ticks, crosses, underlines, comments) precisely.
    """
    if not use_vision_ocr and not dense_red_pen:
        logger.info("Vision OCR disabled - generating margin annotations")
        return generate_annotated_images(original_images, question_scores)

    vision_service = get_vision_service()
    if not vision_service.is_available() and not dense_red_pen:
        logger.warning("Vision OCR not available - using margin annotations")
        return generate_annotated_images(original_images, question_scores)

    # Helper functions for OCR-based annotation positioning
    def _normalize_text(text: str) -> List[str]:
        if not text:
            return []
        return [t for t in re.sub(r"[^a-zA-Z0-9\s]", " ", text.lower()).split() if t]

    def _word_text(word):
        return getattr(word, "text", None) if not isinstance(word, dict) else word.get("text")

    def _word_vertices(word):
        return getattr(word, "vertices", None) if not isinstance(word, dict) else word.get("vertices", [])

    def _find_anchor_box(words, anchor_text: str):
        tokens = _normalize_text(anchor_text)
        if not tokens:
            return None
        try:
            from thefuzz import fuzz
        except ImportError:
            return None

        word_texts = [str(_word_text(w) or "").lower() for w in words]
        best = None
        best_score = 0
        for i in range(0, len(word_texts) - len(tokens) + 1):
            window = word_texts[i:i + len(tokens)]
            if not window:
                continue
            window_text = " ".join(window)
            score = fuzz.ratio(" ".join(tokens), window_text)
            if score > best_score:
                best_score = score
                best = words[i:i + len(tokens)]
        if not best or best_score < 60:
            return None
        # Handle both word formats
        all_xs = []
        all_ys = []
        for w in best:
            if isinstance(w, dict) and "x1" in w:
                all_xs.extend([w["x1"], w["x2"]])
                all_ys.extend([w["y1"], w["y2"]])
            else:
                verts = _word_vertices(w) or []
                all_xs.extend([v.get("x", 0) for v in verts])
                all_ys.extend([v.get("y", 0) for v in verts])
        if not all_xs or not all_ys:
            return None
        return min(all_xs), min(all_ys), max(all_xs), max(all_ys)

    def _build_ocr_words(words):
        ocr_words = []
        for w in words:
            if isinstance(w, dict) and "x1" in w:
                x1, y1, x2, y2 = w["x1"], w["y1"], w["x2"], w["y2"]
                text = w.get("text", "")
            else:
                xs = [v.get("x", 0) for v in (_word_vertices(w) or [])]
                ys = [v.get("y", 0) for v in (_word_vertices(w) or [])]
                if not xs or not ys:
                    continue
                x1, x2 = min(xs), max(xs)
                y1, y2 = min(ys), max(ys)
                text = _word_text(w) or ""
            ocr_words.append({"text": text, "x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1, "xc": (x1 + x2) / 2, "yc": (y1 + y2) / 2})
        ocr_words.sort(key=lambda i: (i["yc"], i["x"]))
        return ocr_words

    def _group_words_into_lines(words, y_threshold: float):
        """Group words into lines based on vertical proximity.
        Handles both formats: {x1,y1,x2,y2} from VisionOCRService 
        and {vertices: [{x,y},...]} from raw Vision API objects."""
        if not words:
            return []
        items = []
        for w in words:
            # Try x1/y1/x2/y2 format first (from VisionOCRService)
            if isinstance(w, dict) and "x1" in w:
                x1 = w.get("x1", 0)
                y1 = w.get("y1", 0)
                x2 = w.get("x2", 0)
                y2 = w.get("y2", 0)
                text = w.get("text", "")
            else:
                # Fallback to vertices format
                verts = _word_vertices(w) or []
                xs = [v.get("x", 0) for v in verts]
                ys = [v.get("y", 0) for v in verts]
                if not xs or not ys:
                    continue
                x1, x2 = min(xs), max(xs)
                y1, y2 = min(ys), max(ys)
                text = _word_text(w) or ""
            if x1 is None or y1 is None or x2 is None or y2 is None:
                continue
            items.append({"text": text, "x1": x1, "x2": x2, "y1": y1, "y2": y2, "yc": (y1 + y2) / 2})
        items.sort(key=lambda i: (i["yc"], i["x1"]))
        lines = []
        for item in items:
            if not lines:
                lines.append([item])
                continue
            last = lines[-1]
            if abs(item["yc"] - last[-1]["yc"]) <= y_threshold:
                last.append(item)
            else:
                lines.append([item])
        line_boxes = []
        for line in lines:
            xs = [i["x1"] for i in line] + [i["x2"] for i in line]
            ys = [i["y1"] for i in line] + [i["y2"] for i in line]
            text = " ".join(i["text"] for i in line)
            line_boxes.append({"text": text, "x1": min(xs), "y1": min(ys), "x2": max(xs), "y2": max(ys)})
        return line_boxes

    def _build_word_boxes(words):
        boxes = []
        for w in words:
            if isinstance(w, dict) and "x1" in w:
                boxes.append((w["x1"], w["y1"], w["x2"], w["y2"]))
            else:
                xs = [v.get("x", 0) for v in (_word_vertices(w) or [])]
                ys = [v.get("y", 0) for v in (_word_vertices(w) or [])]
                if xs and ys:
                    boxes.append((min(xs), min(ys), max(xs), max(ys)))
        return boxes

    # Process each page
    annotated_images: List[str] = []
    q_score_map = {qs.question_number: qs for qs in question_scores}
    question_numbers = sorted({qs.question_number for qs in question_scores})
    question_patterns = {
        q_num: re.compile(rf"^\s*(?:Q\s*)?{q_num}\s*[\).:-]?\s*", re.IGNORECASE)
        for q_num in question_numbers
    }

    # Compute total score once for the first-page header
    _total_obtained = sum(
        qs.obtained_marks for qs in question_scores if qs.obtained_marks >= 0
    )
    _total_max = sum(
        qs.max_marks for qs in question_scores if qs.obtained_marks >= 0
    )
    def _fmt_score(v):
        return str(int(v)) if v == int(v) else f"{v:.1f}"
    _total_score_text = f"{_fmt_score(_total_obtained)} / {_fmt_score(_total_max)}"

    # --- PRE-SCAN: OCR all pages to locate the final line for each question ---
    pages_ocr = [None] * len(original_images)
    question_last_line: Dict[int, tuple] = {}  # q_num -> (page_idx, line_idx, line_box)

    for p_idx, original_image_b64 in enumerate(original_images):
        try:
            image_data = base64.b64decode(original_image_b64)
            with Image.open(io.BytesIO(image_data)) as _img:
                p_w, p_h = _img.size
        except Exception:
            p_w, p_h = 1000, 1400

        try:
            ocr_result = vision_service.detect_text_from_base64(original_image_b64, ["en"])
            words = ocr_result.get("words", [])
        except Exception:
            words = []

        y_threshold = max(10, int(p_h * 0.012))
        line_boxes = _group_words_into_lines(words, y_threshold)

        # Build a per-page line-index map (Qn -> {L#: box}) so we can identify last lines
        line_index_map = {}
        line_counts_local: Dict[int, int] = {}
        current_q_local = question_numbers[0] if question_numbers else 0
        line_id_map_local: Dict[str, dict] = {}
        answer_start_y_local = int(p_h * 0.25)
        footer_margin = max(48, int(p_h * 0.03))
        for line in line_boxes:
            text = (line.get("text") or "").strip()
            if text:
                for q_num, pattern in question_patterns.items():
                    if pattern.match(text):
                        current_q_local = q_num
                        break
            line_counts_local[current_q_local] = line_counts_local.get(current_q_local, 0) + 1
            li = line_counts_local[current_q_local]
            line_id = f"Q{current_q_local}-L{li}"
            line_id_map_local[line_id] = line
            line_index_map.setdefault(current_q_local, {})[li] = line

            # Prefer to record the last *meaningful* line for a question — ignore headers/footers/page-numbers
            y1_l = line.get("y1", 0)
            y2_l = line.get("y2", 0)
            short_numeric = text.isdigit() and len(text) <= 3
            is_footer = (y2_l >= p_h - footer_margin) or short_numeric
            if y2_l >= answer_start_y_local and not is_footer:
                question_last_line[current_q_local] = (p_idx, li, line)

        page_text = " ".join(w.get("text", "") for w in words).lower()
        basic_intro = bool(
            re.search(r"(rubric|evaluation|parameter|marking\s+scheme|header|instruction|next\s+page|test\s+case|turn\s+to|answer\s+key)", page_text)
            or (len(line_boxes) < 3)
            or (len(words) < 10)
        )
        # If a question header (Qn) appears on the page, treat it as an answer page
        has_question_header = any(
            any(pat.match((line.get("text") or "").strip()) for pat in question_patterns.values())
            for line in line_boxes
        )
        is_intro = basic_intro and not has_question_header

        pages_ocr[p_idx] = {
            "words": words,
            "line_boxes": line_boxes,
            "line_index_map": line_index_map,
            "line_id_map": line_id_map_local,
            "img_w": p_w,
            "img_h": p_h,
            "is_intro": is_intro,
        }

    # --- ASSIGN MISSING question.page_number USING OCR pre-scan ---
    # If grading didn't set page_number on QuestionScore, infer it from OCR line matches so
    # score circles can be placed deterministically beside the question end-line.
    for qs in question_scores:
        try:
            if getattr(qs, "page_number", None):
                continue
        except Exception:
            # qs may be a dict-like fallback in some call-sites
            if isinstance(qs, dict) and qs.get("page_number"):
                continue
        qn = qs.question_number
        assigned = False
        for p_idx, p in enumerate(pages_ocr):
            if not p:
                continue
            line_index_map = p.get("line_index_map", {})
            if qn in line_index_map and line_index_map[qn]:
                # assign inferred page number (1-indexed)
                try:
                    qs.page_number = p_idx + 1
                except Exception:
                    # if qs is dict-like, set key
                    if isinstance(qs, dict):
                        qs["page_number"] = p_idx + 1
                assigned = True
                logger.info(f"[PAGE-INFER] Assigned page {p_idx+1} to Q{qn} via OCR pre-scan")
                break
        if not assigned:
            logger.debug(f"[PAGE-INFER] Could not infer page for Q{qn}")

    # --- MAIN PER-PAGE RENDER PASS (uses stored OCR from pre-scan) ---
    for page_idx, original_image in enumerate(original_images):

        # Use pre-scanned OCR data for this page
        page_data = pages_ocr[page_idx]
        if not page_data or not page_data.get("words"):
            # Fall back to basic annotations for this page
            annotated_images.append(original_image)
            continue

        words = page_data["words"]
        line_boxes = page_data["line_boxes"]
        img_width = page_data["img_w"]
        img_height = page_data["img_h"]
        answer_start_y = int(img_height * 0.25)
        is_intro_page = page_data.get("is_intro", False)

        positioned_annotations: List[Annotation] = []

        # On the first page, ONLY draw total score, NO OTHER ANNOTATIONS
        if page_idx == 0:
            positioned_annotations.append(Annotation(
                annotation_type=AnnotationType.TOTAL_SCORE,
                x=0, y=0, text=_total_score_text, color="red", size=28
            ))
            # Skip all answer annotations on first page
            annotated_image = apply_annotations_to_image(original_image, positioned_annotations)
            annotated_images.append(annotated_image)
            continue

        # SKIP INTRO/RUBRIC/HEADER PAGES COMPLETELY - NO ANNOTATIONS AT ALL
        if is_intro_page:
            logger.info(f"[ANN-SKIP] Page {page_idx+1}: Detected as intro/rubric/header page - skipping all annotations")
            annotated_images.append(original_image)
            continue

        # Reuse precomputed line ID maps from pre-scan
        line_id_map = page_data.get("line_id_map", {})
        line_index_map = page_data.get("line_index_map", {})
        current_q = question_numbers[0] if question_numbers else 0
        logger.debug(f"[ANN-LINE-MAP] Page {page_idx+1}: Reusing {len(line_id_map)} line IDs")

        def _parse_line_id(value: Optional[str]):
            if not value:
                return None
            match = re.match(r"^Q(\d+)-L(\d+)$", str(value).strip(), re.IGNORECASE)
            if not match:
                return None
            return int(match.group(1)), int(match.group(2))

        def _expand_line_range(start_id: Optional[str], end_id: Optional[str]) -> List[str]:
            start = _parse_line_id(start_id)
            end = _parse_line_id(end_id) if end_id else start
            if not start:
                return []
            if not end or start[0] != end[0]:
                return [f"Q{start[0]}-L{start[1]}"]
            q_num = start[0]
            start_idx = min(start[1], end[1])
            end_idx = max(start[1], end[1])
            return [f"Q{q_num}-L{i}" for i in range(start_idx, end_idx + 1)]

        # Position line-id or anchor-based annotations
        total_ann_requested = 0
        line_id_placed = 0
        line_id_skipped = 0
        anchor_placed = 0
        
        for q_score in question_scores:
            for ann_data in q_score.annotations:
                if ann_data.page_index not in (-1, page_idx):
                    continue
                
                total_ann_requested += 1
                line_ids = []
                if ann_data.line_id:
                    line_ids = [ann_data.line_id]
                elif ann_data.line_id_start or ann_data.line_id_end:
                    line_ids = _expand_line_range(ann_data.line_id_start, ann_data.line_id_end)

                if line_ids:
                    # ── Collect all resolved line boxes first ──
                    resolved_lines = []
                    for line_id in line_ids:
                        line = line_id_map.get(line_id)
                        if not line:
                            if not resolved_lines:  # Only log once per annotation
                                parsed = _parse_line_id(line_id)
                                q_num_str = f"Q{parsed[0]}" if parsed else "?"
                                avail = [k for k in line_id_map if k.startswith(q_num_str + "-")]
                                logger.warning(f"[ANN-SKIP] Page {page_idx+1}: Line ID '{line_id}' not found. Q{q_score.question_number}, Type={ann_data.type}. Available {q_num_str}: {avail[:10]}")
                            continue
                        x1, y1, x2, y2 = line["x1"], line["y1"], line["x2"], line["y2"]
                        if y2 < answer_start_y:
                            continue
                        resolved_lines.append((x1, y1, x2, y2))

                    if not resolved_lines:
                        line_id_skipped += 1
                        continue

                    ann_type = str(ann_data.type or "").upper()
                    reason_text = (ann_data.text or ann_data.label or ann_data.feedback or "").strip()

                    # Bounding box of entire span
                    span_x1 = min(r[0] for r in resolved_lines)
                    span_y1 = min(r[1] for r in resolved_lines)
                    span_x2 = max(r[2] for r in resolved_lines)
                    span_y2 = max(r[3] for r in resolved_lines)
                    span_cy = (span_y1 + span_y2) // 2
                    is_multi_line = len(resolved_lines) > 1

                    if ann_type in {"UNDERLINE", "ERROR_UNDERLINE", "FEEDBACK_UNDERLINE", "EMPHASIS_UNDERLINE"}:
                        # Underline each line
                        for (lx1, ly1, lx2, ly2) in resolved_lines:
                            width = max(40, lx2 - lx1)
                            positioned_annotations.append(Annotation(
                                annotation_type=AnnotationType.ERROR_UNDERLINE,
                                x=lx1, y=ly2 + 3, text="", color=ann_data.color or "#c00020", size=width
                            ))
                        # Reason: bracket if multi-line, else single comment
                        if reason_text:
                            if is_multi_line:
                                positioned_annotations.append(Annotation(
                                    annotation_type=AnnotationType.MARGIN_BRACKET,
                                    x=span_x2 + 10, y=span_y1,
                                    text=reason_text, color=ann_data.color or "#c00020",
                                    size=24, height=span_y2 - span_y1
                                ))
                            else:
                                positioned_annotations.append(Annotation(
                                    annotation_type=AnnotationType.COMMENT,
                                    x=span_x2 + 10, y=span_y1,
                                    text=reason_text, color=ann_data.color or "#c00020", size=24
                                ))
                        line_id_placed += 1

                    elif ann_type in {"TICK", "CHECKMARK", "DOUBLE_TICK"}:
                        if is_multi_line:
                            # ONE tick at the first line, bracket with reason spanning all lines
                            first_cy = (resolved_lines[0][1] + resolved_lines[0][3]) // 2
                            positioned_annotations.append(Annotation(
                                annotation_type=AnnotationType.CHECKMARK,
                                x=30, y=first_cy - 10, text="", color="green", size=28
                            ))
                            if reason_text:
                                positioned_annotations.append(Annotation(
                                    annotation_type=AnnotationType.MARGIN_BRACKET,
                                    x=span_x2 + 10, y=span_y1,
                                    text=reason_text, color="green",
                                    size=24, height=span_y2 - span_y1
                                ))
                        else:
                            # Single line: tick + inline comment
                            line_cy = (resolved_lines[0][1] + resolved_lines[0][3]) // 2
                            positioned_annotations.append(Annotation(
                                annotation_type=AnnotationType.CHECKMARK,
                                x=30, y=line_cy - 10, text="", color="green", size=28
                            ))
                            if reason_text:
                                positioned_annotations.append(Annotation(
                                    annotation_type=AnnotationType.COMMENT,
                                    x=span_x2 + 10, y=span_y1,
                                    text=reason_text, color="green", size=24
                                ))
                        line_id_placed += 1

                    elif ann_type in {"CROSS", "CROSS_MARK"}:
                        if is_multi_line:
                            first_cy = (resolved_lines[0][1] + resolved_lines[0][3]) // 2
                            positioned_annotations.append(Annotation(
                                annotation_type=AnnotationType.CROSS_MARK,
                                x=30, y=first_cy - 8, text="", color="red", size=26
                            ))
                            if reason_text:
                                positioned_annotations.append(Annotation(
                                    annotation_type=AnnotationType.MARGIN_BRACKET,
                                    x=span_x2 + 10, y=span_y1,
                                    text=reason_text, color="red",
                                    size=24, height=span_y2 - span_y1
                                ))
                        else:
                            line_cy = (resolved_lines[0][1] + resolved_lines[0][3]) // 2
                            positioned_annotations.append(Annotation(
                                annotation_type=AnnotationType.CROSS_MARK,
                                x=30, y=line_cy - 8, text="", color="red", size=26
                            ))
                            if reason_text:
                                positioned_annotations.append(Annotation(
                                    annotation_type=AnnotationType.COMMENT,
                                    x=span_x2 + 10, y=span_y1,
                                    text=reason_text, color="red", size=24
                                ))
                        line_id_placed += 1

                    elif ann_type in {"COMMENT", "BOX_COMMENT"}:
                        # Single comment in right margin at span midpoint
                        positioned_annotations.append(Annotation(
                            annotation_type=AnnotationType.COMMENT,
                            x=span_x2 + 10, y=span_cy - 8,
                            text=reason_text, color=ann_data.color or "red", size=26
                        ))
                        line_id_placed += 1

                    elif ann_type in {"BOX", "HIGHLIGHT_BOX"}:
                        # One box around the entire span + reason in margin
                        pad = 4
                        positioned_annotations.append(Annotation(
                            annotation_type=AnnotationType.HIGHLIGHT_BOX,
                            x=span_x1 - pad, y=span_y1 - pad, text="",
                            color=ann_data.color or "red",
                            width=max(30, span_x2 - span_x1 + pad * 2),
                            height=max(16, span_y2 - span_y1 + pad * 2)
                        ))
                        # If the span covers multiple lines, draw a curly bracket in the margin
                        # (bracket indicates the note applies to the whole boxed block).
                        if reason_text:
                            if is_multi_line:
                                positioned_annotations.append(Annotation(
                                    annotation_type=AnnotationType.MARGIN_BRACKET,
                                    x=span_x2 + 10, y=span_y1,
                                    text=reason_text, color=ann_data.color or "red",
                                    size=24, height=span_y2 - span_y1
                                ))
                            else:
                                positioned_annotations.append(Annotation(
                                    annotation_type=AnnotationType.MARGIN_NOTE,
                                    x=span_x2 + 10, y=span_y1,
                                    text=reason_text, color=ann_data.color or "red", size=24
                                ))
                        line_id_placed += 1
                    continue

                if ann_data.anchor_text:
                    box = _find_anchor_box(words, ann_data.anchor_text)
                    if box:
                        x1, y1, x2, y2 = box
                        if y2 < answer_start_y:
                            continue
                        line_cy = (y1 + y2) // 2
                        reason_text = (ann_data.text or ann_data.label or ann_data.feedback or "").strip()
                        if ann_data.type == AnnotationType.CHECKMARK:
                            positioned_annotations.append(Annotation(
                                annotation_type=AnnotationType.CHECKMARK,
                                x=30, y=line_cy - 10, text="", color="green", size=28
                            ))
                            if reason_text:
                                positioned_annotations.append(Annotation(
                                    annotation_type=AnnotationType.COMMENT,
                                    x=x2 + 10, y=y1, text=reason_text,
                                    color="green", size=24
                                ))
                            anchor_placed += 1
                        elif ann_data.type == AnnotationType.CROSS_MARK:
                            positioned_annotations.append(Annotation(
                                annotation_type=AnnotationType.CROSS_MARK,
                                x=30, y=line_cy - 8, text="", color="red", size=26
                            ))
                            if reason_text:
                                positioned_annotations.append(Annotation(
                                    annotation_type=AnnotationType.COMMENT,
                                    x=x2 + 10, y=y1, text=reason_text,
                                    color="red", size=24
                                ))
                            anchor_placed += 1

        logger.info(f"[ANN-SUMMARY] Page {page_idx+1}: Requested={total_ann_requested}, LineID placed={line_id_placed}, LineID skipped={line_id_skipped}, Anchor placed={anchor_placed}")

        # Ensure every page with substantial handwriting gets AT LEAST 7 annotations
        # Skip intro/next pages (pages with very few lines)
        # Only use GREEN boxes - red is reserved for actual error/correction feedback
        non_total = [a for a in positioned_annotations if a.annotation_type != AnnotationType.TOTAL_SCORE]
        
        # Only add fallback if: (1) insufficient marks AND (2) page has substantial content (4+ lines)
        if len(non_total) < 7 and line_boxes and len(line_boxes) >= 4:
            # Page is a real answer page with insufficient marks; auto-add GREEN boxes only
            candidates = [l for l in line_boxes if l.get("y2", 0) >= answer_start_y]
            candidates = sorted(candidates, key=lambda l: l.get("y1", 0))
            needed = 7 - len(non_total)  # How many more marks to reach 7
            
            # Pick diverse lines: first, middle sections, and near end
            picks = []
            if candidates:
                picks.append(candidates[0])  # First line
                if len(candidates) > 1:
                    picks.append(candidates[len(candidates) // 3])  # Lower third
                if len(candidates) > 2:
                    picks.append(candidates[len(candidates) // 2])  # Middle
                if len(candidates) > 3:
                    picks.append(candidates[2 * len(candidates) // 3])  # Upper third
                if len(candidates) > 4:
                    picks.append(candidates[-1])  # Last line
            
            # Remove duplicates while preserving order
            seen = set()
            unique_picks = []
            for l in picks:
                key = (l.get('y1', 0), l.get('x1', 0))
                if key not in seen:
                    unique_picks.append(l)
                    seen.add(key)
            picks = unique_picks[:needed]
            
            # Add MIXED FEEDBACK - both positive (GREEN) and constructive (RED)
            # Balance: roughly 50-60% positive, 40-50% critical/improvement feedback
            positive_labels = [
                "Well explained point", "Strong constitutional basis", "Relevant case law cited", 
                "Accurate data with source", "Good substantiation", "Proper legal framework",
                "Contextual understanding shown", "Evidence-based claim", "Strong argumentation"
            ]
            critical_labels = [
                "Needs more examples", "Lacks substantiation", "Missing key statute", 
                "Vague explanation needed", "Should cite relevant case", "Incomplete coverage",
                "Needs schedule/article reference", "Lacks constitutional basis", "More clarity needed"
            ]
            
            # Alternate between positive and critical feedback
            for idx, line in enumerate(picks):
                x1, y1, x2, y2 = line["x1"], line["y1"], line["x2"], line["y2"]
                
                # Alternate: even index = positive (green), odd index = critical (red)
                is_positive = (idx % 2 == 0)
                
                if is_positive:
                    label = positive_labels[idx % len(positive_labels)]
                    color = "green"
                else:
                    label = critical_labels[idx % len(critical_labels)]
                    color = "red"
                
                positioned_annotations.append(Annotation(
                    annotation_type=AnnotationType.HIGHLIGHT_BOX,
                    x=x1 - 4, y=y1 - 4, text="", color=color,
                    width=max(30, x2 - x1 + 8), height=max(16, y2 - y1 + 8)
                ))
                positioned_annotations.append(Annotation(
                    annotation_type=AnnotationType.MARGIN_NOTE,
                    x=x2 + 10, y=y1,
                    text=label, color=color, size=24
                ))

        # --- Add per-question total marks at the question's final line (right-margin score) ---
        for qs in question_scores:
            qn = qs.question_number
            placed_score = False

            # 1) Prefer page_number on QuestionScore (explicit mapping from grading)
            page_for_q = (qs.page_number - 1) if getattr(qs, "page_number", None) else None
            if page_for_q == page_idx:
                # Try to find the question START line first (where 'Qn' appears)
                lines_map = page_data.get("line_index_map", {}).get(qn, {})
                if lines_map:
                    # Prefer the smallest line index (question header/start)
                    start_li = min(lines_map.keys())
                    start_line = lines_map[start_li]
                    start_text = (start_line.get("text") or "").strip()
                    is_header = False
                    try:
                        pat = question_patterns.get(qn)
                        if pat and pat.match(start_text):
                            is_header = True
                    except Exception:
                        pass

                    if is_header:
                        # Place score next to question START line (user requested)
                        raw_mid = (start_line.get("y1", 0) + start_line.get("y2", 0)) // 2
                        answer_top = int(img_height * 0.12)
                        clamp_top = max(answer_top, start_line.get("y1", 0) + 4)
                        clamp_bottom = min(img_height - 48, start_line.get("y2", 0) - 2)
                        mid_y = max(clamp_top, min(raw_mid, clamp_bottom))
                        place_x = min(start_line.get("x2", img_width // 2) + 60, img_width - 48)

                        score_text = _fmt_score(qs.obtained_marks)
                        max_text = _fmt_score(qs.max_marks)
                        pct = (qs.obtained_marks / max(1, qs.max_marks)) if qs.max_marks > 0 else 0
                        color = "green" if pct >= 0.5 else "red"
                        positioned_annotations.append(Annotation(
                            annotation_type=AnnotationType.SCORE_CIRCLE,
                            x=place_x, y=mid_y,
                            text=f"{score_text}/{max_text}", color=color, size=26
                        ))
                        text_x = min(place_x + 34, img_width - 140)
                        text_y = max(8, mid_y - 12)
                        positioned_annotations.append(Annotation(
                            annotation_type=AnnotationType.MARGIN_NOTE,
                            x=text_x, y=text_y,
                            text=f"Marks: {score_text}/{max_text}", color=color, size=16
                        ))
                        placed_score = True
                        logger.debug(f"[SCORE-PLACE-START] Q{qn} -> page {page_idx+1} at y={mid_y} (by question start)")
                    else:
                        # Fallback to last-line placement if header not found on this page
                        last_li = max(lines_map.keys())
                        last_line = lines_map[last_li]
                        raw_mid = (last_line.get("y1", 0) + last_line.get("y2", 0)) // 2
                        answer_top = int(img_height * 0.12)
                        clamp_top = max(answer_top, last_line.get("y1", 0) + 4)
                        clamp_bottom = min(img_height - 48, last_line.get("y2", 0) - 2)
                        mid_y = max(clamp_top, min(raw_mid, clamp_bottom))
                        place_x = min(last_line.get("x2", img_width // 2) + 60, img_width - 48)

                        score_text = _fmt_score(qs.obtained_marks)
                        max_text = _fmt_score(qs.max_marks)
                        pct = (qs.obtained_marks / max(1, qs.max_marks)) if qs.max_marks > 0 else 0
                        color = "green" if pct >= 0.5 else "red"
                        # More visible score circle + textual label
                        positioned_annotations.append(Annotation(
                            annotation_type=AnnotationType.SCORE_CIRCLE,
                            x=place_x, y=mid_y,
                            text=f"{score_text}/{max_text}", color=color, size=22
                        ))
                        # Add a small margin text label to make marks unmistakable
                        text_x = min(place_x + 28, img_width - 120)
                        text_y = max(8, mid_y - 10)
                        positioned_annotations.append(Annotation(
                            annotation_type=AnnotationType.MARGIN_NOTE,
                            x=text_x, y=text_y,
                            text=f"Marks: {score_text}/{max_text}", color=color, size=14
                        ))
                        placed_score = True
                        logger.debug(f"[SCORE-PLACE] Q{qn} -> page {page_idx+1} at y={mid_y} (by page_number fallback)")

            # 2) Fall back to the pre-scanned question_last_line if it lies on this page
            if not placed_score:
                last = question_last_line.get(qn)
                if last and last[0] == page_idx and qs.obtained_marks is not None and qs.obtained_marks >= 0:
                    _, _, last_line = last
                    raw_mid = (last_line.get("y1", 0) + last_line.get("y2", 0)) // 2
                    answer_top = int(img_height * 0.12)
                    clamp_top = max(answer_top, last_line.get("y1", 0) + 4)
                    clamp_bottom = min(img_height - 48, last_line.get("y2", 0) - 2)
                    mid_y = max(clamp_top, min(raw_mid, clamp_bottom))

                    place_x = min(last_line.get("x2", img_width // 2) + 60, img_width - 48)
                    score_text = _fmt_score(qs.obtained_marks)
                    max_text = _fmt_score(qs.max_marks)
                    pct = (qs.obtained_marks / max(1, qs.max_marks)) if qs.max_marks > 0 else 0
                    color = "green" if pct >= 0.5 else "red"
                    # More visible score circle + textual label
                    positioned_annotations.append(Annotation(
                        annotation_type=AnnotationType.SCORE_CIRCLE,
                        x=place_x, y=mid_y,
                        text=f"{score_text}/{max_text}", color=color, size=22
                    ))
                    text_x = min(place_x + 28, img_width - 120)
                    text_y = max(8, mid_y - 10)
                    positioned_annotations.append(Annotation(
                        annotation_type=AnnotationType.MARGIN_NOTE,
                        x=text_x, y=text_y,
                        text=f"Marks: {score_text}/{max_text}", color=color, size=14
                    ))
                    placed_score = True
                    logger.debug(f"[SCORE-PLACE] Q{qn} -> page {page_idx+1} at y={mid_y} (by last-line)")

            # 3) If no line found for this question on this page but the question is expected on this page,
            #    place a fallback score circle near the lower section of the question's area.
            if not placed_score and page_for_q == page_idx:
                # Estimate a reasonable Y by dividing page into N question slots for this page
                page_qs = [q for q in question_scores if (getattr(q, 'page_number', None) and q.page_number - 1 == page_idx)]
                if page_qs:
                    # Determine index among page questions
                    try:
                        idx_in_page = next(i for i, q in enumerate(page_qs) if q.question_number == qn)
                    except StopIteration:
                        idx_in_page = 0
                    slot_h = max(80, img_height // max(1, len(page_qs)))
                    est_y = int((idx_in_page + 0.85) * slot_h)
                    est_y = max(64, min(img_height - 80, est_y))
                    place_x = min(int(img_width * 0.72), img_width - 48)
                    score_text = _fmt_score(qs.obtained_marks)
                    max_text = _fmt_score(qs.max_marks)
                    pct = (qs.obtained_marks / max(1, qs.max_marks)) if qs.max_marks > 0 else 0
                    color = "green" if pct >= 0.5 else "red"
                    # More visible score circle + textual label for estimated placement
                    positioned_annotations.append(Annotation(
                        annotation_type=AnnotationType.SCORE_CIRCLE,
                        x=place_x, y=est_y,
                        text=f"{score_text}/{max_text}", color=color, size=22
                    ))
                    text_x = min(place_x + 28, img_width - 120)
                    text_y = max(8, est_y - 10)
                    positioned_annotations.append(Annotation(
                        annotation_type=AnnotationType.MARGIN_NOTE,
                        x=text_x, y=text_y,
                        text=f"Marks: {score_text}/{max_text}", color=color, size=14
                    ))
                    placed_score = True
                    logger.debug(f"[SCORE-PLACE] Q{qn} -> page {page_idx+1} at y={est_y} (estimated slot)")

            # otherwise do not place a score for questions that do not belong to this page


        annotated_image = apply_annotations_to_image(original_image, positioned_annotations)
        annotated_images.append(annotated_image)

    logger.info(f"OCR annotations applied to {len(annotated_images)} pages")
    return annotated_images
