from app.layers.ai_structured.prompts import (
    build_extraction_prompt,
    get_extraction_system_prompt,
)


def test_system_prompt_forbids_mark_assignment():
    prompt = get_extraction_system_prompt().lower()
    assert "do not assign marks" in prompt
    assert "strict json" in prompt


def test_system_prompt_has_json_safety_rules():
    prompt = get_extraction_system_prompt().lower()
    assert "no markdown" in prompt or "no code fences" in prompt
    assert "no raw newlines" in prompt


def test_extraction_prompt_blocks_mcq_subparts():
    prompt = build_extraction_prompt(raw_ocr_text="sample", batch_index=1, total_batches=1).lower()
    assert "mcq options must be in options" in prompt
    assert "do not output or_group_id" in prompt
    assert "any one/any of the following/alternative question" in prompt
