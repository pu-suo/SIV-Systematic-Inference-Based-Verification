"""Live round-trip tests for the extractor against the frozen LLM.

These tests are gated behind ``@pytest.mark.requires_llm`` and require both
``OPENAI_API_KEY`` to be set and the ``openai`` package to be installed.
They parametrize over the fifteen few-shot gold examples and assert that
the live LLM, when shown the same prompt, returns a structurally-equivalent
extraction for each sentence.

Gate (Phase 2): at least 13 / 15 equivalences pass.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from siv.compiler import compile_canonical_fol
from siv.schema import (
    AtomicFormula,
    Formula,
    SentenceExtraction,
    validate_extraction,
)

_EXAMPLES = json.loads(
    (Path(__file__).parent.parent / "prompts" / "extraction_examples.json").read_text()
)


# ── Structural-equivalence helpers ──────────────────────────────────────────

def _canonicalize_predicates(se: SentenceExtraction) -> dict:
    return {p.name: (p.arity, tuple(p.arg_types)) for p in se.predicates}


def _formula_shape(f: Formula) -> tuple:
    """Shape descriptor ignoring variable names and operand ordering on
    commutative connectives (and, or)."""
    if f.atomic is not None:
        return ("atom", f.atomic.pred, len(f.atomic.args), bool(f.atomic.negated))
    if f.negation is not None:
        return ("neg", _formula_shape(f.negation))
    if f.quantification is not None:
        q = f.quantification
        restrictor_shape = tuple(
            sorted((a.pred, len(a.args), bool(a.negated)) for a in q.restrictor)
        )
        iq_shape = tuple((iq.quantifier,) for iq in q.inner_quantifications)
        return ("quant", q.quantifier, restrictor_shape, iq_shape,
                _formula_shape(q.nucleus))
    if f.connective is not None:
        operand_shapes = [_formula_shape(op) for op in (f.operands or [])]
        if f.connective in ("and", "or"):
            operand_shapes = sorted(operand_shapes, key=repr)
        return ("conn", f.connective, tuple(operand_shapes))
    return ("empty",)


def _equivalent(live: SentenceExtraction, gold: SentenceExtraction) -> bool:
    if _canonicalize_predicates(live) != _canonicalize_predicates(gold):
        return False
    return _formula_shape(live.formula) == _formula_shape(gold.formula)


# ── Live client fixture ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def frozen_client():
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")
    try:
        from openai import OpenAI
    except ImportError:
        pytest.skip("openai package not installed")

    from siv.frozen_client import FrozenClient
    return FrozenClient(OpenAI())


# ── Per-example round-trip test ────────────────────────────────────────────

@pytest.mark.requires_llm
@pytest.mark.parametrize(
    "example",
    _EXAMPLES,
    ids=[ex["sentence"] for ex in _EXAMPLES],
)
def test_roundtrip_matches_gold(example, frozen_client):
    from siv.extractor import extract_sentence

    sentence = example["sentence"]
    gold = SentenceExtraction.model_validate(example["extraction"])
    validate_extraction(gold)

    live = extract_sentence(sentence, frozen_client)
    validate_extraction(live)
    assert _equivalent(live, gold), (
        f"Structural mismatch for {sentence!r}\n"
        f"GOLD: {compile_canonical_fol(gold)}\n"
        f"LIVE: {compile_canonical_fol(live)}"
    )
