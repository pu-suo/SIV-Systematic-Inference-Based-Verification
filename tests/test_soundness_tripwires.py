"""
Soundness trip-wire tests.

These tests exist to fail loudly if a future refactor reintroduces a
behavior that Stage 3 deliberately removed or added. Each test cites
the Tenet and task that produced the invariant.
"""

import importlib
import inspect
import json
from pathlib import Path

import pytest

from siv.schema import VerificationResult, TestSuite, UnitTest
from siv.compiler import compile_test_suite, compile_sentence_test_suite
from siv.verifier import verify
from siv import schema as schema_mod


# ─── Tenet 1 trip-wires (Task 01) ─────────────────────────────────────────────

def test_tripwire_no_partial_credit_module():
    """Task 01: siv/partial_credit.py must not exist."""
    with pytest.raises(ImportError):
        importlib.import_module("siv.partial_credit")


def test_tripwire_verify_has_no_strict_mode_param():
    """Task 01: verify() must not have a strict_mode parameter."""
    sig = inspect.signature(verify)
    assert "strict_mode" not in sig.parameters


def test_tripwire_verify_has_unresolved_policy():
    """Task 01: verify() must expose unresolved_policy with exactly two values."""
    sig = inspect.signature(verify)
    assert "unresolved_policy" in sig.parameters
    default = sig.parameters["unresolved_policy"].default
    assert default == "raise"


def test_tripwire_verification_result_has_no_partial_credits():
    """Task 01: VerificationResult must not carry a partial_credits field."""
    fields = {f for f in VerificationResult.__dataclass_fields__}
    assert "partial_credits" not in fields


def test_tripwire_component_match_scores_zero(monkeypatch):
    """
    Task 01 + Tenet 1: a candidate containing only 'LovesDeeply' must
    score zero recall on a test expecting 'Loves'. No 0.5 partial credit.
    """
    # Build a minimal test suite by hand — bypass the compiler so this
    # test does not depend on the extraction pipeline.
    suite = TestSuite(
        problem_id="tripwire_tenet1",
        positive_tests=[
            UnitTest(
                fol_string="exists x.exists y.Loves(x,y)",
                test_type="vocabulary",
                is_positive=True,
            )
        ],
        negative_tests=[],
    )
    result = verify("exists x.exists y.LovesDeeply(x,y)", suite, unresolved_policy="exclude")
    assert result.recall_passed == 0
    assert result.recall_rate == 0.0


# ─── Tenet 2 trip-wires (Task 02) ─────────────────────────────────────────────

def test_tripwire_extraction_prompt_has_no_ternary_rule():
    """Task 02: the extraction system prompt must not list 3-arg facts."""
    prompt_path = Path("prompts/extraction_system.txt")
    assert prompt_path.exists()
    text = prompt_path.read_text()
    assert "3-arg" not in text
    assert "ternary" not in text.lower()


def test_tripwire_extraction_prompt_has_neo_davidsonian_block():
    """Task 02: the Neo-Davidsonian block must be present and named."""
    text = Path("prompts/extraction_system.txt").read_text()
    assert "NEO-DAVIDSONIAN FORM" in text
    assert "DITRANSITIVE DECOMPOSITION" in text


def test_tripwire_extraction_examples_are_unary_or_binary():
    """Task 02: every fact in every example must have arity 1 or 2."""
    data = json.load(open("prompts/extraction_examples.json"))
    for ex in data:
        for f in ex["response"]["facts"]:
            assert len(f["args"]) in (1, 2), (
                f"Example '{ex.get('sentence', '?')}' contains a fact with "
                f"arity {len(f['args'])}: {f}"
            )


# ─── Arithmetic trip-wires ────────────────────────────────────────────────────

def test_tripwire_siv_score_precision_only():
    """Task 03 Part F: recall_total=0 with good precision returns precision."""
    r = VerificationResult(
        candidate_fol="dummy",
        syntax_valid=True,
        recall_passed=0,
        recall_total=0,
        precision_passed=3,
        precision_total=3,
        tier1_skips=0,
        tier2_skips=0,
        prover_calls=0,
    )
    assert r.siv_score == 1.0


def test_tripwire_siv_score_recall_only():
    """Task 03 Part F: precision_total=0 with good recall returns recall."""
    r = VerificationResult(
        candidate_fol="dummy",
        syntax_valid=True,
        recall_passed=3,
        recall_total=3,
        precision_passed=0,
        precision_total=0,
        tier1_skips=0,
        tier2_skips=0,
        prover_calls=0,
    )
    assert r.siv_score == 1.0


# ─── Tenet 4 trip-wire (pre-existing, reaffirmed) ────────────────────────────

def test_tripwire_prepositional_unary_still_flagged():
    """Tenet 4: the validator must still flag prepositional 1-arg predicates."""
    from siv.schema import (
        SentenceExtraction, Entity, EntityType, Fact, MacroTemplate,
        ProblemExtraction,
    )
    sent = SentenceExtraction(
        nl="No managers work remotely from home.",
        entities=[Entity(id="e1", surface="managers", entity_type=EntityType.UNIVERSAL)],
        facts=[Fact(pred="work remotely from home", args=["e1"], negated=True)],
        macro_template=MacroTemplate.TYPE_E,
    )
    extraction = ProblemExtraction(problem_id="tripwire_tenet4", sentences=[sent])
    suite = compile_test_suite(extraction)
    assert suite.has_violations
    assert any(v.violation_type == "prepositional_unary" for v in suite.violations)
