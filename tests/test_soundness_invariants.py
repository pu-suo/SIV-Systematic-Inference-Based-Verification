"""Soundness invariant tests (SIV.md §8, Phase 4).

Exercises C9a (entailment monotonicity) and C9b (contrastive soundness) on
the 22-sentence invariant corpus.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pytest

from siv.compiler import compile_canonical_fol, compile_sentence_test_suite
from siv.invariants import (
    check_contrastive_soundness,
    check_entailment_monotonicity,
)
from siv.schema import (
    AtomicFormula,
    Formula,
    SentenceExtraction,
    TestSuite,
    UnitTest,
    validate_extraction,
)
from siv.vampire_interface import is_vampire_available


vampire_required = pytest.mark.skipif(
    not is_vampire_available(), reason="Vampire not available"
)


# ── Corpus assembly (14 + 8 = 22) ──────────────────────────────────────────

_ROOT = Path(__file__).parent.parent
_PHASE2_EXAMPLES = json.loads(
    (_ROOT / "prompts" / "extraction_examples.json").read_text()
)
_INVARIANT_EXTRAS = json.loads(
    (_ROOT / "tests" / "data" / "invariant_corpus.json").read_text()
)

# Label the Phase 2 14 as the base corpus; the extras carry a `pattern` tag.
CORPUS = _PHASE2_EXAMPLES + _INVARIANT_EXTRAS


def test_corpus_has_at_least_twenty_two_entries():
    assert len(CORPUS) >= 22


def test_corpus_covers_all_required_patterns():
    """§16 requires each of the eight additional patterns present ≥ 1 time."""
    extras_patterns = {e["pattern"] for e in _INVARIANT_EXTRAS}
    required = {
        "nested_universal_over_existential_different_scopes",
        "connective_with_quantification_with_connective_nucleus",
        "disjunction_with_three_operands",
        "negation_of_implication",
        "biconditional_between_two_quantifieds",
        "ground_atomic_two_constants",
        "universal_with_disjunctive_nucleus",
        "universal_with_inner_existential_restrictor_containing_connective",
    }
    missing = required - extras_patterns
    assert not missing, f"missing required patterns: {missing}"


# ── Per-entry invariant checks ─────────────────────────────────────────────

_CORPUS_IDS = [e["sentence"] for e in CORPUS]


@vampire_required
@pytest.mark.parametrize("entry", CORPUS, ids=_CORPUS_IDS)
def test_entailment_monotonicity_on_corpus(entry):
    """C9a: conjunction of positives bidirectionally entails canonical."""
    se = SentenceExtraction.model_validate(entry["extraction"])
    validate_extraction(se)
    suite = compile_sentence_test_suite(se, with_contrastives=False, timeout_s=10)
    ok, reason = check_entailment_monotonicity(se, suite, timeout_s=10)
    assert ok, f"{entry['sentence']!r}: {reason}"


@vampire_required
@pytest.mark.parametrize("entry", CORPUS, ids=_CORPUS_IDS)
def test_contrastive_soundness_on_corpus(entry):
    """C9b: every contrastive in the test suite is provably unsat against
    the positives (under witness axioms)."""
    se = SentenceExtraction.model_validate(entry["extraction"])
    validate_extraction(se)
    suite = compile_sentence_test_suite(se, timeout_s=10)
    ok, reason = check_contrastive_soundness(suite, timeout_s=10)
    assert ok, f"{entry['sentence']!r}: {reason}"


# ── Contract behavior on boundaries ────────────────────────────────────────

def test_contrastive_soundness_empty_contrastives_is_pass():
    """No contrastives = vacuous pass. Recall-only is not a failure."""
    se = SentenceExtraction.model_validate(CORPUS[0]["extraction"])
    suite = TestSuite(extraction=se, positives=[UnitTest(fol="P(a)", kind="positive")],
                      contrastives=[])
    ok, reason = check_contrastive_soundness(suite, timeout_s=5)
    assert ok
    assert reason is None


def test_entailment_monotonicity_empty_positives_is_failure():
    """An empty positives list is a contract violation, not a vacuous pass —
    canonical FOL is non-empty for any valid extraction, so the conjunction
    of zero positives cannot be bidirectionally equivalent to it."""
    se = SentenceExtraction.model_validate(CORPUS[0]["extraction"])
    suite = TestSuite(extraction=se, positives=[], contrastives=[])
    ok, _ = check_entailment_monotonicity(se, suite, timeout_s=5)
    assert not ok


# ── Deliberately-broken compiler: invariant must catch the bug ─────────────

@vampire_required
def test_deliberately_broken_positive_fails_monotonicity(monkeypatch):
    """Inject a subtly-wrong positive into the test suite and confirm C9a
    catches it. The canonical FOL remains correct; only the positives list
    is corrupted. Restores automatically via monkeypatch teardown.

    This is the Phase 4 load-bearing test: if the invariant can't catch a
    real bug, it is not doing any work."""
    se = SentenceExtraction.model_validate(CORPUS[2]["extraction"])  # All dogs are mammals.
    canonical = compile_canonical_fol(se)  # all x.(Dog(x) -> Mammal(x))

    # Monkey-patch compile_sentence_test_suite to return a test suite whose
    # sole positive is the opposite direction (off-by-implication direction).
    # `all x.(Mammal(x) -> Dog(x))` is not bidirectionally equivalent to
    # the canonical under free-domain semantics.
    broken_positive = "all x.(Mammal(x) -> Dog(x))"
    broken_suite = TestSuite(
        extraction=se,
        positives=[UnitTest(fol=broken_positive, kind="positive")],
        contrastives=[],
    )
    ok, reason = check_entailment_monotonicity(se, broken_suite, timeout_s=10)
    assert not ok
    assert "failed" in (reason or "").lower()


@vampire_required
def test_deliberately_broken_contrastive_fails_soundness():
    """A contrastive that is not actually unsat against the positives must
    be caught by C9b. Demonstrates the invariant is load-bearing against
    mechanism failures in the generator."""
    se = SentenceExtraction.model_validate(CORPUS[2]["extraction"])  # All dogs are mammals.
    suite = compile_sentence_test_suite(se, timeout_s=10)
    # Inject a fake contrastive that is satisfiable alongside the positives:
    # just a trivial tautology.
    suite.contrastives.append(UnitTest(
        fol="all x.(Dog(x) -> Dog(x))",
        kind="contrastive",
        mutation_kind="fake_injected_for_test",
    ))
    ok, reason = check_contrastive_soundness(suite, timeout_s=10)
    assert not ok
    assert "fake_injected_for_test" in (reason or "")
