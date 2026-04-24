"""
FOL Utilities: parsing, normalization, predicate extraction, and TPTP conversion.

Ported and extended from SIV_Evaluation_Framework (3).ipynb, Cells 9-10, 12.
All FOL strings use NLTK format:
  exists x.(P(x) & Q(x))
  all x.(P(x) -> Q(x))
  -P(x)   (negation)
"""
import re
import unicodedata
from typing import Optional, Set, List

# ── NLTK logic imports ────────────────────────────────────────────────────────

NLTK_AVAILABLE = False
try:
    from nltk.sem.logic import (
        Expression, NegatedExpression,
        ApplicationExpression, BinaryExpression,
        Variable, AllExpression, ExistsExpression,
        AndExpression, OrExpression,
        ImpExpression, IffExpression, EqualityExpression,
        IndividualVariableExpression,
    )
    read_expr = Expression.fromstring
    NLTK_AVAILABLE = True
except ImportError:
    pass  # Callers that need NLTK will check NLTK_AVAILABLE


# ── Normalisation ─────────────────────────────────────────────────────────────

def normalize_fol_string(fol: str) -> str:
    """Convert Unicode symbols and common variants to NLTK ASCII format."""
    if not fol or not isinstance(fol, str):
        return ""

    # Step 1: Replace Unicode logic symbols BEFORE stripping non-ASCII.
    # Order matters: stripping non-ASCII first would silently delete these.
    for symbol, replacement in [
        # Quantifiers
        ("∀", "all "),  ("∃", "exists "),
        # Conjunction / disjunction
        ("∧", " & "),   ("∨", " | "),
        ("⋀", " & "),   ("⋁", " | "),   # n-ary variants (U+22C0, U+22C1)
        # Implication — FOLIO v2 uses ⇒ on many problems
        ("→", " -> "),  ("⇒", " -> "),  ("⟹", " -> "),
        # Biconditional
        ("↔", " <-> "), ("⟺", " <-> "), ("⇔", " <-> "),
        # Negation
        ("¬", "-"),     ("~", "-"),
    ]:
        fol = fol.replace(symbol, replacement)

    # Step 2: Strip remaining non-ASCII (fancy quotes, curly arrows, etc.)
    fol = unicodedata.normalize("NFKD", fol).encode("ascii", "ignore").decode("ascii")

    # Step 3: ASCII keyword and whitespace normalisations
    for pattern, replacement in [
        (r"\bforall\b", "all"),
        (r"\bexist\b(?!s)", "exists"),  # "exist x" → "exists x" but keep "exists"
        (r"(?<=[A-Za-z0-9_])(all|exists)(?=\s)", r" \1"),  # ∀x∃y → "all x exists y"
        (r"\s+", " "),
    ]:
        fol = re.sub(pattern, replacement, fol)

    return fol.strip()


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_fol(fol_string: str) -> "Optional[Expression]":
    """
    Parse a FOL string into an NLTK Expression.
    Returns None if NLTK is unavailable or the string is syntactically invalid.
    """
    if not NLTK_AVAILABLE:
        return None
    try:
        normalized = normalize_fol_string(fol_string)
        if not normalized:
            return None
        return read_expr(normalized)
    except Exception:
        return None


def is_valid_fol(fol_string: str) -> bool:
    """Return True if *fol_string* parses as valid NLTK FOL."""
    return parse_fol(fol_string) is not None


# ── Predicate extraction ──────────────────────────────────────────────────────

def extract_predicates(fol_string: str) -> Set[str]:
    """
    Return the set of all predicate names that appear in *fol_string*.

    Primary path: walk the NLTK AST.
    Fallback (no NLTK / parse failure): regex over CamelCase identifiers
    followed by '('.
    """
    expr = parse_fol(fol_string)
    if expr is not None:
        return _extract_predicates_from_expr(expr)
    # Regex fallback
    matches = re.findall(r"([A-Z][A-Za-z0-9_]*)\s*\(", fol_string)
    keywords = {"All", "Exists", "Forall", "And", "Or", "Not", "Implies"}
    return {m for m in matches if m not in keywords}


def _extract_predicates_from_expr(expr) -> Set[str]:
    """Recursively walk an NLTK Expression and collect predicate names."""
    if not NLTK_AVAILABLE:
        return set()
    if isinstance(expr, ApplicationExpression):
        # Walk down the curried application chain to get the predicate head
        e = expr
        while isinstance(e, ApplicationExpression):
            e = e.function
        if hasattr(e, "variable"):
            return {e.variable.name}
        return set()
    elif isinstance(expr, BinaryExpression):
        return (
            _extract_predicates_from_expr(expr.first)
            | _extract_predicates_from_expr(expr.second)
        )
    elif isinstance(expr, NegatedExpression):
        return _extract_predicates_from_expr(expr.term)
    elif hasattr(expr, "term"):
        return _extract_predicates_from_expr(expr.term)
    return set()


# ── TPTP conversion ───────────────────────────────────────────────────────────

def convert_to_tptp(expr, _toplevel: bool = True) -> str:
    """
    Recursively convert an NLTK Expression to TPTP format for Vampire.

    TPTP conventions used here:
      - Variables are upper-case single letters (X, Y, …)
      - Predicates/constants are lower-case
      - Quantifiers: ?[X] : … (exists),  ![X] : … (all)

    Free variables are closed with universal quantifiers at the top level,
    following the standard convention that free variables in classical FOL
    are implicitly universally quantified.
    """
    if not NLTK_AVAILABLE:
        raise RuntimeError("NLTK is required for TPTP conversion.")

    # At the top level, close any free variables with universal quantifiers
    if _toplevel:
        free_vars = sorted(str(v) for v in expr.free())
        core = _convert_to_tptp_inner(expr)
        if free_vars:
            var_list = ", ".join(_tptp_var(v) for v in free_vars)
            return f"![{var_list}] : ({core})"
        return core

    return _convert_to_tptp_inner(expr)


def _convert_to_tptp_inner(expr) -> str:
    """Inner recursive TPTP conversion (does not close free variables)."""

    r = _convert_to_tptp_inner  # short alias for recursive calls

    if isinstance(expr, ExistsExpression):
        return f"?[{_tptp_var(str(expr.variable))}] : ({r(expr.term)})"
    elif isinstance(expr, AllExpression):
        return f"![{_tptp_var(str(expr.variable))}] : ({r(expr.term)})"
    elif isinstance(expr, NegatedExpression):
        return f"~({r(expr.term)})"
    elif isinstance(expr, AndExpression):
        return f"({r(expr.first)} & {r(expr.second)})"
    elif isinstance(expr, OrExpression):
        return f"({r(expr.first)} | {r(expr.second)})"
    elif isinstance(expr, ImpExpression):
        return f"({r(expr.first)} => {r(expr.second)})"
    elif isinstance(expr, IffExpression):
        return f"({r(expr.first)} <=> {r(expr.second)})"
    elif isinstance(expr, EqualityExpression):
        return f"({r(expr.first)} = {r(expr.second)})"
    elif isinstance(expr, ApplicationExpression):
        # Uncurry: f(a)(b)(c) → pred(a, b, c)
        func = expr.function
        args: List = [expr.argument]
        while isinstance(func, ApplicationExpression):
            args.insert(0, func.argument)
            func = func.function
        pred_name = _tptp_const(str(func).lower())
        args_str = ", ".join(r(a) for a in args)
        return f"{pred_name}({args_str})"
    elif isinstance(expr, IndividualVariableExpression):
        # NLTK treats lowercase u-z identifiers as bound-variable expressions;
        # TPTP requires variables to be uppercase identifiers.
        return _tptp_var(str(expr.variable))
    elif isinstance(expr, Variable):
        return _tptp_var(str(expr))
    else:
        return _tptp_const(str(expr).lower())


def _tptp_var(name: str) -> str:
    """Render an NLTK variable name as a valid TPTP variable identifier."""
    return name[0].upper() + name[1:] if name else name


def _tptp_const(name: str) -> str:
    """Render a constant or predicate name as a valid TPTP identifier.

    TPTP requires lowercase constants/functions/predicates to start with
    [a-z].  Identifiers that start with a digit (e.g. ``2008SummerOlympics``)
    are prefixed with ``c_`` to make them syntactically valid.
    """
    if not name:
        return name
    if name[0].isdigit():
        return f"c_{name}"
    return name
