"""
Tiered Verification Pipeline with Partial Credit.

Tier 0: Syntax check  — does the candidate parse as valid FOL?
Tier 1: Vocabulary    — CamelCase-aware predicate presence check with partial credit
Tier 2: AST patterns  — lightweight structural check (no prover)
Tier 3: Vampire       — full theorem proving (only for unresolved tests)

Partial credit system (applied at Tier 1 for recall tests):
  Full match   (predicate present as standalone):     1.0
  Partial match (predicate is a CamelCase component): 0.5
  No match     (predicate absent entirely):           0.0

A test resolved at Tier 1 with full credit counts as recall_passed.
A test resolved at Tier 1 with partial credit is recorded in partial_credits
but does NOT increment recall_passed.
A test definitively failed at Tier 1 (credit = 0.0) is skipped (no prover call).
"""
from typing import Dict, Optional, Set, Tuple

from siv.fol_utils import (
    NLTK_AVAILABLE, extract_predicates, is_valid_fol, parse_fol,
)
from siv.partial_credit import tier1_credit
from siv.schema import ProverUnavailableError, TestSuite, UnitTest, VerificationResult
from siv.vampire_interface import check_entailment


# ── Predicate helpers ─────────────────────────────────────────────────────────

def _extract_predicates_from_fol(fol_string: str) -> Set[str]:
    """Return all predicate names from *fol_string*."""
    return extract_predicates(fol_string)


# ── Tier 0: Syntax ────────────────────────────────────────────────────────────

def _tier0_syntax(candidate: str) -> bool:
    """Return True if *candidate* parses as valid NLTK FOL."""
    return is_valid_fol(candidate)


# ── Tier 1: Vocabulary ────────────────────────────────────────────────────────

def _tier1_vocabulary(
    candidate: str,
    test: UnitTest,
    strict_mode: bool = False,
) -> Tuple[bool, float]:
    """
    CamelCase-aware vocabulary check.

    strict_mode=False (default for backward compat):
      (True,  1.0) → all predicates found as standalone → full credit
      (False, 0.5) → predicate is a CamelCase component → partial credit
      (False, 0.0) → predicate absent entirely → definitive fail

    strict_mode=True:
      (True,  1.0) → all predicates found as standalone
      (False, 0.0) → any predicate absent or only a component → fail

    For NEGATIVE tests the semantics are inverted by the caller.
    """
    test_preds      = _extract_predicates_from_fol(test.fol_string)
    candidate_preds = _extract_predicates_from_fol(candidate)

    if not test_preds:
        return (True, 1.0)

    credit = tier1_credit(candidate_preds, test_preds, strict_mode=strict_mode)
    if credit >= 1.0:
        return (True, 1.0)
    if credit > 0.0:
        return (False, credit)
    return (False, 0.0)


# ── Tier 2: AST pattern matching ──────────────────────────────────────────────

def _tier2_ast(candidate_expr, test_expr) -> Optional[bool]:
    """
    Lightweight AST-based entailment check using NLTK expressions.

    Handles simple patterns without calling the theorem prover:
      1. Syntactic identity (alpha-equivalence via NLTK's __eq__)
      2. Test is a simple atom P(c) and candidate contains it as a conjunct
      3. Test is exists x.P(x) and candidate is P(c) or contains P(x)

    Returns True/False if resolved, None if Tier 3 is needed.
    """
    if not NLTK_AVAILABLE:
        return None

    try:
        from nltk.sem.logic import (
            ApplicationExpression, AndExpression,
            ExistsExpression, AllExpression,
        )

        # 1. Structural equality
        if candidate_expr == test_expr:
            return True

        # 2. Test is a simple atom → check if it appears as a conjunct in candidate
        def collect_conjuncts(expr):
            """Flatten nested AndExpressions into a list of conjuncts."""
            if isinstance(expr, AndExpression):
                return collect_conjuncts(expr.first) + collect_conjuncts(expr.second)
            return [expr]

        candidate_conjuncts = collect_conjuncts(candidate_expr)
        if test_expr in candidate_conjuncts:
            return True

        # 3. Test is exists x.P(x) → check if candidate contains P(_) anywhere
        if isinstance(test_expr, ExistsExpression):
            inner = test_expr.term
            if inner in candidate_conjuncts:
                return True
            # Check exists-body against candidate conjuncts (variable renaming)
            for conj in candidate_conjuncts:
                if isinstance(conj, ExistsExpression) and conj.term == inner:
                    return True

        # 4. Test is all x.(P(x) -> Q(x)) — check candidate structural match
        if isinstance(test_expr, AllExpression):
            if candidate_expr == test_expr:
                return True

    except Exception:
        pass

    return None  # Needs Tier 3


# ── Tier 3: Vampire ───────────────────────────────────────────────────────────

def _tier3_prover(candidate: str, test_fol: str, timeout: int = 5) -> Optional[bool]:
    """
    Call Vampire to check candidate ⊢ test_fol.
    Returns True/False/None (None = timeout or unavailable).
    """
    return check_entailment(candidate, test_fol, timeout=timeout)


# ── Full verification pipeline ────────────────────────────────────────────────

def verify(
    candidate_fol: str,
    test_suite: TestSuite,
    prover_timeout: int = 5,
    strict_mode: bool = False,
) -> VerificationResult:
    """
    Run the full tiered verification of one candidate against a test suite.

    For POSITIVE tests: candidate must entail → counted in recall.
    For NEGATIVE tests: candidate must NOT entail → counted in precision.

    strict_mode=False (default): CamelCase component matching gives 0.5 partial
                                  credit at Tier 1 (dense reward signal for training).
    strict_mode=True:             Tier 1 returns only 1.0 or 0.0 — no partial credit
                                  (strict mathematical verification for leaderboards).
    """
    # FIX C1: schema violations short-circuit the verifier. No prover calls
    # are made; the result is marked extraction_invalid=True and siv_score=0.0.
    # Placed before Tier 0 so no work is done on an invalid extraction.
    if test_suite.has_violations:
        return VerificationResult(
            candidate_fol=candidate_fol,
            syntax_valid=_tier0_syntax(candidate_fol),
            recall_passed=0,
            recall_total=len(test_suite.positive_tests),
            precision_passed=0,
            precision_total=len(test_suite.negative_tests),
            tier1_skips=0,
            tier2_skips=0,
            prover_calls=0,
            extraction_invalid=True,
            schema_violations=list(test_suite.violations),
        )

    # ── Tier 0: syntax ──────────────────────────────────────────────────────
    syntax_valid = _tier0_syntax(candidate_fol)
    n_pos = len(test_suite.positive_tests)
    n_neg = len(test_suite.negative_tests)

    if not syntax_valid:
        return VerificationResult(
            candidate_fol=candidate_fol,
            syntax_valid=False,
            recall_passed=0,
            recall_total=n_pos,
            precision_passed=0,
            precision_total=n_neg,
            tier1_skips=n_pos + n_neg,
            tier2_skips=0,
            prover_calls=0,
        )

    recall_passed    = 0
    precision_passed = 0
    tier1_skips      = 0
    tier2_skips      = 0
    prover_calls     = 0
    partial_credits: Dict[str, float] = {}
    # FIX B1: track tests that could not be resolved by the prover.
    unresolved_recall    = 0
    unresolved_precision = 0

    candidate_expr = parse_fol(candidate_fol) if NLTK_AVAILABLE else None

    # ── RECALL: positive tests ───────────────────────────────────────────────
    for i, test in enumerate(test_suite.positive_tests):
        definitive, credit = _tier1_vocabulary(candidate_fol, test, strict_mode=strict_mode)

        if credit == 0.0:
            # Predicate completely absent → definitive fail
            tier1_skips += 1
            continue

        if definitive and credit == 1.0:
            # Full vocabulary match → still need structural / prover check
            # Try Tier 2 first
            test_expr = parse_fol(test.fol_string) if NLTK_AVAILABLE else None
            if candidate_expr is not None and test_expr is not None:
                t2 = _tier2_ast(candidate_expr, test_expr)
                if t2 is True:
                    recall_passed += 1
                    tier2_skips += 1
                    continue
                elif t2 is False:
                    tier2_skips += 1
                    continue

            # Tier 3
            prover_calls += 1
            result = _tier3_prover(candidate_fol, test.fol_string, prover_timeout)
            if result is True:
                recall_passed += 1
            elif result is None:
                # FIX B1: prover unresolved → no credit, no partial, no lexical
                # fallback. Excluded from denominator via unresolved_recall.
                unresolved_recall += 1
            # result is False → fall through, no increment, no exclusion
        else:
            # Partial vocabulary match (credit = 0.5)
            # Try Tier 2 / Tier 3 to upgrade
            test_expr = parse_fol(test.fol_string) if NLTK_AVAILABLE else None
            if candidate_expr is not None and test_expr is not None:
                t2 = _tier2_ast(candidate_expr, test_expr)
                if t2 is True:
                    recall_passed += 1
                    tier2_skips += 1
                    continue
                elif t2 is False:
                    partial_credits[f"pos_{i}"] = credit
                    tier2_skips += 1
                    continue

            prover_calls += 1
            result = _tier3_prover(candidate_fol, test.fol_string, prover_timeout)
            if result is True:
                recall_passed += 1
            elif result is None:
                # FIX B1: prover unresolved → no partial credit fallback.
                # Excluded from denominator via unresolved_recall.
                unresolved_recall += 1
            else:
                # result is False → partial vocabulary credit applies
                partial_credits[f"pos_{i}"] = credit

    # ── PRECISION: negative tests ────────────────────────────────────────────
    for i, test in enumerate(test_suite.negative_tests):
        _, credit = _tier1_vocabulary(candidate_fol, test, strict_mode=strict_mode)

        if credit == 0.0:
            # Candidate lacks the perturbed predicate entirely → trivially safe
            precision_passed += 1
            tier1_skips += 1
            continue

        # Candidate has the perturbed predicate → need to check actual entailment
        test_expr = parse_fol(test.fol_string) if NLTK_AVAILABLE else None
        resolved = False
        if candidate_expr is not None and test_expr is not None:
            t2 = _tier2_ast(candidate_expr, test_expr)
            if t2 is not None:
                if not t2:
                    precision_passed += 1
                tier2_skips += 1
                resolved = True

        if not resolved:
            prover_calls += 1
            result = _tier3_prover(candidate_fol, test.fol_string, prover_timeout)
            if result is False:
                # FIX B1: candidate provably does NOT entail the negative test
                # → a real precision pass.
                precision_passed += 1
            elif result is None:
                # FIX B1: prover unresolved → exclude from precision denominator.
                unresolved_precision += 1
            # result is True → candidate wrongly entails the negative test,
            # precision fails (no increment)

    # FIX B1: in strict mode, any unresolved test aborts the run rather than
    # silently producing a degraded (or inflated) score.
    if strict_mode and (unresolved_recall > 0 or unresolved_precision > 0):
        raise ProverUnavailableError(
            f"{unresolved_recall} recall and {unresolved_precision} precision "
            f"tests were unresolved because the theorem prover was unavailable "
            f"or timed out. Published SIV scores require strict_mode=True with "
            f"a working prover. Configure Vampire via siv.vampire_interface "
            f"or run with strict_mode=False (reward-shaping mode)."
        )

    return VerificationResult(
        candidate_fol=candidate_fol,
        syntax_valid=syntax_valid,
        recall_passed=recall_passed,
        recall_total=n_pos,
        precision_passed=precision_passed,
        precision_total=n_neg,
        tier1_skips=tier1_skips,
        tier2_skips=tier2_skips,
        prover_calls=prover_calls,
        partial_credits=partial_credits,
        unresolved_recall=unresolved_recall,
        unresolved_precision=unresolved_precision,
    )
