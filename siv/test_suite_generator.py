"""
SIV test suite generation from a single natural language sentence.

Composes the extraction, compilation, and contrastive generation steps into
a single callable that produces a frozen, serializable test suite dictionary.

Public API
----------
generate_test_suite(nl, client, timeout_s) -> dict
    NL sentence → complete SIV test suite with positives, contrastives,
    canonical FOL, witness axioms, and structural classification.

serialize_test_suite(suite_dict) -> str
    Serialize a test suite dict to a JSON string.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from siv.compiler import compile_canonical_fol, compile_sentence_test_suite
from siv.contrastive_generator import classify_structure, derive_witness_axioms
from siv.extractor import extract_sentence
from siv.schema import SentenceExtraction, SchemaViolation


def generate_test_suite(
    nl: str,
    client,
    timeout_s: int = 10,
) -> Dict[str, Any]:
    """Generate a complete SIV test suite from a natural language sentence.

    Steps:
      1. LLM extraction → ``SentenceExtraction``
      2. Compile canonical FOL (Path A)
      3. Compile test suite with positives + contrastives (Path B + Vampire)
      4. Derive witness axioms
      5. Classify structural class

    Parameters
    ----------
    nl : str
        The natural language sentence to analyze.
    client : FrozenClient
        LLM client (wrapping OpenAI) for extraction.
    timeout_s : int
        Vampire timeout per entailment check (default 10).

    Returns
    -------
    dict
        Serializable dict with keys: ``nl``, ``canonical_fol``,
        ``structural_class``, ``positives``, ``contrastives``,
        ``witness_axioms``, ``extraction_json``.

    Raises
    ------
    SchemaViolation
        If the LLM extraction fails validation after retry.
    """
    # 1. Extract
    extraction = extract_sentence(nl, client)

    # 2. Compile canonical FOL
    canonical_fol = compile_canonical_fol(extraction)

    # 3. Compile test suite (positives + contrastives via Vampire)
    suite = compile_sentence_test_suite(extraction, timeout_s=timeout_s)

    # 4. Derive witness axioms
    witness_axioms = derive_witness_axioms(extraction)

    # 5. Classify structure
    structural_class = classify_structure(extraction)

    # Serialize
    positives = [
        {"fol": t.fol, "kind": t.kind}
        for t in suite.positives
    ]
    contrastives = [
        {"fol": t.fol, "kind": t.kind, "mutation_kind": t.mutation_kind}
        for t in suite.contrastives
    ]

    return {
        "nl": nl,
        "canonical_fol": canonical_fol,
        "structural_class": structural_class,
        "positives": positives,
        "contrastives": contrastives,
        "witness_axioms": witness_axioms,
        "extraction_json": extraction.model_dump(),
    }


def serialize_test_suite(suite_dict: Dict[str, Any]) -> str:
    """Serialize a test suite dict to a JSON string (one line)."""
    return json.dumps(suite_dict, default=str)


def load_test_suite(line: str) -> Dict[str, Any]:
    """Load a test suite dict from a JSON string."""
    return json.loads(line)
