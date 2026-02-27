from app.services.segmentation import build_page_segments, cluster_words_to_lines


def test_segmentation_clusters_into_multiple_blocks():
    words = [
        {"text": "Q1", "x1": 10, "y1": 10, "x2": 30, "y2": 25, "conf": 0.9, "page": 1},
        {"text": "Intro", "x1": 40, "y1": 10, "x2": 90, "y2": 25, "conf": 0.9, "page": 1},
        {"text": "A1", "x1": 20, "y1": 80, "x2": 60, "y2": 95, "conf": 0.9, "page": 1},
        {"text": "A2", "x1": 65, "y1": 80, "x2": 100, "y2": 95, "conf": 0.9, "page": 1},
    ]
    segments = build_page_segments(words=words, tables=[], page=1)
    assert len(segments) >= 2
    assert all(s["segment_id"].startswith("P1-S") for s in segments)


def test_tables_attached_to_intersecting_segment():
    words = [
        {"text": "Ledger", "x1": 100, "y1": 100, "x2": 180, "y2": 120, "conf": 0.9, "page": 1},
    ]
    table = {"bbox": [90, 90, 220, 220], "page": 1, "cells": [{"row": 1, "col": 1, "text": "Amount"}]}
    segments = build_page_segments(words=words, tables=[table], page=1)
    assert len(segments) == 1
    assert len(segments[0]["tables"]) == 1


def test_line_clustering_returns_line_ids():
    words = [
        {"text": "Hello", "x1": 10, "y1": 10, "x2": 40, "y2": 25, "conf": 0.9, "page": 1},
        {"text": "World", "x1": 45, "y1": 11, "x2": 90, "y2": 26, "conf": 0.9, "page": 1},
    ]
    lines = cluster_words_to_lines(words)
    assert len(lines) == 1
    assert lines[0]["line_id"] == "L1"

