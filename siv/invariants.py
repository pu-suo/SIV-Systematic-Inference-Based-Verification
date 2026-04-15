"""
Soundness invariants (SIV.md §8, C9a, C9b).

Two CI-level checks that run on every compiled test suite and fail the build
on violation.

- ``check_entailment_monotonicity`` (C9a): the conjunction of a test suite's
  positives is bidirectionally equivalent to ``compile_canonical_fol(extraction)``.
  Runs WITHOUT witness axioms — pure compiler-path equivalence.
- ``check_contrastive_soundness`` (C9b): every contrastive in the test suite
  is provably inconsistent with the conjunction of the positives, under the
  §6.5 witness axioms.

Timeout and unknown are failures, not passes. There is no soundness bypass.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from siv.contrastive_generator import derive_witness_axioms
from siv.schema import SentenceExtraction, TestSuite
from siv.vampire_interface import vampire_check


def check_entailment_monotonicity(
    extraction: SentenceExtraction,
    test_suite: TestSuite,
    timeout_s: int = 10,
) -> Tuple[bool, Optional[str]]:
    """C9a. With ``P`` = conjunction of positives and ``Q`` = canonical FOL,
    Vampire-check both ``P ⊨ Q`` and ``Q ⊨ P`` without witness axioms.

    Returns ``(True, None)`` iff both directions proved.
    Returns ``(False, reason)`` on the first failure (sat / timeout / unknown).
    """
    from siv.compiler import compile_canonical_fol

    if not test_suite.positives:
        return False, "test suite has no positives"

    p_fol = _conjunction([t.fol for t in test_suite.positives])
    q_fol = compile_canonical_fol(extraction)

    v_pq = vampire_check(p_fol, q_fol, check="entails", timeout=timeout_s)
    if v_pq != "unsat":
        return False, f"P ⊨ Q failed: verdict={v_pq}"

    v_qp = vampire_check(q_fol, p_fol, check="entails", timeout=timeout_s)
    if v_qp != "unsat":
        return False, f"Q ⊨ P failed: verdict={v_qp}"

    return True, None


def check_contrastive_soundness(
    test_suite: TestSuite,
    timeout_s: int = 10,
) -> Tuple[bool, Optional[str]]:
    """C9b. With ``P`` = conjunction of positives, for each contrastive ``C``,
    Vampire-check that ``(P ∧ C)`` is ``unsat`` under §6.5 witness axioms.

    Returns ``(True, None)`` iff every contrastive is unsat against the positives.
    Returns ``(False, reason)`` on the first contrastive that is sat / timeout /
    unknown.
    """
    if not test_suite.contrastives:
        return True, None

    if not test_suite.positives:
        return False, "test suite has contrastives but no positives"

    p_fol = _conjunction([t.fol for t in test_suite.positives])
    witnesses = derive_witness_axioms(test_suite.extraction)

    for i, c in enumerate(test_suite.contrastives):
        verdict = vampire_check(
            p_fol, c.fol, check="unsat", timeout=timeout_s, axioms=witnesses,
        )
        if verdict != "unsat":
            return False, (
                f"contrastive {i} ({c.mutation_kind}) not unsat against positives: "
                f"verdict={verdict}; fol={c.fol!r}"
            )

    return True, None


def _conjunction(fols: List[str]) -> str:
    if len(fols) == 1:
        return fols[0]
    return "(" + " & ".join(f"({f})" for f in fols) + ")"
