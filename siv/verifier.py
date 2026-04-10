"""
Tiered Verification Pipeline.

Tier 0: Syntax check  — does the candidate parse as valid FOL?
Tier 1: Vocabulary    — strict predicate presence check (full match or zero)
Tier 2: AST patterns  — lightweight structural check (no prover)
Tier 3: Vampire       — full theorem proving (only for unresolved tests)

Vocabulary check at Tier 1 (recall tests):
  Full match   (predicate present as standalone):     1.0
  No match     (predicate absent entirely):           0.0

A test resolved at Tier 1 with full credit counts as recall_passed.
A test definitively failed at Tier 1 (credit = 0.0) is skipped (no prover call).
"""
from typing import Literal, Optional, Set, Tuple

from siv.consistency import ast_level_inconsistency
from siv.fol_utils import (
    NLTK_AVAILABLE, extract_predicates, is_valid_fol, parse_fol,
)
from siv.schema import ProverUnavailableError, TestSuite, UnitTest, VerificationResult
from siv.vampire_interface import check_entailment, check_satisfiability


# ── Predicate helpers ─────────────────────────────────────────────────────────

def _extract_predicates_from_fol(fol_string: str) -> Set[str]:
    """Return all predicate names from *fol_string*."""
    return extract_predicates(fol_string)


# ── Tier 0: Syntax ────────────────────────────────────────────────────────────

def _tier0_syntax(candidate: str) -> bool:
    """Return True if *candidate* parses as valid NLTK FOL."""
    return is_valid_fol(candidate)


# ── Tier 0b: Consistency ──────────────────────────────────────────────────────

def _tier0_consistency(candidate_fol: str, timeout: int = 2) -> Optional[bool]:
    """
    Check candidate internal consistency via two-stage approach.

    Returns:
      False — candidate is provably inconsistent (short-circuit to SIV=0)
      True  — candidate is known consistent
      None  — unresolved (prover unavailable or timeout); caller proceeds normally
    """
    # First, cheap AST-level check (no prover needed)
    if ast_level_inconsistency(candidate_fol):
        return False
    # Then, prover-level check if available
    return check_satisfiability(candidate_fol, timeout=timeout)


# ── Tier 1: Vocabulary ────────────────────────────────────────────────────────

def _tier1_vocabulary(
    candidate: str,
    test: UnitTest,
) -> Tuple[bool, float]:
    """
    Strict vocabulary check.

    (True,  1.0) → all predicates found as standalone → full credit
    (False, 0.0) → any predicate absent → definitive fail

    For NEGATIVE tests the semantics are inverted by the caller.
    """
    test_preds      = _extract_predicates_from_fol(test.fol_string)
    candidate_preds = _extract_predicates_from_fol(candidate)

    if not test_preds:
        return (True, 1.0)

    if test_preds.issubset(candidate_preds):
        return (True, 1.0)
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

            # Walk into every ExistsExpression in the candidate's top-level conjuncts
            for conj in candidate_conjuncts:
                if isinstance(conj, ExistsExpression):
                    inner_body_conjuncts = collect_conjuncts(conj.term)
                    if inner in inner_body_conjuncts:
                        return True

            # Handle the case where the top-level candidate expression IS an ExistsExpression
            if isinstance(candidate_expr, ExistsExpression):
                candidate_body_conjuncts = collect_conjuncts(candidate_expr.term)
                if inner in candidate_body_conjuncts:
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
    unresolved_policy: Literal["raise", "exclude"] = "raise",
) -> VerificationResult:
    """
    Run the full tiered verification of one candidate against a test suite.

    For POSITIVE tests: candidate must entail → counted in recall.
    For NEGATIVE tests: candidate must NOT entail → counted in precision.

    unresolved_policy="raise" (default, published-metric behavior):
        Any test unresolved by the prover raises ProverUnavailableError.
    unresolved_policy="exclude":
        Unresolved tests are excluded from the effective denominator via
        unresolved_recall / unresolved_precision. Run completes normally.
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

    # ── Tier 0b: consistency (Defense 2 against ex-falso exploits) ────────────
    consistency = _tier0_consistency(candidate_fol, prover_timeout)
    if consistency is False:
        # Candidate is provably inconsistent — short-circuit to SIV=0.
        # None means "unresolved" → proceed normally (no error raised).
        return VerificationResult(
            candidate_fol=candidate_fol,
            syntax_valid=True,
            recall_passed=0,
            recall_total=n_pos,
            precision_passed=0,
            precision_total=n_neg,
            tier1_skips=0,
            tier2_skips=0,
            prover_calls=1 if consistency is not None else 0,
            candidate_inconsistent=True,
        )

    recall_passed    = 0
    precision_passed = 0
    tier1_skips      = 0
    tier2_skips      = 0
    prover_calls     = 0
    # FIX B1: track tests that could not be resolved by the prover.
    unresolved_recall    = 0
    unresolved_precision = 0

    candidate_expr = parse_fol(candidate_fol) if NLTK_AVAILABLE else None

    # ── RECALL: positive tests ───────────────────────────────────────────────
    for test in test_suite.positive_tests:
        definitive, credit = _tier1_vocabulary(candidate_fol, test)

        if credit == 0.0:
            # Predicate completely absent → definitive fail
            tier1_skips += 1
            continue

        # credit == 1.0: full vocabulary match → need structural / prover check
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
            # FIX B1: prover unresolved → excluded from denominator.
            unresolved_recall += 1
        # result is False → fall through, no increment, no exclusion

    # ── PRECISION: negative tests ────────────────────────────────────────────
    for test in test_suite.negative_tests:
        _, credit = _tier1_vocabulary(candidate_fol, test)

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

    # FIX B1: in "raise" mode, any unresolved test aborts the run rather than
    # silently producing a degraded (or inflated) score.
    if unresolved_policy == "raise" and (unresolved_recall > 0 or unresolved_precision > 0):
        raise ProverUnavailableError(
            f"{unresolved_recall} recall and {unresolved_precision} precision "
            f"tests were unresolved because the theorem prover was unavailable "
            f"or timed out. Published SIV scores require a working prover. "
            f"Configure Vampire via siv.vampire_interface or run with "
            f'unresolved_policy="exclude" (unresolved tests excluded from denominator).'
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
        unresolved_recall=unresolved_recall,
        unresolved_precision=unresolved_precision,
    )
