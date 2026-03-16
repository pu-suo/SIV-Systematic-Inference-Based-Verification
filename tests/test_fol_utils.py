"""Tests for siv/fol_utils.py"""
import pytest
from siv.fol_utils import (
    normalize_fol_string,
    parse_fol,
    is_valid_fol,
    extract_predicates,
    convert_to_tptp,
    NLTK_AVAILABLE,
)


# ── normalize_fol_string ──────────────────────────────────────────────────────

def test_normalize_empty():
    assert normalize_fol_string("") == ""
    assert normalize_fol_string(None) == ""  # type: ignore

def test_normalize_forall():
    result = normalize_fol_string("forall x.P(x)")
    assert result == "all x.P(x)"

def test_normalize_exist_singular():
    result = normalize_fol_string("exist x.P(x)")
    assert "exists" in result

def test_normalize_whitespace():
    result = normalize_fol_string("all  x . P(x)")
    assert "  " not in result

def test_normalize_tilde_negation():
    result = normalize_fol_string("~P(x)")
    assert result == "-P(x)"

def test_normalize_preserves_nltk():
    fol = "all x.(Dog(x) -> Animal(x))"
    assert normalize_fol_string(fol) == fol


# ── is_valid_fol ──────────────────────────────────────────────────────────────

@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_valid_universal():
    assert is_valid_fol("all x.(Dog(x) -> Animal(x))")

@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_valid_existential():
    assert is_valid_fol("exists x.(Cat(x) & Happy(x))")

@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_valid_ground():
    assert is_valid_fol("Star(sun)")

@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_invalid_unmatched_paren():
    assert not is_valid_fol("exists x.Cat(x")

@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_invalid_empty():
    assert not is_valid_fol("")


# ── extract_predicates ────────────────────────────────────────────────────────

@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_extract_single():
    preds = extract_predicates("Tall(x)")
    assert "Tall" in preds

@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_extract_multiple():
    preds = extract_predicates("exists x.(Car(x) & Crimson(x) & Running(x))")
    assert preds == {"Car", "Crimson", "Running"}

@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_extract_universal():
    preds = extract_predicates("all x.(Dog(x) -> Animal(x))")
    assert "Dog" in preds
    assert "Animal" in preds

@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_extract_negated():
    preds = extract_predicates("all x.(Bird(x) -> -Flies(x))")
    assert "Bird" in preds
    assert "Flies" in preds

def test_extract_regex_fallback():
    # If NLTK parse fails, regex should still find CamelCase predicates
    preds = extract_predicates("CrimsonCar(x) & MovesQuickly(x)")
    assert "CrimsonCar" in preds or "CrimsonCar" in preds


# ── convert_to_tptp ───────────────────────────────────────────────────────────

@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_tptp_exists():
    expr = parse_fol("exists x.Cat(x)")
    tptp = convert_to_tptp(expr)
    assert "?[X]" in tptp
    assert "cat" in tptp.lower()

@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_tptp_all():
    expr = parse_fol("all x.(Dog(x) -> Animal(x))")
    tptp = convert_to_tptp(expr)
    assert "![X]" in tptp
    assert "=>" in tptp

@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_tptp_negation():
    expr = parse_fol("-Cat(x)")
    tptp = convert_to_tptp(expr)
    assert tptp.startswith("~")

@pytest.mark.skipif(not NLTK_AVAILABLE, reason="NLTK not installed")
def test_tptp_conjunction():
    expr = parse_fol("Car(x) & Red(x)")
    tptp = convert_to_tptp(expr)
    assert "&" in tptp
