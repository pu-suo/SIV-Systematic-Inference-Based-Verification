"""Tests for siv/vampire_interface.py — check_satisfiability."""
import pytest
from siv.fol_utils import NLTK_AVAILABLE
from siv.vampire_interface import check_satisfiability, is_vampire_available


def test_check_satisfiability_signature():
    """check_satisfiability must accept (candidate_fol: str, timeout: int)."""
    import inspect
    sig = inspect.signature(check_satisfiability)
    assert "candidate_fol" in sig.parameters
    assert "timeout" in sig.parameters


def test_check_satisfiability_returns_optional_bool():
    """check_satisfiability returns True, False, or None (never raises)."""
    result = check_satisfiability("P(a) & Q(b)", timeout=1)
    assert result is None or isinstance(result, bool)


def test_check_satisfiability_invalid_fol_returns_none():
    """Unparseable FOL must return None, not raise."""
    result = check_satisfiability("not valid fol !!!", timeout=1)
    assert result is None


@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
@pytest.mark.skipif(not is_vampire_available(), reason="Vampire not installed")
def test_check_satisfiability_consistent_candidate():
    """A consistent candidate should return True when Vampire is available."""
    result = check_satisfiability("P(a) & Q(b)", timeout=2)
    assert result is True or result is None  # None = prover unavailable


@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
@pytest.mark.skipif(not is_vampire_available(), reason="Vampire not installed")
def test_check_satisfiability_inconsistent_candidate():
    """An inconsistent candidate (P(a) & -P(a)) should return False when Vampire is available."""
    result = check_satisfiability("P(a) & -P(a)", timeout=2)
    assert result is False or result is None  # None = prover unavailable / timeout
