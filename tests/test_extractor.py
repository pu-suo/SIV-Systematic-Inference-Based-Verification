"""Tests for siv/extractor.py (no API required)."""
import json
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from siv.extractor import extract_sentence, _dict_to_extraction, _register_entities_across_sentences
from siv.frozen_client import FrozenClient
from siv.schema import Entity, EntityType, Fact, MacroTemplate, Constant, SentenceExtraction
from siv.pre_analyzer import analyze_sentence


# ── Stub helpers ──────────────────────────────────────────────────────────────

@dataclass
class _StubMessage:
    content: str


@dataclass
class _StubChoice:
    message: object


@dataclass
class _StubResponse:
    choices: list
    system_fingerprint: str = "fp_test"


def _make_stub_client(response_json: dict):
    stub = MagicMock()
    stub.chat.completions.create.return_value = _StubResponse(
        choices=[_StubChoice(message=_StubMessage(content=json.dumps(response_json)))]
    )
    return stub


def _minimal_response():
    return {
        "constants": [],
        "entities": [{"id": "e1", "surface": "tree", "entity_type": "existential"}],
        "facts": [{"pred": "tall", "args": ["e1"], "negated": False}],
        "macro_template": "ground_positive",
    }


# ── _dict_to_extraction: replacement tests for deleted _parse_response ────────
#
# _parse_response has been deleted (Task 05). The JSON Schema response_format
# binding now guarantees that FrozenClient.extract() returns pre-parsed,
# structurally valid JSON. The tests below verify the same semantic behaviors
# via _dict_to_extraction, which is the layer that receives the parsed dict.

def test_dict_to_extraction_handles_clean_json():
    """Replacement for test_parse_response_clean_json:
    _dict_to_extraction must correctly map a well-formed dict."""
    data = {
        "constants": [],
        "entities": [{"id": "e1", "surface": "tree", "entity_type": "existential"}],
        "facts": [{"pred": "tall", "args": ["e1"], "negated": False}],
        "macro_template": "ground_positive",
    }
    sent = _dict_to_extraction("The tall tree.", data, [])
    assert sent.entities[0].id == "e1"
    assert sent.facts[0].pred == "tall"


def test_dict_to_extraction_handles_entities_only_format():
    """Replacement for test_parse_response_strips_markdown:
    _dict_to_extraction must handle the old format (no constants key)."""
    data = {
        "entities": [{"id": "e1", "surface": "tree", "entity_type": "existential"}],
        "facts": [{"pred": "tall", "args": ["e1"], "negated": False}],
        "macro_template": "ground_positive",
    }
    sent = _dict_to_extraction("The tall tree.", data, [])
    assert sent.entities[0].surface == "tree"
    assert sent.facts[0].pred == "tall"
    assert sent.constants == []


def test_dict_to_extraction_missing_facts_raises():
    """Replacement for test_parse_response_missing_entities_raises:
    _dict_to_extraction must raise if facts is absent."""
    data = {
        "constants": [],
        "entities": [{"id": "e1", "surface": "tree", "entity_type": "existential"}],
        "macro_template": "ground_positive",
    }
    with pytest.raises(Exception):
        _dict_to_extraction("The tall tree.", data, [])


def test_extract_sentence_wraps_raw_client_in_frozen_client(tmp_path, monkeypatch):
    """Replacement for test_parse_response_invalid_json_raises:
    extract_sentence must auto-wrap a raw OpenAI client in FrozenClient."""
    monkeypatch.setattr("siv.frozen_client.CACHE_FILE", tmp_path / "cache.jsonl")
    monkeypatch.setattr("siv.frozen_client.CACHE_DIR", tmp_path)

    stub = _make_stub_client(_minimal_response())
    result = extract_sentence("A tall tree.", analyze_sentence("A tall tree."), client=stub)
    assert result.entities[0].surface == "tree"
    # Raw client was wrapped — call still went through
    assert stub.chat.completions.create.call_count == 1


# ── _dict_to_extraction two-list format ──────────────────────────────────────

def test_dict_to_extraction_new_two_list_format():
    """Replacement for test_parse_response_new_two_list_format:
    new format with separate constants and entities arrays."""
    data = {
        "constants": [{"id": "lanaWilson", "surface": "Lana Wilson"}],
        "entities": [{"id": "e1", "surface": "film", "entity_type": "existential"}],
        "facts": [{"pred": "directed", "args": ["lanaWilson", "e1"], "negated": False}],
        "macro_template": "ground_positive",
    }
    sent = _dict_to_extraction("Lana Wilson directed a film.", data, [])
    assert len(sent.constants) == 1
    assert sent.constants[0].id == "lanaWilson"
    assert len(sent.entities) == 1


def test_dict_to_extraction_old_entity_type_constant_accepted():
    """Replacement for test_parse_response_old_entity_type_constant_accepted:
    old-format entity_type='constant' in entities list must not raise and must
    be routed to the constants list by _dict_to_extraction."""
    data = {
        "entities": [{"id": "bonnie", "surface": "Bonnie", "entity_type": "constant"}],
        "facts": [{"pred": "sings", "args": ["bonnie"], "negated": False}],
        "macro_template": "ground_positive",
    }
    sent = _dict_to_extraction("Bonnie sings.", data, [])
    # entity_type='constant' must be routed to constants, not entities
    const_ids = [c.id for c in sent.constants]
    assert "bonnie" in const_ids
    assert len(sent.entities) == 0


# ── extract_sentence backend guard ───────────────────────────────────────────

def test_extract_sentence_no_backend_raises():
    """Must raise RuntimeError if neither client nor vllm_extractor is provided."""
    with pytest.raises(RuntimeError, match="No extraction backend"):
        extract_sentence("Test.", analyze_sentence("Test."))


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


# ── FIX E1: whitespace-normalised registry key ────────────────────────────────

def _make_sent(nl: str, entity_surface: str, entity_id: str = "e1") -> SentenceExtraction:
    """Helper: build a minimal SentenceExtraction with one entity."""
    return SentenceExtraction(
        nl=nl,
        entities=[Entity(id=entity_id, surface=entity_surface, entity_type=EntityType.EXISTENTIAL)],
        facts=[],
        macro_template=MacroTemplate.GROUND_POSITIVE,
        compound_analyses=[],
        constants=[],
    )


def test_fix_E1_whitespace_normalized_registry():
    """
    FIX E1 (narrow): internal whitespace in entity surface forms must not
    cause duplicate registry entries.

    Positive case: "company building" vs "company  building" (two spaces)
      → same canonical id after registration.
    Case-insensitive case: "company building" vs "Company Building"
      → same canonical id (pre-existing .lower() behaviour, confirmed no regression).
    Negative case: "company building" vs "building"
      → different ids (Tenet-1 guardrail: distinct surface forms stay distinct).
    """
    # --- Positive case: whitespace collapse ---
    s1 = _make_sent("Sent 1.", "company building")
    s2 = _make_sent("Sent 2.", "company  building")   # two spaces
    result = _register_entities_across_sentences([s1, s2])
    assert result[0].entities[0].id == result[1].entities[0].id, (
        "single-space and double-space surface must resolve to the same entity id"
    )

    # --- Case-insensitive case: confirm no regression on .lower() ---
    s3 = _make_sent("Sent 3.", "company building")
    s4 = _make_sent("Sent 4.", "Company Building")
    result2 = _register_entities_across_sentences([s3, s4])
    assert result2[0].entities[0].id == result2[1].entities[0].id, (
        "different casing of the same surface must resolve to the same entity id"
    )

    # --- Negative case: Tenet-1 guardrail — distinct surfaces stay distinct ---
    s5 = _make_sent("Sent 5.", "company building")
    s6 = _make_sent("Sent 6.", "building")
    result3 = _register_entities_across_sentences([s5, s6])
    assert result3[0].entities[0].id != result3[1].entities[0].id, (
        "'company building' and 'building' are different surface forms and must NOT collapse"
    )
