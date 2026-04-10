"""
Tests for scripts/siv_inspect.py — the SIV Inspector CLI.

All offline tests use --extraction-json to avoid API calls.
Tests that require the API mock it via monkeypatch.
"""
import json
import os
import sys
import pytest
from unittest.mock import MagicMock, patch

from siv.schema import (
    Entity, EntityType, Fact, MacroTemplate,
    ProblemExtraction, SentenceExtraction,
)

from scripts.siv_inspect import main


# ── Shared extraction fixtures ────────────────────────────────────────────────

_SIMPLE_EXTRACTION_DICT = {
    "constants": [],
    "entities": [{"id": "e1", "surface": "dogs", "entity_type": "universal"}],
    "facts": [{"pred": "mammals", "args": ["e1"], "negated": False}],
    "macro_template": "universal_affirmative",
}

_SIMPLE_EXTRACTION_JSON = json.dumps(_SIMPLE_EXTRACTION_DICT)

_SECOND_EXTRACTION_JSON = json.dumps({
    "constants": [],
    "entities": [{"id": "e1", "surface": "mammals", "entity_type": "universal"}],
    "facts": [{"pred": "breathe", "args": ["e1"], "negated": False}],
    "macro_template": "universal_affirmative",
})


# ── Test 1: Offline smoke test ────────────────────────────────────────────────

def test_offline_smoke(capsys):
    """
    --extraction-json with a minimal valid extraction: exit 0, output shows
    extraction fields.
    """
    main(["--extraction-json", _SIMPLE_EXTRACTION_JSON])
    captured = capsys.readouterr()
    assert "mammals" in captured.out
    assert "dogs" in captured.out
    assert "universal" in captured.out


# ── Test 2: Offline with candidate ───────────────────────────────────────────

def test_offline_with_candidate(capsys):
    """
    --extraction-json + --candidate: output contains 'SIV ='.
    """
    main([
        "--extraction-json", _SIMPLE_EXTRACTION_JSON,
        "--candidate", "all x.(Dogs(x) -> Mammals(x))",
    ])
    captured = capsys.readouterr()
    assert "SIV =" in captured.out


# ── Test 3: JSON output shape ─────────────────────────────────────────────────

def test_json_output_shape(capsys):
    """
    --extraction-json + --json: output is valid JSON with 'premises' key
    and premises[0].extraction.
    """
    main(["--extraction-json", _SIMPLE_EXTRACTION_JSON, "--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "premises" in data
    assert len(data["premises"]) == 1
    assert "extraction" in data["premises"][0]
    assert "test_suite" in data["premises"][0]


# ── Test 4: Multiple premises offline ────────────────────────────────────────

def test_multiple_premises_offline(capsys):
    """
    Two --extraction-json values: both appear in output.
    """
    main([
        "--extraction-json", _SIMPLE_EXTRACTION_JSON,
        "--extraction-json", _SECOND_EXTRACTION_JSON,
    ])
    captured = capsys.readouterr()
    # Both premises' predicates should appear
    assert "mammals" in captured.out
    assert "breathe" in captured.out


# ── Test 5: Missing API key without --extraction-json exits 2 ─────────────────

def test_missing_api_key_exits_2(monkeypatch):
    """
    No --extraction-json, no OPENAI_API_KEY → exit code 2.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(SystemExit) as exc_info:
        main(["All dogs are mammals."])
    assert exc_info.value.code == 2


# ── Test 6: Invalid extraction JSON exits 2 ──────────────────────────────────

def test_invalid_extraction_json_exits_2():
    """
    --extraction-json '{garbage}' → exit code 2.
    """
    with pytest.raises(SystemExit) as exc_info:
        main(["--extraction-json", "{garbage}"])
    assert exc_info.value.code == 2


# ── Test 7: JSON output with candidate ───────────────────────────────────────

def test_json_output_with_candidate(capsys):
    """
    --json + --candidate: candidate_result is populated in JSON output.
    """
    main([
        "--extraction-json", _SIMPLE_EXTRACTION_JSON,
        "--candidate", "all x.(Dogs(x) -> Mammals(x))",
        "--json",
    ])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    cr = data["premises"][0]["candidate_result"]
    assert cr is not None
    assert "siv_score" in cr
    assert "recall_rate" in cr
    assert "precision_rate" in cr


# ── Test 8: No args → exit 2 ─────────────────────────────────────────────────

def test_no_args_exits_2(monkeypatch):
    """
    No sentences and no --extraction-json → exit code 2.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 2
