"""
Tests for siv/invariants.py — one test per invariant, covering both
passing and failing cases, plus the aggregate check_all_invariants.
"""
import pytest
from unittest.mock import MagicMock, patch

from siv.schema import (
    Entity, EntityType, Fact, MacroTemplate, Constant, SentenceExtraction,
)
from siv.invariants import (
    check_syntactic_validity,
    check_vocabulary_containment,
    check_constant_containment,
    check_quantifier_correspondence,
    check_self_consistency,
    check_all_invariants,
)


# ── Shared fixtures ───────────────────────────────────────────────────────────

def _make_existential_extraction() -> SentenceExtraction:
    """'Some dogs are brown.' — 0 UNIVERSAL entities, no constants."""
    return SentenceExtraction(
        nl="Some dogs are brown.",
        entities=[Entity(id="e1", surface="dogs", entity_type=EntityType.EXISTENTIAL)],
        facts=[
            Fact(pred="dogs", args=["e1"], negated=False),
            Fact(pred="brown", args=["e1"], negated=False),
        ],
        macro_template=MacroTemplate.TYPE_I,
    )


def _make_constant_extraction() -> SentenceExtraction:
    """'Rex is a dog.' — named constant, no quantified entities."""
    return SentenceExtraction(
        nl="Rex is a dog.",
        entities=[],
        facts=[Fact(pred="dog", args=["rex"], negated=False)],
        macro_template=MacroTemplate.GROUND_POSITIVE,
        constants=[Constant(id="rex", surface="Rex")],
    )


def _make_universal_extraction() -> SentenceExtraction:
    """'All dogs are animals.' — 1 UNIVERSAL entity."""
    return SentenceExtraction(
        nl="All dogs are animals.",
        entities=[
            Entity(id="e1", surface="dogs", entity_type=EntityType.UNIVERSAL),
            Entity(id="e2", surface="animals", entity_type=EntityType.EXISTENTIAL),
        ],
        facts=[Fact(pred="are", args=["e1", "e2"], negated=False)],
        macro_template=MacroTemplate.TYPE_A,
    )


# ── Invariant 1: Syntactic Validity ──────────────────────────────────────────

def test_invariant_1_syntactic_validity_passes_on_valid_fol():
    passed, reason = check_syntactic_validity("exists x.Dog(x)")
    assert passed is True
    assert reason is None


def test_invariant_1_syntactic_validity_fails_on_garbage():
    passed, reason = check_syntactic_validity("not valid fol @@@ ###")
    assert passed is False
    assert reason is not None
    assert "not valid NLTK FOL" in reason


# ── Invariant 2: Vocabulary Containment ──────────────────────────────────────

def test_invariant_2_vocabulary_containment_passes_on_canonical():
    extraction = _make_existential_extraction()
    fol = "exists x.(Dogs(x) & Brown(x))"
    passed, reason = check_vocabulary_containment(fol, extraction)
    assert passed is True
    assert reason is None


def test_invariant_2_vocabulary_containment_fails_on_invented_predicate():
    extraction = _make_existential_extraction()
    fol = "exists x.(Dogs(x) & Hairy(x))"  # "Hairy" not in extraction
    passed, reason = check_vocabulary_containment(fol, extraction)
    assert passed is False
    assert reason is not None
    assert "Hairy" in reason


# ── Invariant 3: Constant Containment ────────────────────────────────────────

def test_invariant_3_constant_containment_passes():
    extraction = _make_constant_extraction()
    fol = "Dog(rex)"
    passed, reason = check_constant_containment(fol, extraction)
    assert passed is True
    assert reason is None


def test_invariant_3_constant_containment_fails_on_invented_constant():
    extraction = _make_constant_extraction()
    fol = "Dog(fluffy)"  # "fluffy" not in constants
    passed, reason = check_constant_containment(fol, extraction)
    assert passed is False
    assert reason is not None
    assert "fluffy" in reason


# ── Invariant 4: Quantifier Correspondence ────────────────────────────────────

def test_invariant_4_quantifier_correspondence_passes_on_matching_counts():
    extraction = _make_universal_extraction()  # 1 UNIVERSAL entity → expects 1 'all'
    fol = "(exists x.Dogs(x)) & all x.(Dogs(x) -> exists y.(Animals(y) & Are(x,y)))"
    passed, reason = check_quantifier_correspondence(fol, extraction)
    assert passed is True
    assert reason is None


def test_invariant_4_quantifier_correspondence_fails_on_extra_universal():
    extraction = _make_existential_extraction()  # 0 UNIVERSAL entities → expects 0 'all'
    fol = "all x.(Dogs(x) -> Brown(x))"  # unexpected 'all'
    passed, reason = check_quantifier_correspondence(fol, extraction)
    assert passed is False
    assert reason is not None
    assert "mismatch" in reason


def test_invariant_4_quantifier_correspondence_allows_extra_existentials():
    extraction = _make_universal_extraction()  # 1 UNIVERSAL → expects 1 'all'
    # One 'all', multiple 'exists' — existentials are unconstrained
    fol = "(exists x.Dogs(x)) & all x.(Dogs(x) -> exists y.(Animals(y) & exists z.Are(x,z)))"
    passed, reason = check_quantifier_correspondence(fol, extraction)
    assert passed is True
    assert reason is None


# ── Invariant 5: Self-Consistency ─────────────────────────────────────────────

def test_invariant_5_self_consistency_passes_on_canonical_fol():
    extraction = _make_existential_extraction()
    fol = "exists x.(Dogs(x) & Brown(x))"

    from siv.schema import TestSuite
    mock_suite = MagicMock(spec=TestSuite)
    mock_suite.has_violations = False
    mock_result = MagicMock()
    mock_result.recall_rate = 1.0

    with patch("siv.invariants.compile_sentence_test_suite", return_value=mock_suite), \
         patch("siv.invariants.verify", return_value=mock_result):
        passed, reason = check_self_consistency(fol, extraction)

    assert passed is True
    assert reason is None


def test_invariant_5_self_consistency_fails_on_wrong_fol():
    extraction = _make_existential_extraction()
    fol = "all x.(Cats(x) -> Purple(x))"  # unrelated FOL

    from siv.schema import TestSuite
    mock_suite = MagicMock(spec=TestSuite)
    mock_suite.has_violations = False
    mock_result = MagicMock()
    mock_result.recall_rate = 0.1  # Below 0.8 threshold

    with patch("siv.invariants.compile_sentence_test_suite", return_value=mock_suite), \
         patch("siv.invariants.verify", return_value=mock_result):
        passed, reason = check_self_consistency(fol, extraction)

    assert passed is False
    assert reason is not None
    assert "threshold" in reason


# ── Aggregate: check_all_invariants ──────────────────────────────────────────

def test_check_all_invariants_returns_all_failures():
    extraction = _make_existential_extraction()  # 0 UNIVERSAL entities
    # This FOL:
    #   - Syntactically valid
    #   - Contains "Hairy" not in extraction → vocabulary failure
    #   - Has 1 'all' but 0 UNIVERSAL entities → quantifier failure
    #   - Self-consistency: will also fail with low recall
    fol = "all x.(Hairy(x) -> Dogs(x))"

    from siv.schema import TestSuite
    mock_suite = MagicMock(spec=TestSuite)
    mock_suite.has_violations = False
    mock_result = MagicMock()
    mock_result.recall_rate = 0.0

    with patch("siv.invariants.compile_sentence_test_suite", return_value=mock_suite), \
         patch("siv.invariants.verify", return_value=mock_result):
        failures = check_all_invariants(fol, extraction)

    # At minimum: vocabulary failure + quantifier failure + self-consistency failure
    assert len(failures) >= 2
    assert any("Hairy" in f for f in failures), "Expected vocabulary failure for 'Hairy'"
    assert any("mismatch" in f for f in failures), "Expected quantifier mismatch failure"
