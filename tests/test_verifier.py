"""Tests for siv/verifier.py"""
import pytest
from siv.schema import UnitTest, TestSuite
from siv.verifier import (
    _tier0_syntax,
    _tier1_vocabulary,
    _tier2_ast,
    verify,
    _camelcase_components,
    _extract_predicates_from_fol,
)
from siv.fol_utils import NLTK_AVAILABLE


# ── _camelcase_components ─────────────────────────────────────────────────────

def test_camel_split_two():
    assert _camelcase_components("CrimsonCar") == ["Crimson", "Car"]

def test_camel_split_three():
    assert _camelcase_components("MovesQuickly") == ["Moves", "Quickly"]

def test_camel_single():
    comps = _camelcase_components("Tall")
    assert comps == ["Tall"]


# ── _tier0_syntax ─────────────────────────────────────────────────────────────

@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_tier0_valid():
    assert _tier0_syntax("exists x.(Car(x) & Crimson(x))")

@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_tier0_invalid():
    assert not _tier0_syntax("exists x Car(x")


# ── _tier1_vocabulary ─────────────────────────────────────────────────────────

@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_full_credit_standalone():
    """Spec: Crimson is present as standalone predicate → full credit."""
    result = _tier1_vocabulary(
        "exists x.(Car(x) & Crimson(x) & Running(x))",
        UnitTest(fol_string="exists x.Crimson(x)", test_type="vocabulary", is_positive=True),
    )
    assert result == (True, 1.0)

@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_partial_credit_for_component():
    """Spec: CrimsonCar(x) should get 0.5 credit for test expecting Crimson(x)."""
    result = _tier1_vocabulary(
        "all x.(CrimsonCar(x) -> MovesQuickly(x))",
        UnitTest(fol_string="exists x.Crimson(x)", test_type="vocabulary", is_positive=True),
    )
    assert result[1] == pytest.approx(0.5)

@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_zero_credit_absent_predicate():
    """Predicate completely absent → (False, 0.0)."""
    result = _tier1_vocabulary(
        "exists x.Car(x)",
        UnitTest(fol_string="exists x.Crimson(x)", test_type="vocabulary", is_positive=True),
    )
    assert result == (False, 0.0)

@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_full_credit_decomposed():
    """Spec: Car(x) & Crimson(x) → full credit for Crimson test."""
    result = _tier1_vocabulary(
        "exists x.(Car(x) & Crimson(x) & Running(x))",
        UnitTest(fol_string="exists x.Crimson(x)", test_type="vocabulary", is_positive=True),
    )
    assert result[1] == pytest.approx(1.0)


# ── _tier2_ast ────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_tier2_identity():
    from siv.fol_utils import parse_fol
    expr = parse_fol("exists x.(Car(x) & Red(x))")
    result = _tier2_ast(expr, expr)
    assert result is True

@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_tier2_conjunct_found():
    from siv.fol_utils import parse_fol
    candidate = parse_fol("exists x.(Car(x) & Red(x))")
    test = parse_fol("exists x.Red(x)")
    result = _tier2_ast(candidate, test)
    # May return True or None depending on simplification
    assert result in (True, None)

@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_tier2_returns_none_for_complex():
    from siv.fol_utils import parse_fol
    candidate = parse_fol("all x.(Dog(x) -> Animal(x))")
    test = parse_fol("all x.(Dog(x) -> Mammal(x))")
    result = _tier2_ast(candidate, test)
    assert result in (None, False)


# ── verify (integration) ──────────────────────────────────────────────────────

def _make_suite(pos_fols, neg_fols, problem_id="test"):
    pos = [UnitTest(fol_string=f, test_type="vocabulary", is_positive=True)
           for f in pos_fols]
    neg = [UnitTest(fol_string=f, test_type="contrastive", is_positive=False)
           for f in neg_fols]
    return TestSuite(problem_id=problem_id, positive_tests=pos, negative_tests=neg)


@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_verify_invalid_syntax():
    suite = _make_suite(["exists x.Car(x)"], [])
    result = verify("exists x Car(x", suite)
    assert result.syntax_valid is False
    assert result.siv_score == pytest.approx(0.0)


@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_verify_empty_suite():
    suite = _make_suite([], [])
    result = verify("exists x.Car(x)", suite)
    assert result.syntax_valid is True
    assert result.siv_score == pytest.approx(0.0)


@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_verify_precision_pass_on_absent_pred():
    """Negative test with predicate absent from candidate → precision passes."""
    suite = _make_suite(
        pos_fols=["exists x.Car(x)"],
        neg_fols=["exists x.Crimson(x)"],
    )
    result = verify("exists x.Car(x)", suite)
    assert result.precision_passed == 1
    assert result.precision_total == 1


@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_verify_recall_vocab_fail():
    """Required predicate missing → recall fails for that test."""
    suite = _make_suite(["exists x.Crimson(x)"], [])
    result = verify("exists x.Car(x)", suite)
    assert result.recall_passed == 0
    assert result.tier1_skips >= 1
