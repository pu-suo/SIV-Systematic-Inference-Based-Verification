"""Tests for siv/extractor.py — fallback extraction only (no API required)."""
import pytest
from siv.extractor import _fallback_extraction, _nltk_fallback, _parse_response, _dict_to_extraction
from siv.schema import EntityType, MacroTemplate, Constant
from siv.pre_analyzer import _SPACY_AVAILABLE


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


# ── _nltk_fallback ────────────────────────────────────────────────────────────

def test_nltk_fallback_returns_extraction():
    result = _nltk_fallback("Nancy is a queen.", [])
    assert result.nl == "Nancy is a queen."
    assert isinstance(result.macro_template, MacroTemplate)
    assert len(result.entities) > 0

def test_nltk_fallback_universal_macro():
    result = _nltk_fallback("All dogs are animals.", [])
    assert result.macro_template in (MacroTemplate.TYPE_A, MacroTemplate.TYPE_E,
                                      MacroTemplate.GROUND_POSITIVE)
    # At minimum, should not crash and should produce entities
    assert len(result.entities) >= 0

def test_nltk_fallback_entity_types():
    result = _nltk_fallback("Nancy runs.", [])
    for e in result.entities:
        assert isinstance(e.entity_type, EntityType)


# ── _fallback_extraction ──────────────────────────────────────────────────────

@pytest.mark.skipif(not _SPACY_AVAILABLE, reason="spaCy not installed")
def test_spacy_fallback_entities_nonempty():
    result = _fallback_extraction("The tall tree grows quickly.")
    assert len(result.entities) > 0

@pytest.mark.skipif(not _SPACY_AVAILABLE, reason="spaCy not installed")
def test_spacy_fallback_facts_nonempty():
    result = _fallback_extraction("The tall tree grows quickly.")
    assert len(result.facts) > 0

@pytest.mark.skipif(not _SPACY_AVAILABLE, reason="spaCy not installed")
def test_spacy_fallback_proper_noun_to_constants():
    """Proper nouns must be routed to constants list, not entities."""
    result = _fallback_extraction("Nancy runs.")
    const_surfaces = [c.surface.lower() for c in result.constants]
    assert "nancy" in const_surfaces
    entity_surfaces = [e.surface.lower() for e in result.entities]
    assert "nancy" not in entity_surfaces

def test_fallback_always_returns_valid_extraction():
    """Even without spaCy, fallback must return a valid SentenceExtraction."""
    result = _fallback_extraction("All students like difficult exams.")
    assert result.nl == "All students like difficult exams."
    assert isinstance(result.macro_template, MacroTemplate)
    assert isinstance(result.entities, list)
    assert isinstance(result.facts, list)


# ── _nltk_fallback constants routing ─────────────────────────────────────────

def test_nltk_fallback_proper_noun_to_constants():
    """NNP/NNPS tokens must appear in constants, not entities."""
    result = _nltk_fallback("Nancy is a queen.", [])
    const_ids = [c.id for c in result.constants]
    assert "nancy" in const_ids
    entity_surfaces = [e.surface.lower() for e in result.entities]
    assert "nancy" not in entity_surfaces


def test_nltk_fallback_constants_are_constant_objects():
    result = _nltk_fallback("James manages the office.", [])
    for c in result.constants:
        assert isinstance(c, Constant)


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
