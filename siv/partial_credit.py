"""
Partial Credit Module

Extracts the CamelCase component-matching logic from verifier.py so it can be
toggled independently from strict mathematical verification.

Two evaluation modes:
  strict_mode=True  (default) — Tier 1 returns 1.0 (full match) or 0.0 (absent).
                                  No 0.5 partial credit.  Use for leaderboards/papers.
  strict_mode=False            — Tier 1 may return 0.5 for CamelCase components.
                                  Use for training-phase dense reward signals.
"""
import re
from typing import List, Set


def camelcase_components(pred_name: str) -> List[str]:
    """
    Split a CamelCase identifier into its constituent words.

    'CrimsonCar'  → ['Crimson', 'Car']
    'DirectedBy'  → ['Directed', 'By']
    'MovesQuickly'→ ['Moves', 'Quickly']
    """
    parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", pred_name).split()
    return parts


def camelcase_partial_match(
    candidate_preds: Set[str],
    test_preds: Set[str],
) -> float:
    """
    Return a partial credit score for how well candidate_preds cover test_preds.

    Returns:
      1.0  — all test predicates found as standalone in candidate predicates
      0.5  — all test predicates found as CamelCase components (not standalone)
      0.0  — at least one test predicate is absent entirely
    """
    if not test_preds:
        return 1.0

    best_credit = 1.0
    for tp in test_preds:
        if tp in candidate_preds:
            continue  # full match
        # Check if tp is a component of any candidate predicate
        found_as_component = any(
            tp in camelcase_components(cp)
            for cp in candidate_preds
        )
        if found_as_component:
            best_credit = min(best_credit, 0.5)
        else:
            return 0.0  # completely absent

    return best_credit


def tier1_credit(
    candidate_preds: Set[str],
    test_preds: Set[str],
    strict_mode: bool = True,
) -> float:
    """
    Compute Tier-1 vocabulary credit.

    strict_mode=True:  returns 1.0 if all test predicates are present as
                       standalone predicates, otherwise 0.0.
    strict_mode=False: delegates to camelcase_partial_match (0.0 / 0.5 / 1.0).
    """
    if strict_mode:
        # Full standalone match or nothing
        if test_preds.issubset(candidate_preds):
            return 1.0
        return 0.0
    return camelcase_partial_match(candidate_preds, test_preds)
