"""Tests for siv/extractor.py (no API required)."""
import pytest
from siv.extractor import extract_sentence, _parse_response, _dict_to_extraction
from siv.schema import EntityType, MacroTemplate, Constant
from siv.pre_analyzer import analyze_sentence


# ── _parse_response ───────────────────────────────────────────────────────────

def test_parse_response_clean_json():
    raw = '{"entities": [{"id": "e1", "surface": "tree", "entity_type": "existential"}], "facts": [{"pred": "tall", "args": ["e1"], "negated": false}], "macro_template": "ground_positive"}'
    data = _parse_response(raw)
    assert data["entities"][0]["id"] == "e1"
    assert data["facts"][0]["pred"] == "tall"

def test_parse_response_strips_markdown():
    raw = '```json\n{"entities": [], "facts": [], "macro_template": "ground_positive"}\n```'
    data = _parse_response(raw)
    assert data["macro_template"] == "ground_positive"

def test_parse_response_missing_entities_raises():
    with pytest.raises((ValueError, KeyError, Exception)):
        _parse_response('{"facts": []}')

def test_parse_response_invalid_json_raises():
    with pytest.raises(Exception):
        _parse_response("not json at all")


# ── extract_sentence backend guard ───────────────────────────────────────────

def test_extract_sentence_no_backend_raises():
    """Must raise RuntimeError if neither client nor vllm_extractor is provided."""
    with pytest.raises(RuntimeError, match="No extraction backend"):
        extract_sentence("Test.", analyze_sentence("Test."))


# ── _parse_response two-list format ──────────────────────────────────────────

def test_parse_response_new_two_list_format():
    """New format with separate constants and entities arrays."""
    raw = (
        '{"constants": [{"id": "lanaWilson", "surface": "Lana Wilson"}], '
        '"entities": [{"id": "e1", "surface": "film", "entity_type": "existential"}], '
        '"facts": [{"pred": "directed", "args": ["lanaWilson", "e1"], "negated": false}], '
        '"macro_template": "ground_positive"}'
    )
    data = _parse_response(raw)
    assert len(data["constants"]) == 1
    assert data["constants"][0]["id"] == "lanaWilson"
    assert len(data["entities"]) == 1


def test_parse_response_old_entity_type_constant_accepted():
    """Old-format entity_type='constant' in entities list must not raise."""
    raw = (
        '{"entities": [{"id": "bonnie", "surface": "Bonnie", "entity_type": "constant"}], '
        '"facts": [{"pred": "sings", "args": ["bonnie"], "negated": false}], '
        '"macro_template": "ground_positive"}'
    )
    data = _parse_response(raw)
    assert len(data["entities"]) == 1  # still in entities list at raw parse stage


# ── _dict_to_extraction constants routing ────────────────────────────────────

def test_dict_to_extraction_populates_constants():
    """constants key in data → Constant objects in SentenceExtraction.constants."""
    data = {
        "constants": [{"id": "bonnie", "surface": "Bonnie"}],
        "entities": [],
        "facts": [{"pred": "sings", "args": ["bonnie"], "negated": False}],
        "macro_template": "ground_positive",
    }
    sent = _dict_to_extraction("Bonnie sings.", data, [])
    assert len(sent.constants) == 1
    assert sent.constants[0].id == "bonnie"
    assert len(sent.entities) == 0


def test_dict_to_extraction_entity_type_constant_routes_to_constants():
    """Old-format entity_type='constant' must be routed to constants list."""
    data = {
        "constants": [],
        "entities": [{"id": "bonnie", "surface": "Bonnie", "entity_type": "constant"}],
        "facts": [{"pred": "sings", "args": ["bonnie"], "negated": False}],
        "macro_template": "ground_positive",
    }
    sent = _dict_to_extraction("Bonnie sings.", data, [])
    const_ids = [c.id for c in sent.constants]
    assert "bonnie" in const_ids
    assert all(e.surface.lower() != "bonnie" for e in sent.entities)
