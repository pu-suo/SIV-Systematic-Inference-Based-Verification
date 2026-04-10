"""
SIV Score Computation.

SIV Score = F1(recall_rate, precision_rate)
          = 2 * recall * precision / (recall + precision)

Where:
  recall_rate    = recall_passed / effective_positive_tests
  precision_rate = negative_tests_rejected / total_negative_tests

This module provides:
  - compute_siv_score()  — for a single VerificationResult
  - score_candidates()   — rank a list of candidates for one test suite
  - aggregate_scores()   — problem-level aggregation across multiple problems
"""
from typing import Dict, List, Literal, NamedTuple, Optional

from siv.schema import TestSuite, VerificationResult
from siv.verifier import verify


# ── Per-candidate scoring ──────────────────────────────────────────────────────

def compute_siv_score(result: VerificationResult) -> float:
    """
    Compute the SIV score (F1) for a single VerificationResult.

    Returns a float in [0.0, 1.0].
    Delegates to the property on VerificationResult, exposed here for
    a consistent import surface.
    """
    return result.siv_score


# ── Batch candidate scoring ────────────────────────────────────────────────────

class CandidateScore(NamedTuple):
    candidate_fol: str
    siv_score: float
    recall_rate: float
    precision_rate: float
    syntax_valid: bool
    result: VerificationResult


def score_candidates(
    candidates: List[str],
    test_suite: TestSuite,
    prover_timeout: int = 5,
    unresolved_policy: Literal["raise", "exclude"] = "raise",
) -> List[CandidateScore]:
    """
    Verify and score a list of FOL candidates against a single test suite.

    Returns a list of CandidateScore objects sorted by siv_score descending.
    """
    scores: List[CandidateScore] = []
    for cand in candidates:
        result = verify(cand, test_suite, prover_timeout=prover_timeout,
                        unresolved_policy=unresolved_policy)
        scores.append(CandidateScore(
            candidate_fol=cand,
            siv_score=result.siv_score,
            recall_rate=result.recall_rate,
            precision_rate=result.precision_rate,
            syntax_valid=result.syntax_valid,
            result=result,
        ))
    return sorted(scores, key=lambda s: s.siv_score, reverse=True)


def best_candidate(
    candidates: List[str],
    test_suite: TestSuite,
    prover_timeout: int = 5,
    unresolved_policy: Literal["raise", "exclude"] = "raise",
) -> Optional[CandidateScore]:
    """Return the highest-scoring candidate, or None if list is empty."""
    scored = score_candidates(candidates, test_suite, prover_timeout, unresolved_policy)
    return scored[0] if scored else None


# ── Problem-level aggregation ─────────────────────────────────────────────────

class ProblemScore(NamedTuple):
    problem_id: str
    best_siv_score: float
    best_recall: float
    best_precision: float
    num_candidates: int
    best_candidate: str
    # FIX C1: True when the best candidate's result has extraction_invalid=True.
    extraction_invalid: bool = False


def aggregate_scores(
    problem_results: Dict[str, List[CandidateScore]],
) -> List[ProblemScore]:
    """
    Aggregate per-candidate scores into per-problem summary statistics.

    Args:
        problem_results: mapping from problem_id → list of CandidateScore

    Returns:
        List of ProblemScore sorted by best_siv_score descending.
    """
    out: List[ProblemScore] = []
    for problem_id, scores in problem_results.items():
        if not scores:
            out.append(ProblemScore(
                problem_id=problem_id,
                best_siv_score=0.0,
                best_recall=0.0,
                best_precision=0.0,
                num_candidates=0,
                best_candidate="",
            ))
            continue
        best = max(scores, key=lambda s: s.siv_score)
        out.append(ProblemScore(
            problem_id=problem_id,
            best_siv_score=best.siv_score,
            best_recall=best.recall_rate,
            best_precision=best.precision_rate,
            num_candidates=len(scores),
            best_candidate=best.candidate_fol,
            # FIX C1: propagate extraction_invalid from the best result.
            extraction_invalid=best.result.extraction_invalid,
        ))
    return sorted(out, key=lambda p: p.best_siv_score, reverse=True)


def aggregate_sentence_scores(
    sentence_results: List[VerificationResult],
) -> Dict[str, float]:
    """
    Macro-average SIV, recall, and precision across per-sentence VerificationResults.

    Use this for sentence-level evaluation where each premise is scored against
    its own test suite and the problem score is the mean of per-sentence scores.

    Returns a dict with keys: siv, recall, precision.
    """
    if not sentence_results:
        return {"siv": 0.0, "recall": 0.0, "precision": 0.0, "num_invalid": 0}
    n = len(sentence_results)
    # FIX C1: invalid results contribute 0.0 to the average (siv_score returns
    # 0.0 when extraction_invalid=True) and are counted in num_invalid.
    # They are included in the denominator so they drag down the problem score.
    return {
        "siv":         sum(r.siv_score      for r in sentence_results) / n,
        "recall":      sum(r.recall_rate    for r in sentence_results) / n,
        "precision":   sum(r.precision_rate for r in sentence_results) / n,
        "num_invalid": sum(1 for r in sentence_results if r.extraction_invalid),
    }


def aggregate_per_candidate(
    candidate_results: Dict[str, List[VerificationResult]],
) -> Dict[str, Dict[str, float]]:
    """
    Aggregate per-premise VerificationResults for each candidate name.

    Args:
        candidate_results: mapping from candidate_name → list of VerificationResult
                           (one per premise, in order)

    Returns:
        Mapping from candidate_name → aggregate dict with keys:
        siv, recall, precision, num_invalid (via aggregate_sentence_scores).
    """
    return {
        name: aggregate_sentence_scores(results)
        for name, results in candidate_results.items()
    }


def macro_average(problem_scores: List[ProblemScore]) -> Dict[str, float]:
    """
    Compute macro-average SIV, recall, and precision across problems.

    Returns a dict with keys: siv, recall, precision.
    """
    if not problem_scores:
        return {"siv": 0.0, "recall": 0.0, "precision": 0.0, "num_invalid_problems": 0}
    n = len(problem_scores)
    # FIX C1: invalid problems contribute best_siv_score=0.0 (already enforced
    # by VerificationResult.siv_score) and are counted in num_invalid_problems.
    return {
        "siv":                  sum(p.best_siv_score for p in problem_scores) / n,
        "recall":               sum(p.best_recall    for p in problem_scores) / n,
        "precision":            sum(p.best_precision for p in problem_scores) / n,
        "num_invalid_problems": sum(1 for p in problem_scores if p.extraction_invalid),
    }
