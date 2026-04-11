"""Tests for siv/verifier.py"""
import pytest
from siv.schema import ProverUnavailableError, UnitTest, TestSuite
from siv.verifier import (
    _tier0_syntax,
    _tier1_vocabulary,
    _tier2_ast,
    verify,
)
import siv.verifier as _verifier_module
from siv.fol_utils import NLTK_AVAILABLE


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
def test_component_match_gives_zero_credit():
    """Tenet 1: CrimsonCar(x) gives ZERO credit for a test expecting Crimson(x)."""
    result = _tier1_vocabulary(
        "all x.(CrimsonCar(x) -> MovesQuickly(x))",
        UnitTest(fol_string="exists x.Crimson(x)", test_type="vocabulary", is_positive=True),
    )
    assert result == (False, 0.0)

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


# ── FIX B1: Prover-unresolved handling ───────────────────────────────────────

@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_unresolved_raises_by_default(monkeypatch):
    """
    verify() with default unresolved_policy="raise" must raise ProverUnavailableError
    when the prover returns None for any test.

    Candidate has both predicates P and Q (Tier 1 passes, credit=1.0),
    but the structural forms differ so Tier 2 returns None, pushing to Tier 3.
    Candidate: exists x.(P(x) & Q(x))  — existential conjunction
    Test:      all x.(P(x) -> Q(x))    — universal conditional (structurally different)
    """
    suite = _make_suite(["all x.(P(x) -> Q(x))"], [])
    candidate = "exists x.(P(x) & Q(x))"
    monkeypatch.setattr(_verifier_module, "_tier3_prover", lambda *a, **kw: None)

    with pytest.raises(ProverUnavailableError):
        verify(candidate, suite)


@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_unresolved_excluded_when_policy_exclude(monkeypatch):
    """
    verify(..., unresolved_policy="exclude") must NOT raise, and must return a
    VerificationResult with unresolved_recall >= 1.

    Same candidate/test pair as the raise test above.
    """
    suite = _make_suite(["all x.(P(x) -> Q(x))"], [])
    candidate = "exists x.(P(x) & Q(x))"
    monkeypatch.setattr(_verifier_module, "_tier3_prover", lambda *a, **kw: None)

    result = verify(candidate, suite, unresolved_policy="exclude")

    assert result.recall_total >= 1
    assert result.recall_passed == 0
    assert result.unresolved_recall >= 1
    assert result.recall_rate == pytest.approx(0.0)


@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_fix_B1_unresolved_precision_excluded(monkeypatch):
    """
    FIX B1: a precision test whose prover call returns None must NOT count as
    a precision pass. The test is excluded from the precision denominator.

    Candidate: exists x.(P(x) & Q(x))
    Negative test: all x.(P(x) -> Q(x))  — predicates present (Tier 1 credit>0),
    structurally different (Tier 2 returns None), so Tier 3 is called.
    """
    suite = _make_suite([], ["all x.(P(x) -> Q(x))"])
    candidate = "exists x.(P(x) & Q(x))"
    monkeypatch.setattr(_verifier_module, "_tier3_prover", lambda *a, **kw: None)

    result = verify(candidate, suite, unresolved_policy="exclude")

    assert result.unresolved_precision >= 1
    # The unresolved test must NOT have generated a precision pass.
    assert result.precision_passed == 0


@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_fix_B1_resolved_tests_unaffected():
    """
    FIX B1: a test that resolves at Tier 2 (structural identity) must still
    count as recall_passed, and unresolved_recall must remain 0.
    """
    fol = "exists x.(Car(x) & Red(x))"
    suite = _make_suite([fol], [])

    result = verify(fol, suite)

    assert result.unresolved_recall == 0
    assert result.recall_passed == 1


@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_fix_B1_mixed_resolved_and_unresolved(monkeypatch):
    """
    FIX B1: with two positive tests — one definitively failed at Tier 1 (absent
    predicate), the other unresolved by the prover — the effective denominator
    drops to 1 (the absent-predicate test counts against, the unresolved is
    excluded), so recall_rate == 0.0 / 1 == 0.0.

    Test 1: exists x.Crimson(x)        — Crimson absent from candidate → Tier 1 skip
    Test 2: all x.(P(x) -> Q(x))       — P and Q present, structurally different → Tier 3
    Candidate: exists x.(P(x) & Q(x))  — contains P and Q but not Crimson
    """
    suite = _make_suite(
        ["exists x.Crimson(x)", "all x.(P(x) -> Q(x))"],
        [],
    )
    candidate = "exists x.(P(x) & Q(x))"
    monkeypatch.setattr(_verifier_module, "_tier3_prover", lambda *a, **kw: None)

    result = verify(candidate, suite, unresolved_policy="exclude")

    assert result.recall_passed == 0
    assert result.unresolved_recall == 1
    # effective_denom = 2 - 1 = 1; recall_rate = 0/1 = 0.0
    assert result.recall_rate == pytest.approx(0.0)


# ── Task 03 Part F: edge-case arithmetic ──────────────────────────────────────

def test_siv_score_recall_only():
    """Task 03 Part F: when recall_total=0 (or all unresolved) but precision passes,
    siv_score should equal precision_rate (previously returned 0.0)."""
    from siv.schema import VerificationResult
    r = VerificationResult(
        candidate_fol="P(a)",
        syntax_valid=True,
        recall_passed=0,
        recall_total=0,
        precision_passed=3,
        precision_total=3,
        tier1_skips=0,
        tier2_skips=0,
        prover_calls=0,
    )
    assert r.siv_score == pytest.approx(1.0), (
        f"Precision-only case: expected siv_score=1.0; got {r.siv_score}"
    )


def test_siv_score_precision_only():
    """Task 03 Part F: symmetric — when precision_total=0 but recall passes,
    siv_score should equal recall_rate."""
    from siv.schema import VerificationResult
    r = VerificationResult(
        candidate_fol="P(a)",
        syntax_valid=True,
        recall_passed=3,
        recall_total=3,
        precision_passed=0,
        precision_total=0,
        tier1_skips=0,
        tier2_skips=0,
        prover_calls=0,
    )
    assert r.siv_score == pytest.approx(1.0), (
        f"Recall-only case: expected siv_score=1.0; got {r.siv_score}"
    )


def test_tier2_existential_conjunct_containment():
    from siv.verifier import verify
    from siv.schema import TestSuite, UnitTest
    suite = TestSuite(
        problem_id="tier2_ext",
        positive_tests=[
            UnitTest(fol_string="exists x.Tall(x)", test_type="vocabulary", is_positive=True),
        ],
        negative_tests=[],
    )
    candidate = "exists x.(Tree(x) & Tall(x))"
    result = verify(candidate, suite, unresolved_policy="exclude")
    assert result.recall_passed == 1
    assert result.prover_calls == 0
