"""
AST-level perturbation functions for NLTK FOL Expressions.

Each perturbation takes a parsed NLTK ``Expression`` and returns a modified
``Expression``, or raises ``NotApplicable`` if the transformation does not
fit the formula's structure.  Perturbations are grouped into four tiers:

  - **Tier A**: Subtle, debatable (reasonable annotators may disagree).
  - **Tier B**: Meaning-altering, lexically close (paper's Exhibit A).
  - **Tier C**: Clearly wrong but fluent.
  - **Tier D**: Nonsense.

All perturbations operate on the parsed *gold* FOL — never on SIV's
``SentenceExtraction`` schema.  They are deterministic given a fixed RNG seed.
"""
from __future__ import annotations

import random
import re
import string
from typing import Dict, List, Optional, Set, Tuple

from siv.fol_utils import parse_fol, NLTK_AVAILABLE

if NLTK_AVAILABLE:
    from nltk.sem.logic import (
        Expression,
        AllExpression,
        ExistsExpression,
        NegatedExpression,
        ApplicationExpression,
        AndExpression,
        OrExpression,
        ImpExpression,
        IffExpression,
        BinaryExpression,
        ConstantExpression,
        IndividualVariableExpression,
        Variable,
    )

    read_expr = Expression.fromstring


# ── Exception ────────────────────────────────────────────────────────────────


class NotApplicable(Exception):
    """Raised when a perturbation cannot be applied to the given expression."""


# ── Helpers ──────────────────────────────────────────────────────────────────


def _uncurry(expr: "ApplicationExpression") -> Tuple:
    """Uncurry a chain of ApplicationExpressions into (head, [args])."""
    func = expr
    args = []
    while isinstance(func, ApplicationExpression):
        args.insert(0, func.argument)
        func = func.function
    return func, args


def _curry(head, args: list) -> "Expression":
    """Rebuild a curried ApplicationExpression from head and args."""
    result = head
    for arg in args:
        result = ApplicationExpression(result, arg)
    return result


def _pred_name(expr: "ApplicationExpression") -> str:
    """Get the predicate name from an ApplicationExpression."""
    head, _ = _uncurry(expr)
    return str(head)


def _find_predicates(expr) -> List[Tuple[str, int]]:
    """Walk AST and return (pred_name, arity) pairs found."""
    results = []
    if isinstance(expr, ApplicationExpression):
        head, args = _uncurry(expr)
        results.append((str(head), len(args)))
        for a in args:
            results.extend(_find_predicates(a))
    elif isinstance(expr, BinaryExpression):
        results.extend(_find_predicates(expr.first))
        results.extend(_find_predicates(expr.second))
    elif isinstance(expr, NegatedExpression):
        results.extend(_find_predicates(expr.term))
    elif isinstance(expr, (AllExpression, ExistsExpression)):
        results.extend(_find_predicates(expr.term))
    elif hasattr(expr, "term"):
        results.extend(_find_predicates(expr.term))
    return results


def _find_constants(expr) -> Set[str]:
    """Walk AST and return set of constant names."""
    results = set()
    if isinstance(expr, ApplicationExpression):
        _, args = _uncurry(expr)
        for a in args:
            if isinstance(a, ConstantExpression):
                results.add(str(a))
            else:
                results.update(_find_constants(a))
    elif isinstance(expr, BinaryExpression):
        results.update(_find_constants(expr.first))
        results.update(_find_constants(expr.second))
    elif isinstance(expr, NegatedExpression):
        results.update(_find_constants(expr.term))
    elif isinstance(expr, (AllExpression, ExistsExpression)):
        results.update(_find_constants(expr.term))
    elif isinstance(expr, ConstantExpression):
        results.add(str(expr))
    elif hasattr(expr, "term"):
        results.update(_find_constants(expr.term))
    return results


def _camel_split(name: str) -> List[str]:
    """Split CamelCase into components: 'ProfessionalTennisPlayer' -> ['Professional', 'Tennis', 'Player']."""
    parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    parts = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", parts)
    return parts.split()


def _replace_pred_name(expr, old_name: str, new_name: str):
    """Replace predicate name throughout the AST."""
    if isinstance(expr, ApplicationExpression):
        head, args = _uncurry(expr)
        if str(head) == old_name:
            new_head = read_expr(new_name)
            new_args = [_replace_pred_name(a, old_name, new_name) for a in args]
            return _curry(new_head, new_args)
        new_args = [_replace_pred_name(a, old_name, new_name) for a in args]
        return _curry(head, new_args)
    elif isinstance(expr, AndExpression):
        return AndExpression(
            _replace_pred_name(expr.first, old_name, new_name),
            _replace_pred_name(expr.second, old_name, new_name),
        )
    elif isinstance(expr, OrExpression):
        return OrExpression(
            _replace_pred_name(expr.first, old_name, new_name),
            _replace_pred_name(expr.second, old_name, new_name),
        )
    elif isinstance(expr, ImpExpression):
        return ImpExpression(
            _replace_pred_name(expr.first, old_name, new_name),
            _replace_pred_name(expr.second, old_name, new_name),
        )
    elif isinstance(expr, IffExpression):
        return IffExpression(
            _replace_pred_name(expr.first, old_name, new_name),
            _replace_pred_name(expr.second, old_name, new_name),
        )
    elif isinstance(expr, NegatedExpression):
        return NegatedExpression(_replace_pred_name(expr.term, old_name, new_name))
    elif isinstance(expr, AllExpression):
        return AllExpression(expr.variable, _replace_pred_name(expr.term, old_name, new_name))
    elif isinstance(expr, ExistsExpression):
        return ExistsExpression(expr.variable, _replace_pred_name(expr.term, old_name, new_name))
    return expr


def _replace_constant(expr, old_name: str, new_name: str):
    """Replace a constant name throughout the AST."""
    if isinstance(expr, ConstantExpression) and str(expr) == old_name:
        return read_expr(new_name)
    elif isinstance(expr, ApplicationExpression):
        head, args = _uncurry(expr)
        new_args = [_replace_constant(a, old_name, new_name) for a in args]
        new_head = _replace_constant(head, old_name, new_name)
        return _curry(new_head, new_args)
    elif isinstance(expr, AndExpression):
        return AndExpression(
            _replace_constant(expr.first, old_name, new_name),
            _replace_constant(expr.second, old_name, new_name),
        )
    elif isinstance(expr, OrExpression):
        return OrExpression(
            _replace_constant(expr.first, old_name, new_name),
            _replace_constant(expr.second, old_name, new_name),
        )
    elif isinstance(expr, ImpExpression):
        return ImpExpression(
            _replace_constant(expr.first, old_name, new_name),
            _replace_constant(expr.second, old_name, new_name),
        )
    elif isinstance(expr, IffExpression):
        return IffExpression(
            _replace_constant(expr.first, old_name, new_name),
            _replace_constant(expr.second, old_name, new_name),
        )
    elif isinstance(expr, NegatedExpression):
        return NegatedExpression(_replace_constant(expr.term, old_name, new_name))
    elif isinstance(expr, AllExpression):
        return AllExpression(expr.variable, _replace_constant(expr.term, old_name, new_name))
    elif isinstance(expr, ExistsExpression):
        return ExistsExpression(expr.variable, _replace_constant(expr.term, old_name, new_name))
    return expr


# ── Tier A — subtle ──────────────────────────────────────────────────────────


def A_arity_decompose(expr: "Expression") -> "Expression":
    """``P(x, c)`` → ``P_c(x)``: fold a constant argument into the predicate name.

    Finds the first binary predicate with a ``ConstantExpression`` argument,
    creates a new unary predicate incorporating the constant, and removes
    the constant argument.
    """
    found = _find_binary_with_constant(expr)
    if found is None:
        raise NotApplicable("No binary predicate with constant argument")
    pred_name, const_name, const_is_second = found
    new_pred = pred_name + const_name[0].upper() + const_name[1:]
    return _apply_arity_decompose(expr, pred_name, const_name, new_pred, const_is_second)


def _find_binary_with_constant(expr) -> Optional[Tuple[str, str, bool]]:
    """Find first binary predicate with a constant arg. Returns (pred, const, const_is_second)."""
    if isinstance(expr, ApplicationExpression):
        head, args = _uncurry(expr)
        if len(args) == 2:
            if isinstance(args[1], ConstantExpression):
                return (str(head), str(args[1]), True)
            if isinstance(args[0], ConstantExpression):
                return (str(head), str(args[0]), False)
        for a in args:
            r = _find_binary_with_constant(a)
            if r:
                return r
    elif isinstance(expr, BinaryExpression):
        r = _find_binary_with_constant(expr.first)
        if r:
            return r
        return _find_binary_with_constant(expr.second)
    elif isinstance(expr, NegatedExpression):
        return _find_binary_with_constant(expr.term)
    elif isinstance(expr, (AllExpression, ExistsExpression)):
        return _find_binary_with_constant(expr.term)
    return None


def _apply_arity_decompose(expr, pred_name, const_name, new_pred, const_is_second):
    """Recursively apply the arity decomposition."""
    if isinstance(expr, ApplicationExpression):
        head, args = _uncurry(expr)
        if str(head) == pred_name and len(args) == 2:
            if const_is_second and isinstance(args[1], ConstantExpression) and str(args[1]) == const_name:
                return _curry(read_expr(new_pred), [args[0]])
            if not const_is_second and isinstance(args[0], ConstantExpression) and str(args[0]) == const_name:
                return _curry(read_expr(new_pred), [args[1]])
        new_args = [_apply_arity_decompose(a, pred_name, const_name, new_pred, const_is_second) for a in args]
        return _curry(head, new_args)
    elif isinstance(expr, AndExpression):
        return AndExpression(
            _apply_arity_decompose(expr.first, pred_name, const_name, new_pred, const_is_second),
            _apply_arity_decompose(expr.second, pred_name, const_name, new_pred, const_is_second),
        )
    elif isinstance(expr, OrExpression):
        return OrExpression(
            _apply_arity_decompose(expr.first, pred_name, const_name, new_pred, const_is_second),
            _apply_arity_decompose(expr.second, pred_name, const_name, new_pred, const_is_second),
        )
    elif isinstance(expr, ImpExpression):
        return ImpExpression(
            _apply_arity_decompose(expr.first, pred_name, const_name, new_pred, const_is_second),
            _apply_arity_decompose(expr.second, pred_name, const_name, new_pred, const_is_second),
        )
    elif isinstance(expr, IffExpression):
        return IffExpression(
            _apply_arity_decompose(expr.first, pred_name, const_name, new_pred, const_is_second),
            _apply_arity_decompose(expr.second, pred_name, const_name, new_pred, const_is_second),
        )
    elif isinstance(expr, NegatedExpression):
        return NegatedExpression(
            _apply_arity_decompose(expr.term, pred_name, const_name, new_pred, const_is_second)
        )
    elif isinstance(expr, AllExpression):
        return AllExpression(
            expr.variable,
            _apply_arity_decompose(expr.term, pred_name, const_name, new_pred, const_is_second),
        )
    elif isinstance(expr, ExistsExpression):
        return ExistsExpression(
            expr.variable,
            _apply_arity_decompose(expr.term, pred_name, const_name, new_pred, const_is_second),
        )
    return expr


def A_const_to_unary(expr: "Expression") -> "Expression":
    """``Has(x, fever)`` → ``HasFever(x)``: merge constant into predicate name as unary."""
    found = _find_binary_with_constant(expr)
    if found is None:
        raise NotApplicable("No predicate with constant argument")
    pred_name, const_name, const_is_second = found
    new_pred = pred_name + const_name[0].upper() + const_name[1:]
    return _apply_arity_decompose(expr, pred_name, const_name, new_pred, const_is_second)


def A_compound_decompose(expr: "Expression") -> "Expression":
    """``ProfessionalTennisPlayer(x)`` → ``(Professional(x) & TennisPlayer(x))``.

    Splits a CamelCase compound predicate name into component predicates.
    Only applies to unary predicates with ≥2 CamelCase components.
    """
    preds = _find_predicates(expr)
    for name, arity in preds:
        if arity != 1:
            continue
        parts = _camel_split(name)
        if len(parts) >= 2:
            return _apply_compound_decompose(expr, name, parts)
    raise NotApplicable("No compound CamelCase unary predicate found")


def _apply_compound_decompose(expr, old_name: str, parts: List[str]):
    """Replace unary pred with conjunction of component predicates."""
    if isinstance(expr, ApplicationExpression):
        head, args = _uncurry(expr)
        if str(head) == old_name and len(args) == 1:
            arg = args[0]
            # Build conjunction: Part1(arg) & Part2(arg) & ...
            conjuncts = [_curry(read_expr(p), [arg]) for p in parts]
            result = conjuncts[0]
            for c in conjuncts[1:]:
                result = AndExpression(result, c)
            return result
        new_args = [_apply_compound_decompose(a, old_name, parts) for a in args]
        return _curry(head, new_args)
    elif isinstance(expr, AndExpression):
        return AndExpression(
            _apply_compound_decompose(expr.first, old_name, parts),
            _apply_compound_decompose(expr.second, old_name, parts),
        )
    elif isinstance(expr, OrExpression):
        return OrExpression(
            _apply_compound_decompose(expr.first, old_name, parts),
            _apply_compound_decompose(expr.second, old_name, parts),
        )
    elif isinstance(expr, ImpExpression):
        return ImpExpression(
            _apply_compound_decompose(expr.first, old_name, parts),
            _apply_compound_decompose(expr.second, old_name, parts),
        )
    elif isinstance(expr, IffExpression):
        return IffExpression(
            _apply_compound_decompose(expr.first, old_name, parts),
            _apply_compound_decompose(expr.second, old_name, parts),
        )
    elif isinstance(expr, NegatedExpression):
        return NegatedExpression(_apply_compound_decompose(expr.term, old_name, parts))
    elif isinstance(expr, AllExpression):
        return AllExpression(expr.variable, _apply_compound_decompose(expr.term, old_name, parts))
    elif isinstance(expr, ExistsExpression):
        return ExistsExpression(expr.variable, _apply_compound_decompose(expr.term, old_name, parts))
    return expr


def A_const_rename(expr: "Expression", rng: random.Random) -> "Expression":
    """Stylistic constant rename: ``theMixer`` → ``mixer``, ``summerOlympics2008`` → ``olym2008``."""
    consts = sorted(_find_constants(expr))
    if not consts:
        raise NotApplicable("No constants to rename")
    target = consts[0]
    # Generate a plausible rename: take first 4 chars + optional suffix
    base = target[:4].lower()
    suffix = str(rng.randint(1, 99))
    new_name = base + suffix
    # Ensure it's a valid NLTK constant (starts with lowercase letter)
    if not new_name[0].isalpha():
        new_name = "c" + new_name
    return _replace_constant(expr, target, new_name)


# ── Tier B — meaning-altering ────────────────────────────────────────────────


SYMMETRIC_PREDICATES = {"Equal", "SameAs", "Similar", "Adjacent", "Married", "Sibling"}


def B_arg_swap(expr: "Expression") -> "Expression":
    """``P(a, b)`` → ``P(b, a)``: swap arguments of the first binary predicate."""
    swapped, did_swap = _swap_first_binary_args(expr)
    if not did_swap:
        raise NotApplicable("No binary predicate to swap")
    return swapped


def _swap_first_binary_args(expr, done=False):
    """Find and swap the first binary predicate's arguments."""
    if done:
        return expr, True
    if isinstance(expr, ApplicationExpression):
        head, args = _uncurry(expr)
        if len(args) == 2 and str(head) not in SYMMETRIC_PREDICATES:
            swapped = _curry(head, [args[1], args[0]])
            return swapped, True
        return expr, False
    elif isinstance(expr, AndExpression):
        new_first, d = _swap_first_binary_args(expr.first)
        if d:
            return AndExpression(new_first, expr.second), True
        new_second, d = _swap_first_binary_args(expr.second)
        return AndExpression(expr.first, new_second), d
    elif isinstance(expr, OrExpression):
        new_first, d = _swap_first_binary_args(expr.first)
        if d:
            return OrExpression(new_first, expr.second), True
        new_second, d = _swap_first_binary_args(expr.second)
        return OrExpression(expr.first, new_second), d
    elif isinstance(expr, ImpExpression):
        new_first, d = _swap_first_binary_args(expr.first)
        if d:
            return ImpExpression(new_first, expr.second), True
        new_second, d = _swap_first_binary_args(expr.second)
        return ImpExpression(expr.first, new_second), d
    elif isinstance(expr, IffExpression):
        new_first, d = _swap_first_binary_args(expr.first)
        if d:
            return IffExpression(new_first, expr.second), True
        new_second, d = _swap_first_binary_args(expr.second)
        return IffExpression(expr.first, new_second), d
    elif isinstance(expr, NegatedExpression):
        new_term, d = _swap_first_binary_args(expr.term)
        return NegatedExpression(new_term), d
    elif isinstance(expr, AllExpression):
        new_term, d = _swap_first_binary_args(expr.term)
        return AllExpression(expr.variable, new_term), d
    elif isinstance(expr, ExistsExpression):
        new_term, d = _swap_first_binary_args(expr.term)
        return ExistsExpression(expr.variable, new_term), d
    return expr, False


def B_restrictor_drop(expr: "Expression") -> "Expression":
    """Drop one conjunct from the antecedent of a universal implication.

    ``all x.((A(x) & B(x)) -> C(x))`` → ``all x.(A(x) -> C(x))``
    """
    if not isinstance(expr, AllExpression):
        raise NotApplicable("Not a universal formula")
    body = expr.term
    if not isinstance(body, ImpExpression):
        raise NotApplicable("Universal body is not an implication")
    antecedent = body.first
    conjuncts = _flatten_and(antecedent)
    if len(conjuncts) < 2:
        raise NotApplicable("Antecedent has fewer than 2 conjuncts")
    # Drop the last conjunct
    remaining = conjuncts[:-1]
    new_ante = remaining[0]
    for c in remaining[1:]:
        new_ante = AndExpression(new_ante, c)
    return AllExpression(expr.variable, ImpExpression(new_ante, body.second))


def _flatten_and(expr) -> list:
    """Flatten nested AndExpressions into a list of conjuncts."""
    if isinstance(expr, AndExpression):
        return _flatten_and(expr.first) + _flatten_and(expr.second)
    return [expr]


def B_restrictor_add(expr: "Expression", story_predicates: List[str]) -> "Expression":
    """Add an extra conjunct to the antecedent from another story predicate.

    ``all x.(A(x) -> C(x))`` → ``all x.((A(x) & Extra(x)) -> C(x))``
    """
    if not isinstance(expr, AllExpression):
        raise NotApplicable("Not a universal formula")
    body = expr.term
    if not isinstance(body, ImpExpression):
        raise NotApplicable("Universal body is not an implication")

    existing_preds = {name for name, _ in _find_predicates(expr)}
    available = [p for p in story_predicates if p not in existing_preds]
    if not available:
        raise NotApplicable("No available predicates from story context")

    extra_pred = available[0]
    # Build Extra(bound_var) using the universal's bound variable
    bound_var = expr.variable
    extra_atom = read_expr(f"{extra_pred}({bound_var})")
    new_ante = AndExpression(body.first, extra_atom)
    return AllExpression(expr.variable, ImpExpression(new_ante, body.second))


def B_scope_flip(expr: "Expression") -> "Expression":
    """Swap the order of two nested quantifiers.

    ``all x.(exists y.R(x,y))`` → ``exists y.(all x.R(x,y))``
    """
    if isinstance(expr, AllExpression) and isinstance(expr.term, ExistsExpression):
        inner = expr.term
        return ExistsExpression(inner.variable, AllExpression(expr.variable, inner.term))
    if isinstance(expr, ExistsExpression) and isinstance(expr.term, AllExpression):
        inner = expr.term
        return AllExpression(inner.variable, ExistsExpression(expr.variable, inner.term))
    # Also handle: all x.(P(x) -> exists y.Q(x,y)) → exists y.(all x.(P(x) -> Q(x,y)))
    if isinstance(expr, AllExpression) and isinstance(expr.term, ImpExpression):
        consequent = expr.term.second
        if isinstance(consequent, ExistsExpression):
            new_body = ImpExpression(expr.term.first, consequent.term)
            return ExistsExpression(
                consequent.variable,
                AllExpression(expr.variable, new_body),
            )
    raise NotApplicable("No two nested quantifiers to flip")


def B_quantifier_swap(expr: "Expression") -> "Expression":
    """Swap the outermost quantifier type: ``∀`` → ``∃`` or vice versa."""
    if isinstance(expr, AllExpression):
        return ExistsExpression(expr.variable, expr.term)
    if isinstance(expr, ExistsExpression):
        return AllExpression(expr.variable, expr.term)
    raise NotApplicable("No top-level quantifier to swap")


# ── Tier C — clearly wrong ──────────────────────────────────────────────────


ANTONYM_LEXICON: Dict[str, str] = {
    "Tall": "Short", "Short": "Tall",
    "Happy": "Sad", "Sad": "Happy",
    "Rich": "Poor", "Poor": "Rich",
    "Strong": "Weak", "Weak": "Strong",
    "Love": "Hate", "Hate": "Love",
    "Loves": "Hates", "Hates": "Loves",
    "Like": "Dislike", "Dislike": "Like",
    "Likes": "Dislikes", "Dislikes": "Likes",
    "Before": "After", "After": "Before",
    "Above": "Below", "Below": "Above",
    "Taller": "Shorter", "Shorter": "Taller",
    "Larger": "Smaller", "Smaller": "Larger",
    "LocatedIn": "NotIn",
    "Accept": "Reject", "Reject": "Accept",
    "Win": "Lose", "Lose": "Win",
    "True": "False", "False": "True",
    "Good": "Bad", "Bad": "Good",
    "Fast": "Slow", "Slow": "Fast",
    "Hot": "Cold", "Cold": "Hot",
    "Old": "Young", "Young": "Old",
    "Cheap": "Expensive", "Expensive": "Cheap",
    "Safe": "Dangerous", "Dangerous": "Safe",
    "Legal": "Illegal", "Illegal": "Legal",
    "Dependent": "Independent", "Independent": "Dependent",
    "Aware": "Unaware", "Unaware": "Aware",
}


def C_predicate_substitute(
    expr: "Expression",
    antonym_lexicon: Optional[Dict[str, str]] = None,
) -> "Expression":
    """Swap one predicate for its antonym from the lexicon."""
    lexicon = antonym_lexicon or ANTONYM_LEXICON
    preds = _find_predicates(expr)
    for name, _ in preds:
        if name in lexicon:
            return _replace_pred_name(expr, name, lexicon[name])
    raise NotApplicable("No predicate has a known antonym")


def C_negation_drop(expr: "Expression") -> "Expression":
    """Remove the first ``NegatedExpression`` found in the AST."""
    result, did_drop = _drop_first_negation(expr)
    if not did_drop:
        raise NotApplicable("No negation to drop")
    return result


def _drop_first_negation(expr, done=False):
    if done:
        return expr, True
    if isinstance(expr, NegatedExpression):
        return expr.term, True
    elif isinstance(expr, AndExpression):
        new_first, d = _drop_first_negation(expr.first)
        if d:
            return AndExpression(new_first, expr.second), True
        new_second, d = _drop_first_negation(expr.second)
        return AndExpression(expr.first, new_second), d
    elif isinstance(expr, OrExpression):
        new_first, d = _drop_first_negation(expr.first)
        if d:
            return OrExpression(new_first, expr.second), True
        new_second, d = _drop_first_negation(expr.second)
        return OrExpression(expr.first, new_second), d
    elif isinstance(expr, ImpExpression):
        new_first, d = _drop_first_negation(expr.first)
        if d:
            return ImpExpression(new_first, expr.second), True
        new_second, d = _drop_first_negation(expr.second)
        return ImpExpression(expr.first, new_second), d
    elif isinstance(expr, IffExpression):
        new_first, d = _drop_first_negation(expr.first)
        if d:
            return IffExpression(new_first, expr.second), True
        new_second, d = _drop_first_negation(expr.second)
        return IffExpression(expr.first, new_second), d
    elif isinstance(expr, AllExpression):
        new_term, d = _drop_first_negation(expr.term)
        return AllExpression(expr.variable, new_term), d
    elif isinstance(expr, ExistsExpression):
        new_term, d = _drop_first_negation(expr.term)
        return ExistsExpression(expr.variable, new_term), d
    return expr, False


def C_entity_swap(expr: "Expression", story_constants: List[str]) -> "Expression":
    """Replace one constant with a different constant from the same story."""
    existing = sorted(_find_constants(expr))
    if not existing:
        raise NotApplicable("No constants in expression")
    target = existing[0]
    available = [c for c in story_constants if c != target and c not in existing]
    if not available:
        raise NotApplicable("No different constant available in story")
    replacement = available[0]
    return _replace_constant(expr, target, replacement)


# ── Tier D — nonsense ────────────────────────────────────────────────────────


def D_random_predicates(expr: "Expression", rng: random.Random) -> "Expression":
    """Replace all predicate names with random 6-character strings."""
    preds = _find_predicates(expr)
    if not preds:
        raise NotApplicable("No predicates in expression")
    # Build deterministic mapping
    name_map: Dict[str, str] = {}
    for name, _ in preds:
        if name not in name_map:
            rand_name = "".join(rng.choices(string.ascii_uppercase, k=1)) + \
                        "".join(rng.choices(string.ascii_lowercase + string.digits, k=5))
            name_map[name] = rand_name
    result = expr
    for old, new in name_map.items():
        result = _replace_pred_name(result, old, new)
    return result


# ── Dispatch ─────────────────────────────────────────────────────────────────

TIER_A_OPS = [A_arity_decompose, A_const_to_unary, A_compound_decompose, A_const_rename]
TIER_B_OPS = [B_arg_swap, B_restrictor_drop, B_restrictor_add, B_scope_flip, B_quantifier_swap]
TIER_C_OPS = [C_predicate_substitute, C_negation_drop, C_entity_swap]
TIER_D_OPS = [D_random_predicates]

_TIER_MAP = {"A": TIER_A_OPS, "B": TIER_B_OPS, "C": TIER_C_OPS, "D": TIER_D_OPS}

# Operators that need extra keyword args
_NEEDS_RNG = {A_const_rename, D_random_predicates}
_NEEDS_STORY_PREDS = {B_restrictor_add}
_NEEDS_STORY_CONSTS = {C_entity_swap}
_NEEDS_LEXICON = {C_predicate_substitute}


def select_perturbation(
    tier: str,
    expr: "Expression",
    rng: random.Random,
    story_predicates: Optional[List[str]] = None,
    story_constants: Optional[List[str]] = None,
    antonym_lexicon: Optional[Dict[str, str]] = None,
    exclude_ops: Optional[Set[str]] = None,
) -> Tuple["Expression", str]:
    """Try each operator in the tier (shuffled by rng) until one succeeds.

    Returns ``(perturbed_expr, operator_name)``.
    Raises ``NotApplicable`` if no operator in the tier can apply.

    *exclude_ops* can be used to skip specific operators (e.g., when
    generating a second Tier B perturbation different from the first).
    """
    ops = list(_TIER_MAP.get(tier, []))
    if not ops:
        raise NotApplicable(f"Unknown tier: {tier}")

    rng_copy = random.Random(rng.randint(0, 2**31))  # Don't mutate caller's rng state unpredictably
    rng_copy.shuffle(ops)

    excluded = exclude_ops or set()

    for op in ops:
        if op.__name__ in excluded:
            continue
        try:
            kwargs = {}
            if op in _NEEDS_RNG:
                kwargs["rng"] = random.Random(rng.randint(0, 2**31))
            if op in _NEEDS_STORY_PREDS:
                kwargs["story_predicates"] = story_predicates or []
            if op in _NEEDS_STORY_CONSTS:
                kwargs["story_constants"] = story_constants or []
            if op in _NEEDS_LEXICON:
                kwargs["antonym_lexicon"] = antonym_lexicon

            result = op(expr, **kwargs)

            # Validate round-trip
            result_str = str(result)
            reparsed = parse_fol(result_str)
            if reparsed is None:
                continue  # Skip this operator if output doesn't reparse

            return result, op.__name__
        except NotApplicable:
            continue

    raise NotApplicable(f"No Tier {tier} operator applicable")
