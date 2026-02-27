"""Phase 3: layout understanding for college V2 pipeline."""

from __future__ import annotations

import base64
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np


ANCHOR_LEFT_RATIO = 0.45


def _b64_to_cv2(image_base64: str) -> np.ndarray:
    arr = np.frombuffer(base64.b64decode(image_base64), dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Failed to decode image")
    return img


def _detect_layout_type(binary_inv: np.ndarray, blocks: List[Dict[str, Any]]) -> str:
    """Detect page layout type to apply appropriate extraction strategy."""
    h, w = binary_inv.shape[:2]
    
    # Count different block types
    table_count = sum(1 for b in blocks if b.get("type") == "table")
    text_count = sum(1 for b in blocks if b.get("type") == "text")
    
    # Detect multi-column layout
    if len(blocks) >= 4:
        # Check if blocks are arranged in columns
        left_blocks = [b for b in blocks if b["bbox"][0] < w * 0.45]
        right_blocks = [b for b in blocks if b["bbox"][0] > w * 0.55]
        
        if len(left_blocks) >= 2 and len(right_blocks) >= 2:
            return "multi_column"
    
    # Detect table-heavy layout (accounting)
    if table_count > 0 and table_count / max(1, len(blocks)) > 0.3:
        return "table_heavy"
    
    # Detect diagram-heavy layout (science/maths)
    large_blocks = [b for b in blocks if (b["bbox"][2] - b["bbox"][0]) * (b["bbox"][3] - b["bbox"][1]) > w * h * 0.15]
    if len(large_blocks) >= 2:
        return "diagram_heavy"
    
    return "single_column"


def _merge_related_blocks(blocks: List[Dict[str, Any]], layout_type: str) -> List[Dict[str, Any]]:
    """Merge blocks that likely belong together based on layout type."""
    if not blocks or layout_type == "single_column":
        return blocks
    
    merged = []
    skip_indices = set()
    
    for i, block in enumerate(blocks):
        if i in skip_indices:
            continue
        
        # For accounting: merge consecutive small blocks that might be ledger entries
        if layout_type == "table_heavy" and block.get("type") == "text":
            bbox = block["bbox"]
            block_height = bbox[3] - bbox[1]
            
            # Look for nearby blocks at similar x-position (same column)
            related = [block]
            for j in range(i + 1, min(i + 5, len(blocks))):
                if j in skip_indices:
                    continue
                
                next_block = blocks[j]
                next_bbox = next_block["bbox"]
                
                # Check if blocks are vertically aligned and close
                x_overlap = min(bbox[2], next_bbox[2]) - max(bbox[0], next_bbox[0])
                x_width = max(bbox[2] - bbox[0], next_bbox[2] - next_bbox[0])
                
                if x_overlap / x_width > 0.7 and next_bbox[1] - bbox[3] < block_height * 2:
                    related.append(next_block)
                    skip_indices.add(j)
                    bbox = [
                        min(bbox[0], next_bbox[0]),
                        min(bbox[1], next_bbox[1]),
                        max(bbox[2], next_bbox[2]),
                        max(bbox[3], next_bbox[3])
                    ]
                else:
                    break
            
            if len(related) > 1:
                # Create merged block
                merged_block = {
                    "block_id": block["block_id"],
                    "page_number": block["page_number"],
                    "bbox": bbox,
                    "type": "text",
                    "table_density": max(b.get("table_density", 0) for b in related),
                    "detector": "merged_related",
                }
                merged.append(merged_block)
            else:
                merged.append(block)
        else:
            merged.append(block)
    
    return merged


def _table_line_density(binary_inv: np.ndarray, bbox: Tuple[int, int, int, int]) -> float:
    x, y, w, h = bbox
    roi = binary_inv[y : y + h, x : x + w]
    if roi.size == 0:
        return 0.0

    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, w // 10), 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, h // 8)))
    h_lines = cv2.morphologyEx(roi, cv2.MORPH_OPEN, hk)
    v_lines = cv2.morphologyEx(roi, cv2.MORPH_OPEN, vk)
    line_pixels = cv2.countNonZero(h_lines) + cv2.countNonZero(v_lines)
    return float(line_pixels / max(1, w * h))


def _secondary_table_detector(binary_inv: np.ndarray, page_number: int) -> List[Dict[str, Any]]:
    h, w = binary_inv.shape[:2]
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(12, h // 80)))
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(12, w // 80), 1))
    v_lines = cv2.morphologyEx(binary_inv, cv2.MORPH_OPEN, v_kernel)
    h_lines = cv2.morphologyEx(binary_inv, cv2.MORPH_OPEN, h_kernel)
    grid = cv2.bitwise_or(v_lines, h_lines)
    contours, _ = cv2.findContours(grid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    out: List[Dict[str, Any]] = []
    k = 0
    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)
        if bw * bh < 6000:
            continue
        if bw < w * 0.25 or bh < h * 0.05:
            continue
        k += 1
        out.append(
            {
                "block_id": f"P{page_number}-ST{k}",
                "page_number": page_number,
                "bbox": [float(x), float(y), float(x + bw), float(y + bh)],
                "type": "table",
                "detector": "secondary",
            }
        )
    return out


def detect_page_blocks(clean_pages: List[str]) -> Tuple[List[List[Dict[str, Any]]], List[Dict[str, Any]]]:
    """Return PAGE_BLOCKS and recovery flags per page."""
    all_pages: List[List[Dict[str, Any]]] = []
    recovery_flags: List[Dict[str, Any]] = []

    for page_idx, image_b64 in enumerate(clean_pages or [], start=1):
        page_blocks: List[Dict[str, Any]] = []
        try:
            bgr = _b64_to_cv2(image_b64)
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            h, w = gray.shape[:2]
            thr = cv2.adaptiveThreshold(
                gray,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY_INV,
                21,
                15,
            )
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (13, 5))
            conn = cv2.morphologyEx(thr, cv2.MORPH_CLOSE, kernel, iterations=1)
            contours, _ = cv2.findContours(conn, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            block_id = 0
            table_count = 0
            suspected_accounting = False
            temp_blocks = []

            for c in contours:
                x, y, bw, bh = cv2.boundingRect(c)
                area = bw * bh
                # Increased minimum area to filter out tiny regions
                if area < 3000 or bw < 40 or bh < 20:
                    continue

                x1 = max(0, x - 6)
                y1 = max(0, y - 4)
                x2 = min(w, x + bw + 6)
                y2 = min(h, y + bh + 4)
                bw2, bh2 = x2 - x1, y2 - y1
                # Increased minimum area after padding
                if bw2 * bh2 < 3000:
                    continue

                density = _table_line_density(thr, (x1, y1, bw2, bh2))
                is_table = density >= 0.045
                left_anchor_lane = x1 <= int(w * ANCHOR_LEFT_RATIO)
                if density >= 0.03:
                    suspected_accounting = True

                block_type = "text"
                if is_table:
                    block_type = "table"
                    table_count += 1
                elif left_anchor_lane and bh2 < int(h * 0.12):
                    block_type = "question_anchor_candidate"

                block_id += 1
                temp_blocks.append(
                    {
                        "block_id": f"P{page_idx}-B{block_id}",
                        "page_number": page_idx,
                        "bbox": [float(x1), float(y1), float(x2), float(y2)],
                        "type": block_type,
                        "table_density": round(density, 4),
                        "detector": "primary",
                    }
                )

            if not temp_blocks:
                band_count = 6
                pad_x = max(8, int(w * 0.02))
                pad_top = max(8, int(h * 0.015))
                usable_h = max(1, h - (2 * pad_top))
                band_h = max(24, usable_h // band_count)
                for i in range(band_count):
                    y1 = pad_top + (i * band_h)
                    y2 = pad_top + ((i + 1) * band_h if i < band_count - 1 else usable_h)
                    temp_blocks.append(
                        {
                            "block_id": f"P{page_idx}-FB{i+1}",
                            "page_number": page_idx,
                            "bbox": [float(pad_x), float(y1), float(w - pad_x), float(min(h, y2))],
                            "type": "text",
                            "detector": "fallback_band",
                        }
                    )

            if suspected_accounting and table_count == 0:
                secondary = _secondary_table_detector(thr, page_idx)
                if secondary:
                    temp_blocks.extend(secondary)
                    table_count += len(secondary)
                recovery_flags.append(
                    {
                        "page": page_idx,
                        "flag": "table_detector_retry",
                        "trigger": "suspected_accounting_with_zero_tables",
                        "resolved": table_count > 0,
                    }
                )

            # Detect layout type and merge related blocks
            layout_type = _detect_layout_type(thr, temp_blocks)
            page_blocks = _merge_related_blocks(temp_blocks, layout_type)
            
            # Add layout type to recovery flags for debugging
            recovery_flags.append(
                {
                    "page": page_idx,
                    "flag": "layout_detected",
                    "layout_type": layout_type,
                    "blocks_before_merge": len(temp_blocks),
                    "blocks_after_merge": len(page_blocks),
                }
            )

            page_blocks.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))
        except Exception:
            page_blocks = []
            recovery_flags.append(
                {
                    "page": page_idx,
                    "flag": "layout_detection_failed",
                    "trigger": "exception",
                    "resolved": False,
                }
            )

        all_pages.append(page_blocks)

    return all_pages, recovery_flags


__all__ = ["detect_page_blocks"]
