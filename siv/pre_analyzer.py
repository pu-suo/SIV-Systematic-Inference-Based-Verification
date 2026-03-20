"""
Stage 1: Symbolic Pre-Analysis

Runs BEFORE the LLM extraction.  Identifies modifier+noun compounds in the
sentence and computes four objective signals for each:

  Signal A: WordNet lookup   — is it a lexicalized compound?
  Signal B: PMI score        — how strongly collocated in corpus?
  Signal C: Proper noun flag — from spaCy POS tags
  Signal D: Dependency scope — does the modifier attach to subject or object?

Outputs per-compound recommendations (KEEP / SPLIT) injected into the LLM
extraction prompt.

Dependencies: spacy (en_core_web_sm), nltk (wordnet)
"""
import json
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from siv.schema import CompoundAnalysis

# ── Optional heavy dependencies ───────────────────────────────────────────────

try:
    import spacy
    _NLP = spacy.load("en_core_web_sm")
    _SPACY_AVAILABLE = True
except Exception:
    _NLP = None
    _SPACY_AVAILABLE = False

try:
    from nltk.corpus import wordnet as wn
    _WN_AVAILABLE = True
except Exception:
    _WN_AVAILABLE = False

# ── PMI cache ─────────────────────────────────────────────────────────────────

_PMI_CACHE: Optional[dict] = None
_PMI_THRESHOLD = 3.0          # log2 units; above this → statistically fixed phrase
_DATA_DIR = Path(__file__).parent.parent / "data"


def _load_pmi_cache() -> dict:
    global _PMI_CACHE
    if _PMI_CACHE is not None:
        return _PMI_CACHE
    cache_path = _DATA_DIR / "pmi_cache.json"
    if cache_path.exists():
        with open(cache_path) as f:
            _PMI_CACHE = json.load(f)
    else:
        _PMI_CACHE = {"word_freq": {}, "bigram_freq": {}, "total_words": 1, "total_bigrams": 1}
    return _PMI_CACHE


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_sentence(sentence: str) -> List[CompoundAnalysis]:
    """
    Run full pre-analysis on one sentence.
    Returns one CompoundAnalysis per modifier+noun pair found.
    Falls back gracefully when spaCy is unavailable (returns empty list).
    """
    if not _SPACY_AVAILABLE:
        return []
    doc = _NLP(sentence)
    compounds = _find_compounds(doc)
    return [_make_recommendation(c) for c in compounds]


def format_analyses_for_prompt(analyses: List[CompoundAnalysis]) -> str:
    """
    Render CompoundAnalysis objects as a human-readable block suitable for
    injecting into the LLM extraction prompt.

    When is_proper_noun=True, appends a [Route to constants array] instruction
    to give the LLM a clear signal for the two-list schema.
    """
    if not analyses:
        return "(no compound modifiers detected)"
    lines = []
    for ca in analyses:
        wn_flag = "WordNet:YES" if ca.wordnet_hit else "WordNet:NO"
        pn_flag = "ProperNoun:YES" if ca.is_proper_noun else "ProperNoun:NO"
        route = "  [Route to constants array]" if ca.is_proper_noun else ""
        lines.append(
            f'  • "{ca.modifier} {ca.noun}"  [{wn_flag}  PMI={ca.pmi_score:.1f}'
            f"  {pn_flag}  dep={ca.dep_scope}]  → {ca.recommendation}"
            f" ({ca.reason}){route}"
        )
    return "\n".join(lines)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _find_compounds(doc) -> List[dict]:
    """
    Extract modifier+noun pairs from a spaCy parse.
    Looks for tokens whose dependency label is 'amod' or 'compound' and
    whose head is a NOUN or PROPN.
    """
    pairs = []
    for token in doc:
        if token.dep_ in ("amod", "compound") and token.head.pos_ in ("NOUN", "PROPN"):
            pairs.append({
                "modifier": token.text,
                "noun":     token.head.text,
                "modifier_tok": token,
                "noun_tok":     token.head,
            })
    return pairs


def _check_wordnet(modifier: str, noun: str) -> bool:
    """
    Check whether *modifier_noun* (or close variants) exists as a WordNet synset.
    """
    if not _WN_AVAILABLE:
        return False
    candidates = [
        f"{modifier.lower()}_{noun.lower()}",
        f"{modifier.lower()}{noun.lower()}",
        f"{modifier.lower()}-{noun.lower()}",
    ]
    for lemma in candidates:
        if wn.synsets(lemma):
            return True
    return False


def _compute_pmi(modifier: str, noun: str, cache: dict) -> float:
    """
    Compute Pointwise Mutual Information for the modifier+noun bigram.

      PMI = log2( P(m,n) / (P(m) * P(n)) )
           = log2( freq(m_n) * N ) - log2( freq(m) ) - log2( freq(n) )

    where N is total_bigrams and frequencies are from the pre-cached Brown corpus.
    Returns 0.0 when the bigram is not in the cache (unknown → conservative KEEP).
    """
    key = f"{modifier.lower()}_{noun.lower()}"
    bigram_f = cache.get("bigram_freq", {}).get(key, 0)
    if bigram_f == 0:
        return 0.0
    word_f = cache.get("word_freq", {})
    mod_f  = word_f.get(modifier.lower(), 1)
    noun_f = word_f.get(noun.lower(), 1)
    N = cache.get("total_bigrams", 1)

    pmi = math.log2(bigram_f * N) - math.log2(mod_f) - math.log2(noun_f)
    return pmi


def _check_dep_scope(noun_tok) -> str:
    """
    Return the dependency label of the head noun the modifier attaches to.
    If the noun is itself a root argument (nsubj / nsubjpass), the modifier
    targets the subject entity → useful for deciding SPLIT.
    """
    return noun_tok.dep_


def _make_recommendation(compound: dict) -> CompoundAnalysis:
    """
    Apply the four-signal decision rule and return a CompoundAnalysis.

    Priority order (highest wins):
      1. WordNet hit                      → KEEP  (lexicalized compound)
      2. Proper-noun modifier             → KEEP  (named category like "Harvard")
      3. High PMI (> threshold)           → KEEP  (statistically fixed phrase)
      4. Subject-targeting + low PMI      → SPLIT (independent property)
      5. Default                          → KEEP  (conservative)
    """
    cache = _load_pmi_cache()

    modifier   = compound["modifier"]
    noun       = compound["noun"]
    mod_tok    = compound["modifier_tok"]
    noun_tok   = compound["noun_tok"]

    wn_hit     = _check_wordnet(modifier, noun)
    pmi_score  = _compute_pmi(modifier, noun, cache)
    is_proper  = mod_tok.pos_ == "PROPN" or mod_tok.is_title
    dep_scope  = _check_dep_scope(noun_tok)

    if wn_hit:
        return CompoundAnalysis(
            modifier=modifier, noun=noun,
            wordnet_hit=True, pmi_score=pmi_score,
            is_proper_noun=is_proper, dep_scope=dep_scope,
            recommendation="KEEP",
            reason="Lexicalized compound in WordNet.",
        )

    if is_proper:
        return CompoundAnalysis(
            modifier=modifier, noun=noun,
            wordnet_hit=False, pmi_score=pmi_score,
            is_proper_noun=True, dep_scope=dep_scope,
            recommendation="KEEP",
            reason="Proper-noun modifier denotes a named category.",
        )

    if pmi_score > _PMI_THRESHOLD:
        return CompoundAnalysis(
            modifier=modifier, noun=noun,
            wordnet_hit=False, pmi_score=pmi_score,
            is_proper_noun=False, dep_scope=dep_scope,
            recommendation="KEEP",
            reason=f"High PMI ({pmi_score:.1f} > {_PMI_THRESHOLD}) → fixed collocation.",
        )

    if dep_scope in ("nsubj", "nsubjpass") and pmi_score <= _PMI_THRESHOLD:
        return CompoundAnalysis(
            modifier=modifier, noun=noun,
            wordnet_hit=False, pmi_score=pmi_score,
            is_proper_noun=False, dep_scope=dep_scope,
            recommendation="SPLIT",
            reason="Low PMI; modifier targets subject entity → separate property.",
        )

    # Default: conservative KEEP
    return CompoundAnalysis(
        modifier=modifier, noun=noun,
        wordnet_hit=False, pmi_score=pmi_score,
        is_proper_noun=False, dep_scope=dep_scope,
        recommendation="KEEP",
        reason="Default conservative: insufficient evidence to split.",
    )
