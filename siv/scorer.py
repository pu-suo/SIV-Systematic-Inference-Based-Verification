"""
SIV Score Computation.

SIV Score = F1(recall_rate, precision_rate)
          = 2 * recall * precision / (recall + precision)

Where:
  recall_rate    = (full_passes + sum(partial_credits)) / total_positive_tests
  precision_rate = negative_tests_rejected / total_negative_tests

This module provides:
  - compute_siv_score()  — for a single VerificationResult
  - score_candidates()   — rank a list of candidates for one test suite
  - aggregate_scores()   — problem-level aggregation across multiple problems
"""
from typing import Dict, List, NamedTuple, Optional

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
) -> List[CandidateScore]:
    """
    Verify and score a list of FOL candidates against a single test suite.

    Returns a list of CandidateScore objects sorted by siv_score descending.
    """
    scores: List[CandidateScore] = []
    for cand in candidates:
        result = verify(cand, test_suite, prover_timeout=prover_timeout)
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
) -> Optional[CandidateScore]:
    """Return the highest-scoring candidate, or None if list is empty."""
    scored = score_candidates(candidates, test_suite, prover_timeout)
    return scored[0] if scored else None


# ── Problem-level aggregation ─────────────────────────────────────────────────

class ProblemScore(NamedTuple):
    problem_id: str
    best_siv_score: float
    best_recall: float
    best_precision: float
    num_candidates: int
    best_candidate: str


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
        return {"siv": 0.0, "recall": 0.0, "precision": 0.0}
    n = len(sentence_results)
    return {
        "siv":       sum(r.siv_score      for r in sentence_results) / n,
        "recall":    sum(r.recall_rate    for r in sentence_results) / n,
        "precision": sum(r.precision_rate for r in sentence_results) / n,
    }


def macro_average(problem_scores: List[ProblemScore]) -> Dict[str, float]:
    """
    Compute macro-average SIV, recall, and precision across problems.

    Returns a dict with keys: siv, recall, precision.
    """
    if not problem_scores:
        return {"siv": 0.0, "recall": 0.0, "precision": 0.0}
    n = len(problem_scores)
    return {
        "siv":       sum(p.best_siv_score for p in problem_scores) / n,
        "recall":    sum(p.best_recall    for p in problem_scores) / n,
        "precision": sum(p.best_precision for p in problem_scores) / n,
    }
