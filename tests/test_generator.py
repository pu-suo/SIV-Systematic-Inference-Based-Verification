"""
Tests for siv/generator.py — the SIV Generator module.

All tests avoid real API calls by providing a FakeClient whose generate()
method returns a predetermined dict. The frozen_client.generate() interface
is duck-typed, so no mock library is needed for the client itself.
"""
import pytest
from unittest.mock import patch, MagicMock

from siv.schema import (
    Entity, EntityType, Fact, MacroTemplate, Constant, SentenceExtraction,
)
from siv.generator import generate_fol, GenerationResult


# ── Fake clients ──────────────────────────────────────────────────────────────

class _FakeClient:
    """Minimal duck-typed frozen client that returns a fixed response."""
    def __init__(self, fol_string, refusal_reason=None):
        self._response = {"fol": fol_string, "refusal_reason": refusal_reason}

    def generate(self, system_prompt, few_shot_messages, user_content):
        return (self._response, None)


class _CapturingClient:
    """Records all generate() call arguments for inspection."""
    def __init__(self, fol_string):
        self.calls = []
        self._response = {"fol": fol_string, "refusal_reason": None}

    def generate(self, system_prompt, few_shot_messages, user_content):
        self.calls.append({
            "system_prompt": system_prompt,
            "few_shot_messages": few_shot_messages,
            "user_content": user_content,
        })
        return (self._response, None)


# ── Extraction fixtures ───────────────────────────────────────────────────────

def _make_valid_extraction() -> SentenceExtraction:
    """
    'Some dogs are brown.' — a clean existential extraction with no
    Neo-Davidsonian violations.
    """
    return SentenceExtraction(
        nl="Some dogs are brown.",
        entities=[Entity(id="e1", surface="dogs", entity_type=EntityType.EXISTENTIAL)],
        facts=[
            Fact(pred="dogs", args=["e1"], negated=False),
            Fact(pred="brown", args=["e1"], negated=False),
        ],
        macro_template=MacroTemplate.TYPE_I,
    )


def _make_ternary_extraction() -> SentenceExtraction:
    """
    Extraction with a 3-arg fact — triggers high_arity Neo-Davidsonian violation.
    """
    return SentenceExtraction(
        nl="Bonnie schedules a meeting with customer.",
        entities=[
            Entity(id="e1", surface="bonnie", entity_type=EntityType.EXISTENTIAL),
            Entity(id="e2", surface="meeting", entity_type=EntityType.EXISTENTIAL),
            Entity(id="e3", surface="customer", entity_type=EntityType.EXISTENTIAL),
        ],
        facts=[Fact(pred="schedule", args=["e1", "e2", "e3"], negated=False)],
        macro_template=MacroTemplate.GROUND_POSITIVE,
    )


def _make_prepositional_unary_extraction() -> SentenceExtraction:
    """
    Extraction with a prepositional unary fact — triggers prepositional_unary violation.
    """
    return SentenceExtraction(
        nl="Managers work from home.",
        entities=[Entity(id="e1", surface="managers", entity_type=EntityType.UNIVERSAL)],
        facts=[
            Fact(pred="managers", args=["e1"], negated=False),
            Fact(pred="work from home", args=["e1"], negated=False),
        ],
        macro_template=MacroTemplate.TYPE_A,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_generator_refuses_pre_call_on_ternary_extraction():
    """A 3-arg fact triggers high_arity validation before any API call."""
    extraction = _make_ternary_extraction()

    class _NeverCalledClient:
        def generate(self, *args, **kwargs):
            raise AssertionError("generate() must NOT be called on a pre-call refusal")

    result = generate_fol(extraction, _NeverCalledClient())

    assert result.refused is True
    assert result.refusal_stage == "pre_call"
    assert result.fol is None
    assert "high_arity" in result.refusal_reason


def test_generator_refuses_pre_call_on_prepositional_unary():
    """A prepositional unary fact triggers validation before any API call."""
    extraction = _make_prepositional_unary_extraction()

    class _NeverCalledClient:
        def generate(self, *args, **kwargs):
            raise AssertionError("generate() must NOT be called on a pre-call refusal")

    result = generate_fol(extraction, _NeverCalledClient())

    assert result.refused is True
    assert result.refusal_stage == "pre_call"
    assert result.fol is None
    assert "prepositional_unary" in result.refusal_reason


def test_generator_refuses_post_call_on_invariant_failure():
    """
    When the frozen client returns a FOL that fails vocabulary containment
    (invented predicate not in the extraction), the generator refuses
    post-call with invariant_failure.
    """
    extraction = _make_valid_extraction()
    # "Invented" is not in the extraction's facts or entity surfaces
    client = _FakeClient(fol_string="exists x.(Dogs(x) & Invented(x))")

    result = generate_fol(extraction, client)

    assert result.refused is True
    assert result.refusal_stage == "post_call"
    assert result.refusal_reason == "invariant_failure"
    assert result.fol is None
    assert len(result.invariant_failures) >= 1
    assert any("Invented" in f for f in result.invariant_failures)


def test_generator_returns_fol_on_valid_extraction():
    """
    When the frozen client returns a canonical FOL that passes all invariants,
    generate_fol returns a non-refused GenerationResult with the FOL.
    """
    extraction = _make_valid_extraction()
    canonical_fol = "exists x.(Dogs(x) & Brown(x))"
    client = _FakeClient(fol_string=canonical_fol)

    # Patch check_all_invariants so the test is not coupled to the invariant
    # implementations and does not require Vampire for self-consistency.
    with patch("siv.generator.check_all_invariants", return_value=[]):
        result = generate_fol(extraction, client)

    assert result.refused is False
    assert result.fol == canonical_fol
    assert result.refusal_reason is None
    assert result.refusal_stage is None
    assert result.invariant_failures == []


def test_generator_does_not_include_nl_in_prompt():
    """
    The Generator is JSON-only: the NL sentence must NEVER appear in any
    message passed to frozen_client.generate(). This test enforces the
    architectural constraint from Master Document §5.2.
    """
    from siv.schema import Fact, MacroTemplate, Constant

    sent = SentenceExtraction(
        nl="THIS IS THE SECRET SENTENCE TEXT THAT MUST NOT LEAK",
        entities=[],
        facts=[Fact(pred="dog", args=["rex"], negated=False)],
        macro_template=MacroTemplate.GROUND_POSITIVE,
        constants=[Constant(id="rex", surface="Rex")],
    )

    client = _CapturingClient(fol_string="Dog(rex)")

    # Patch check_all_invariants to avoid coupling to invariant logic
    with patch("siv.generator.check_all_invariants", return_value=[]):
        generate_fol(sent, client)

    assert len(client.calls) == 1, "Expected exactly one generate() call"
    call = client.calls[0]

    SECRET = "SECRET SENTENCE TEXT"
    assert SECRET not in call["system_prompt"], (
        "NL sentence leaked into system_prompt"
    )
    assert SECRET not in call["user_content"], (
        "NL sentence leaked into user_content"
    )
    for msg in call["few_shot_messages"]:
        assert SECRET not in msg.get("content", ""), (
            f"NL sentence leaked into few-shot message: {msg}"
        )
