"""
AST-level consistency checker for FOL candidates.

Provides a fast, Vampire-free check for the most common ex-falso pattern:
a top-level conjunction containing both P(...) and -P(...) with identical
arguments.  This is a proper subset of full consistency checking — it will
miss contradictions that require quantifier reasoning — but it catches the
most common attack vector reliably and without any external tools.
"""
from typing import List, Optional, Set, Tuple

from siv.fol_utils import NLTK_AVAILABLE, parse_fol


def _collect_conjuncts(expr) -> list:
    """Flatten a nested AndExpression into a flat list of conjuncts."""
    try:
        from nltk.sem.logic import AndExpression
        if isinstance(expr, AndExpression):
            return _collect_conjuncts(expr.first) + _collect_conjuncts(expr.second)
    except ImportError:
        pass
    return [expr]


def _unwrap_application(expr) -> Optional[Tuple[str, Tuple[str, ...]]]:
    """
    Unwrap a (possibly nested) ApplicationExpression into (pred_name, args).

    NLTK represents P(a, b) as ApplicationExpression(ApplicationExpression(P, a), b).
    We peel off arguments from the right until we reach the bare predicate.

    Returns None if *expr* is not an ApplicationExpression.
    """
    try:
        from nltk.sem.logic import ApplicationExpression
        if not isinstance(expr, ApplicationExpression):
            return None
        args: List[str] = []
        cur = expr
        while isinstance(cur, ApplicationExpression):
            args.append(str(cur.argument))
            cur = cur.function
        pred = str(cur)
        return pred, tuple(reversed(args))
    except ImportError:
        return None


def ast_level_inconsistency(candidate_fol: str) -> bool:
    """
    Cheap AST-level check for atomic contradictions.

    Returns True iff the candidate contains both P(...) and -P(...) as
    top-level conjuncts with identical arguments. This is a proper subset
    of full consistency checking — it will miss contradictions that require
    quantifier reasoning — but catches the most common ex-falso patterns.

    Does NOT require Vampire.
    """
    if not NLTK_AVAILABLE:
        return False

    expr = parse_fol(candidate_fol)
    if expr is None:
        return False

    try:
        from nltk.sem.logic import NegatedExpression

        conjuncts = _collect_conjuncts(expr)

        positive: Set[Tuple] = set()
        negative: Set[Tuple] = set()

        for conj in conjuncts:
            atom = _unwrap_application(conj)
            if atom is not None:
                positive.add(atom)
                continue
            if isinstance(conj, NegatedExpression):
                inner = _unwrap_application(conj.term)
                if inner is not None:
                    negative.add(inner)

        return bool(positive & negative)

    except Exception:
        return False
