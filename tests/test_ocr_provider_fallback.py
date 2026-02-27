from app.utils.ocr_provider import OCRProvider


def test_ocr_provider_falls_back_to_paddle_on_sparse_vision(monkeypatch):
    provider = OCRProvider()
    provider.fallback_only_if_empty = False

    monkeypatch.setattr(provider, "_decode_dims", lambda _: (1000, 1400))
    monkeypatch.setattr(
        provider,
        "_call_vision",
        lambda _img, min_conf=0.5: {
            "words": [{"text": "Q1", "x1": 10, "y1": 10, "x2": 40, "y2": 30, "conf": 0.9, "page": 1}],
            "lines": [],
            "tables": [],
            "provider": "vision",
            "latency_ms": 1,
        },
    )
    monkeypatch.setattr(
        provider,
        "_call_paddle",
        lambda _img: {
            "words": [{"text": "Answer", "x1": 50, "y1": 100, "x2": 140, "y2": 130, "conf": 0.8, "page": 1}],
            "lines": [{"text": "Answer", "x1": 50, "y1": 100, "x2": 140, "y2": 130, "conf": 0.8, "page": 1}],
            "tables": [{"bbox": [40, 90, 200, 220], "page": 1, "cells": []}],
            "provider": "paddle",
            "latency_ms": 2,
        },
    )

    result = provider.detect("ZmFrZV9pbWFnZQ==", min_conf=0.5, min_words=2, min_lines=1)
    assert result["fallback_used"] is True
    assert len(result["words"]) >= 1
    assert len(result["lines"]) >= 1
    assert len(result["tables"]) == 1
    assert "vision" in result["provider"]


def test_ocr_provider_can_skip_fallback_when_disabled(monkeypatch):
    provider = OCRProvider()

    monkeypatch.setattr(provider, "_decode_dims", lambda _: (1000, 1400))
    monkeypatch.setattr(
        provider,
        "_call_vision",
        lambda _img, min_conf=0.5: {
            "words": [],
            "lines": [],
            "tables": [],
            "provider": "vision",
            "latency_ms": 1,
        },
    )

    called = {"paddle": False}

    def _paddle(_img):
        called["paddle"] = True
        return {
            "words": [{"text": "x", "x1": 1, "y1": 1, "x2": 2, "y2": 2, "conf": 1.0, "page": 1}],
            "lines": [{"text": "x", "x1": 1, "y1": 1, "x2": 2, "y2": 2, "conf": 1.0, "page": 1}],
            "tables": [],
            "provider": "paddle",
            "latency_ms": 2,
        }

    monkeypatch.setattr(provider, "_call_paddle", _paddle)
    result = provider.detect("ZmFrZV9pbWFnZQ==", min_conf=0.5, min_words=2, min_lines=1, allow_fallback=False)
    assert called["paddle"] is False
    assert result["fallback_used"] is False
    assert len(result["words"]) == 0
