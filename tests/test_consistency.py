"""Tests for siv/consistency.py — AST-level inconsistency detection."""
import pytest
from siv.fol_utils import NLTK_AVAILABLE
from siv.consistency import ast_level_inconsistency


@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_simple_contradiction_detected():
    """P(a) & -P(a) is a classic atomic contradiction."""
    assert ast_level_inconsistency("P(a) & -P(a)") is True


@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_conjunction_no_contradiction():
    """P(a) & Q(b) has no contradiction."""
    assert ast_level_inconsistency("P(a) & Q(b)") is False


@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_different_predicates_no_contradiction():
    """P(a) & -Q(a) has different predicates — not a contradiction."""
    assert ast_level_inconsistency("P(a) & -Q(a)") is False


@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_different_args_no_contradiction():
    """P(a) & -P(b) has different arguments — AST check should not fire."""
    assert ast_level_inconsistency("P(a) & -P(b)") is False


@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_quantifier_level_not_detected():
    """all x.(P(x)) & exists y.(-P(y)) — the AST-level check is NOT required to
    catch this; the prover-level check handles it when available."""
    # Result can be False or True depending on implementation, but spec says
    # the AST-level check is *not required* to catch this case.
    result = ast_level_inconsistency("all x.(P(x)) & exists y.(-P(y))")
    # We only assert it doesn't crash and returns a bool
    assert isinstance(result, bool)


@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_binary_predicate_contradiction():
    """R(a, b) & -R(a, b) is a contradiction."""
    assert ast_level_inconsistency("R(a,b) & -R(a,b)") is True


@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_syntax_invalid_returns_false():
    """Unparseable FOL should not raise; it returns False."""
    assert ast_level_inconsistency("not valid fol !!!") is False


@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_single_atom_no_contradiction():
    """A single atom P(a) cannot be a contradiction."""
    assert ast_level_inconsistency("P(a)") is False
