"""Tests for siv/pre_analyzer.py"""
import pytest
from siv.pre_analyzer import (
    analyze_sentence,
    _check_wordnet,
    _compute_pmi,
    format_analyses_for_prompt,
)
from siv.pre_analyzer import _SPACY_AVAILABLE


# ── _check_wordnet ─────────────────────────────────────────────────────────────

def test_wordnet_real_compound():
    # "fire" + "truck" → firetruck is in WordNet
    result = _check_wordnet("fire", "truck")
    # This may or may not be in WordNet depending on NLTK data version;
    # at minimum it should not crash
    assert isinstance(result, bool)

def test_wordnet_nonsense():
    assert _check_wordnet("xyzfoo", "barquux") is False


# ── _compute_pmi ──────────────────────────────────────────────────────────────

def test_pmi_unknown_returns_zero():
    cache = {"word_freq": {}, "bigram_freq": {}, "total_words": 1000, "total_bigrams": 900}
    assert _compute_pmi("zorp", "flibble", cache) == 0.0

def test_pmi_known_bigram():
    cache = {
        "word_freq":    {"tall": 100, "tree": 200},
        "bigram_freq":  {"tall_tree": 50},
        "total_words":  10000,
        "total_bigrams": 9000,
    }
    import math
    pmi = _compute_pmi("tall", "tree", cache)
    expected = math.log2(50 * 9000) - math.log2(100) - math.log2(200)
    assert abs(pmi - expected) < 1e-9


# ── analyze_sentence ──────────────────────────────────────────────────────────

@pytest.mark.skipif(not _SPACY_AVAILABLE, reason="spaCy model not installed")
def test_tall_tree_splits():
    """Spec test: 'tall tree' should get SPLIT recommendation."""
    results = analyze_sentence("The tall tree grows quickly.")
    tall = [r for r in results if r.modifier.lower() == "tall"]
    assert tall, "Expected 'tall' modifier to be detected"
    assert tall[0].recommendation == "SPLIT"

@pytest.mark.skipif(not _SPACY_AVAILABLE, reason="spaCy model not installed")
def test_harvard_student_keeps():
    """Spec test: 'Harvard student' should get KEEP recommendation."""
    results = analyze_sentence("A Harvard student passed the exam.")
    harvard = [r for r in results if r.modifier.lower() == "harvard"]
    assert harvard, "Expected 'Harvard' modifier to be detected"
    assert harvard[0].recommendation == "KEEP"

@pytest.mark.skipif(not _SPACY_AVAILABLE, reason="spaCy model not installed")
def test_analyze_no_modifiers():
    results = analyze_sentence("Nancy runs.")
    assert isinstance(results, list)

@pytest.mark.skipif(not _SPACY_AVAILABLE, reason="spaCy model not installed")
def test_compound_analysis_fields():
    results = analyze_sentence("The tall tree is green.")
    for r in results:
        assert r.recommendation in ("KEEP", "SPLIT")
        assert isinstance(r.pmi_score, float)
        assert isinstance(r.wordnet_hit, bool)
        assert isinstance(r.is_proper_noun, bool)
        assert r.dep_scope  # not empty


# ── format_analyses_for_prompt ────────────────────────────────────────────────

def test_format_empty():
    out = format_analyses_for_prompt([])
    assert "no compound" in out.lower()

@pytest.mark.skipif(not _SPACY_AVAILABLE, reason="spaCy model not installed")
def test_format_nonempty():
    results = analyze_sentence("The tall tree grows quickly.")
    out = format_analyses_for_prompt(results)
    assert isinstance(out, str)
    if results:
        # Should mention at least one modifier
        assert any(r.modifier.lower() in out.lower() for r in results)
