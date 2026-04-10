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


# ─── Soundness Defense 1 trip-wires (Task 03) ────────────────────────────────

def test_tripwire_universal_binding_has_inhabitation_conjunct():
    """
    Task 03 + §4.5 Defense 1: any universal binding test must be
    wrapped with an inhabitation conjunct '(exists x.Type(x)) & ...'.
    """
    from siv.schema import (
        SentenceExtraction, Entity, EntityType, Fact, MacroTemplate,
        ProblemExtraction,
    )
    sent = SentenceExtraction(
        nl="All employees schedule meetings.",
        entities=[
            Entity(id="e1", surface="employees", entity_type=EntityType.UNIVERSAL),
            Entity(id="e2", surface="meetings", entity_type=EntityType.EXISTENTIAL),
        ],
        facts=[Fact(pred="schedule", args=["e1", "e2"])],
        macro_template=MacroTemplate.TYPE_A,
    )
    extraction = ProblemExtraction(problem_id="tripwire_inhabit", sentences=[sent])
    suite = compile_test_suite(extraction)
    universal_tests = [t for t in suite.positive_tests if t.fol_string.startswith("all ")
                       or "(exists x." in t.fol_string and "all x." in t.fol_string]
    assert any("(exists x." in t.fol_string and "all x." in t.fol_string
               for t in suite.positive_tests), (
        "No inhabitation-preconditioned universal test found in the compiled suite. "
        "Expected form: '(exists x.Type(x)) & all x.(Type(x) -> ...)'."
    )


def test_tripwire_vacuous_universal_candidate_fails():
    """
    Task 03 + §4.5 Defense 1: a candidate asserting an empty type
    must NOT pass inhabitation-preconditioned universal tests.
    """
    from siv.schema import (
        SentenceExtraction, Entity, EntityType, Fact, MacroTemplate,
        ProblemExtraction,
    )
    sent = SentenceExtraction(
        nl="All employees are busy.",
        entities=[Entity(id="e1", surface="employees", entity_type=EntityType.UNIVERSAL)],
        facts=[Fact(pred="busy", args=["e1"])],
        macro_template=MacroTemplate.TYPE_A,
    )
    extraction = ProblemExtraction(problem_id="tripwire_vacuous", sentences=[sent])
    suite = compile_test_suite(extraction)

    # Vacuous-universal exploit candidate: asserts no employees exist.
    vacuous = "all x.(-Employees(x))"
    result = verify(vacuous, suite, unresolved_policy="exclude")
    # The candidate must not get full recall credit.
    assert result.recall_rate < 1.0, (
        "Vacuous-universal candidate scored full recall — the inhabitation "
        "precondition defense has regressed."
    )


# ─── Soundness Defense 2 trip-wires (Task 03) ────────────────────────────────

def test_tripwire_verification_result_has_candidate_inconsistent_field():
    """Task 03 + §4.5 Defense 2: the field must exist."""
    fields = {f for f in VerificationResult.__dataclass_fields__}
    assert "candidate_inconsistent" in fields


def test_tripwire_ast_level_inconsistency_catches_direct_contradiction():
    """Task 03 + §4.5 Defense 2: the AST-level check catches P(a) & -P(a)."""
    try:
        from siv.consistency import ast_level_inconsistency
    except ImportError:
        from siv.schema import ast_level_inconsistency
    assert ast_level_inconsistency("P(a) & -P(a)") is True
    assert ast_level_inconsistency("P(a) & Q(b)") is False
    assert ast_level_inconsistency("P(a) & -Q(a)") is False


def test_tripwire_inconsistent_candidate_short_circuits_to_zero():
    """
    Task 03 + §4.5 Defense 2: an internally inconsistent candidate
    scores SIV=0 regardless of the test suite.
    """
    suite = TestSuite(
        problem_id="tripwire_inconsistent",
        positive_tests=[UnitTest(fol_string="exists x.Dog(x)", test_type="vocabulary", is_positive=True)],
        negative_tests=[],
    )
    result = verify("Dog(a) & -Dog(a)", suite, unresolved_policy="exclude")
    assert result.candidate_inconsistent is True
    assert result.siv_score == 0.0


# ─── Arithmetic trip-wires (Task 03 Part F) ──────────────────────────────────

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
