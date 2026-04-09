"""Tests for siv/scorer.py"""
import pytest
from siv.schema import TestSuite, UnitTest, VerificationResult
from siv.scorer import (
    compute_siv_score,
    score_candidates,
    best_candidate,
    aggregate_scores,
    macro_average,
    CandidateScore,
    ProblemScore,
)
from siv.fol_utils import NLTK_AVAILABLE


def _make_result(recall_passed, recall_total, precision_passed, precision_total,
                 syntax_valid=True):
    return VerificationResult(
        candidate_fol="x",
        syntax_valid=syntax_valid,
        recall_passed=recall_passed,
        recall_total=recall_total,
        precision_passed=precision_passed,
        precision_total=precision_total,
        tier1_skips=0,
        tier2_skips=0,
        prover_calls=0,
    )


def _make_suite(pos_fols, neg_fols, problem_id="test"):
    pos = [UnitTest(fol_string=f, test_type="vocabulary", is_positive=True)
           for f in pos_fols]
    neg = [UnitTest(fol_string=f, test_type="contrastive", is_positive=False)
           for f in neg_fols]
    return TestSuite(problem_id=problem_id, positive_tests=pos, negative_tests=neg)


# ── compute_siv_score ─────────────────────────────────────────────────────────

def test_compute_siv_perfect():
    r = _make_result(4, 4, 2, 2)
    assert compute_siv_score(r) == pytest.approx(1.0)

def test_compute_siv_zero():
    r = _make_result(0, 4, 0, 4, syntax_valid=False)
    assert compute_siv_score(r) == pytest.approx(0.0)

def test_compute_siv_partial():
    r = _make_result(3, 4, 2, 2)
    expected = 2 * 0.75 * 1.0 / (0.75 + 1.0)
    assert compute_siv_score(r) == pytest.approx(expected)


# ── score_candidates ──────────────────────────────────────────────────────────

@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_score_candidates_sorted():
    """score_candidates should return results sorted best-first."""
    suite = _make_suite(
        ["exists x.Car(x)", "exists x.Crimson(x)"],
        ["exists x.Blue(x)"],
    )
    candidates = [
        "exists x.(Car(x) & Crimson(x))",  # has both predicates → higher score
        "exists x.Car(x)",                  # missing Crimson → lower score
    ]
    scores = score_candidates(candidates, suite, unresolved_policy="exclude")
    assert len(scores) == 2
    assert scores[0].siv_score >= scores[1].siv_score


@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_best_candidate_returns_first():
    suite = _make_suite(["exists x.Car(x)"], [])
    candidates = ["exists x.Car(x)", "exists x.Dog(x)"]
    best = best_candidate(candidates, suite, unresolved_policy="exclude")
    assert best is not None
    assert isinstance(best, CandidateScore)


def test_best_candidate_empty():
    suite = _make_suite([], [])
    assert best_candidate([], suite) is None


# ── aggregate_scores ──────────────────────────────────────────────────────────

def test_aggregate_scores_sorted():
    from siv.schema import VerificationResult

    def _cs(siv, recall, precision, fol="x"):
        r = _make_result(
            int(recall * 4), 4, int(precision * 4), 4
        )
        return CandidateScore(
            candidate_fol=fol,
            siv_score=r.siv_score,
            recall_rate=r.recall_rate,
            precision_rate=r.precision_rate,
            syntax_valid=True,
            result=r,
        )

    problem_results = {
        "p1": [_cs(0.9, 0.75, 1.0)],
        "p2": [_cs(0.5, 0.5, 0.5)],
    }
    agg = aggregate_scores(problem_results)
    assert len(agg) == 2
    assert agg[0].best_siv_score >= agg[1].best_siv_score

def test_aggregate_empty_problem():
    agg = aggregate_scores({"p1": []})
    assert agg[0].best_siv_score == 0.0
    assert agg[0].num_candidates == 0


# ── macro_average ─────────────────────────────────────────────────────────────

def test_macro_average_empty():
    avg = macro_average([])
    assert avg["siv"] == 0.0

def test_macro_average_single():
    ps = ProblemScore(
        problem_id="p1",
        best_siv_score=0.8,
        best_recall=0.7,
        best_precision=0.9,
        num_candidates=3,
        best_candidate="x",
    )
    avg = macro_average([ps])
    assert avg["siv"] == pytest.approx(0.8)
    assert avg["recall"] == pytest.approx(0.7)
    assert avg["precision"] == pytest.approx(0.9)

def test_macro_average_multiple():
    scores = [
        ProblemScore("p1", 0.8, 0.8, 0.8, 1, "x"),
        ProblemScore("p2", 0.6, 0.6, 0.6, 1, "x"),
    ]
    avg = macro_average(scores)
    assert avg["siv"] == pytest.approx(0.7)
