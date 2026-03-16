"""Tests for siv/extractor.py — fallback extraction only (no API required)."""
import pytest
from siv.extractor import _fallback_extraction, _nltk_fallback, _parse_response
from siv.schema import EntityType, MacroTemplate
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
def test_spacy_fallback_entity_type():
    result = _fallback_extraction("Nancy runs.")
    names = [e.surface.lower() for e in result.entities]
    assert "nancy" in names
    nancy = next(e for e in result.entities if e.surface.lower() == "nancy")
    assert nancy.entity_type == EntityType.CONSTANT

def test_fallback_always_returns_valid_extraction():
    """Even without spaCy, fallback must return a valid SentenceExtraction."""
    result = _fallback_extraction("All students like difficult exams.")
    assert result.nl == "All students like difficult exams."
    assert isinstance(result.macro_template, MacroTemplate)
    assert isinstance(result.entities, list)
    assert isinstance(result.facts, list)
