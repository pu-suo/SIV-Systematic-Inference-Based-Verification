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

def convert_to_tptp(expr) -> str:
    """
    Recursively convert an NLTK Expression to TPTP format for Vampire.

    TPTP conventions used here:
      - Variables are upper-case single letters (X, Y, …)
      - Predicates/constants are lower-case
      - Quantifiers: ?[X] : … (exists),  ![X] : … (all)
    """
    if not NLTK_AVAILABLE:
        raise RuntimeError("NLTK is required for TPTP conversion.")

    if isinstance(expr, ExistsExpression):
        return f"?[{str(expr.variable).upper()}] : ({convert_to_tptp(expr.term)})"
    elif isinstance(expr, AllExpression):
        return f"![{str(expr.variable).upper()}] : ({convert_to_tptp(expr.term)})"
    elif isinstance(expr, NegatedExpression):
        return f"~({convert_to_tptp(expr.term)})"
    elif isinstance(expr, AndExpression):
        return f"({convert_to_tptp(expr.first)} & {convert_to_tptp(expr.second)})"
    elif isinstance(expr, OrExpression):
        return f"({convert_to_tptp(expr.first)} | {convert_to_tptp(expr.second)})"
    elif isinstance(expr, ImpExpression):
        return f"({convert_to_tptp(expr.first)} => {convert_to_tptp(expr.second)})"
    elif isinstance(expr, IffExpression):
        return f"({convert_to_tptp(expr.first)} <=> {convert_to_tptp(expr.second)})"
    elif isinstance(expr, EqualityExpression):
        return f"({convert_to_tptp(expr.first)} = {convert_to_tptp(expr.second)})"
    elif isinstance(expr, ApplicationExpression):
        # Uncurry: f(a)(b)(c) → pred(a, b, c)
        func = expr.function
        args: List = [expr.argument]
        while isinstance(func, ApplicationExpression):
            args.insert(0, func.argument)
            func = func.function
        pred_name = str(func).lower()
        args_str = ", ".join(convert_to_tptp(a) for a in args)
        return f"{pred_name}({args_str})"
    elif isinstance(expr, Variable):
        name = str(expr)
        # Single-letter variables → uppercase (TPTP convention)
        return name.upper() if len(name) == 1 else name.lower()
    else:
        return str(expr).lower()
