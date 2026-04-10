"""
One-time environment bootstrap for SIV.

Loads .env file (if present) via python-dotenv, and ensures NLTK
data is available. Import this module at the top of every CLI
entry point before any other SIV imports.

Usage:
    import siv._bootstrap  # side-effect: loads .env, checks NLTK data
"""
import os
import sys

# ── Load .env file if python-dotenv is available ──────────────────────────────

def _load_dotenv():
    try:
        from dotenv import load_dotenv
        # Walk up from CWD to find .env (handles running from subdirs)
        load_dotenv()
    except ImportError:
        pass

_load_dotenv()


# ── Ensure NLTK data is available ─────────────────────────────────────────────

def _ensure_nltk_data():
    """Download NLTK resources if missing. Silent when already present."""
    import nltk
    resources = {
        'corpora/wordnet': 'wordnet',
        'corpora/brown': 'brown',
        'taggers/averaged_perceptron_tagger_eng': 'averaged_perceptron_tagger_eng',
        'tokenizers/punkt_tab': 'punkt_tab',
    }
    for path, name in resources.items():
        try:
            nltk.data.find(path)
        except LookupError:
            nltk.download(name, quiet=True)

_ensure_nltk_data()


# ── Check spaCy model availability ────────────────────────────────────────────

def _check_spacy():
    """Warn (don't crash) if en_core_web_sm is missing."""
    try:
        import spacy
        spacy.load("en_core_web_sm")
    except OSError:
        print(
            "WARNING: spaCy model 'en_core_web_sm' not found.\n"
            "  Run: python -m spacy download en_core_web_sm\n"
            "  Or:  bash scripts/setup.sh\n",
            file=sys.stderr,
        )

_check_spacy()
