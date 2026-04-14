"""
Extractor (SIV.md §6.3, C5).

Calls a frozen LLM bound to the Pydantic-derived JSON Schema, parses the
response into a ``SentenceExtraction``, validates it (§7 C2/C3), and enforces
the pre-analyzer tripwires. On any ``SchemaViolation``, retries exactly once
with the violation message appended to the system prompt; if the retry fails,
raises to the caller. No second retry. No silent acceptance.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, List, Optional

from pydantic import ValidationError

from siv.pre_analyzer import RequiredFeatures, compute_required_features
from siv.schema import (
    AtomicFormula,
    Formula,
    SchemaViolation,
    SentenceExtraction,
    TripartiteQuantification,
    validate_extraction,
)

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_SYSTEM_PROMPT_PATH = _PROMPTS_DIR / "extraction_system.txt"
_EXAMPLES_PATH = _PROMPTS_DIR / "extraction_examples.json"


# ── Prompt loading ──────────────────────────────────────────────────────────

def load_system_prompt() -> str:
    return _SYSTEM_PROMPT_PATH.read_text()


def load_few_shot_messages() -> List[dict]:
    """Return few-shot messages for the extractor.

    The examples file is a JSON list of {"sentence": str, "extraction": dict}
    entries. Each entry becomes a user/assistant pair: the user content is
    the sentence; the assistant content is the JSON-serialized extraction.
    """
    raw = json.loads(_EXAMPLES_PATH.read_text())
    messages: List[dict] = []
    for ex in raw:
        messages.append({"role": "user", "content": ex["sentence"]})
        messages.append({
            "role": "assistant",
            "content": json.dumps(ex["extraction"], sort_keys=True),
        })
    return messages


# ── Tripwire walker ─────────────────────────────────────────────────────────

def _walk_formula(f: Formula, visitor: Callable[[Formula], None]) -> None:
    """Recursively walk ``f`` invoking ``visitor`` on every node (including
    quantification restrictor atoms lifted into Formula wrappers)."""
    visitor(f)
    if f.atomic is not None:
        return
    if f.negation is not None:
        _walk_formula(f.negation, visitor)
        return
    if f.quantification is not None:
        q = f.quantification
        for atom in q.restrictor:
            visitor(Formula(atomic=atom))
        _walk_formula(q.nucleus, visitor)
        return
    if f.connective is not None:
        for op in f.operands or []:
            _walk_formula(op, visitor)


def _has_populated_restrictor(formula: Formula) -> bool:
    found = [False]

    def visit(node: Formula) -> None:
        if found[0]:
            return
        if node.quantification is not None and len(node.quantification.restrictor) > 0:
            found[0] = True

    _walk_formula(formula, visit)
    return found[0]


def _has_any_negation(formula: Formula) -> bool:
    found = [False]

    def visit(node: Formula) -> None:
        if found[0]:
            return
        if node.negation is not None:
            found[0] = True
        if node.atomic is not None and node.atomic.negated:
            found[0] = True

    _walk_formula(formula, visit)
    return found[0]


def _enforce_tripwires(extraction: SentenceExtraction, req: RequiredFeatures) -> None:
    if req.requires_restrictor and not _has_populated_restrictor(extraction.formula):
        raise SchemaViolation("restrictor required but missing")
    if req.requires_negation and not _has_any_negation(extraction.formula):
        raise SchemaViolation("negation required but missing")


# ── Extractor ───────────────────────────────────────────────────────────────

def extract_sentence(sentence: str, client) -> SentenceExtraction:
    """Extract one sentence into a validated ``SentenceExtraction`` (C5).

    Retries exactly once on ``SchemaViolation`` from validation or tripwire
    enforcement. A second failure raises to the caller. No infinite retries.
    """
    system_prompt = load_system_prompt()
    few_shots = load_few_shot_messages()
    req = compute_required_features(sentence)

    extraction, error = _attempt(sentence, client, system_prompt, few_shots, req)
    if error is None:
        return extraction

    retry_prompt = (
        system_prompt
        + "\n\n---\nRETRY. The previous response violated the schema or "
        "tripwire check with: " + str(error) + ". Fix the violation and "
        "produce a valid extraction."
    )
    extraction, error = _attempt(sentence, client, retry_prompt, few_shots, req)
    if error is not None:
        raise error
    return extraction


def _attempt(
    sentence: str,
    client,
    system_prompt: str,
    few_shots: List[dict],
    req: RequiredFeatures,
) -> tuple[Optional[SentenceExtraction], Optional[SchemaViolation]]:
    try:
        data, _ = client.extract(
            system_prompt=system_prompt,
            few_shot_messages=few_shots,
            user_content=sentence,
        )
        extraction = SentenceExtraction.model_validate(data)
        validate_extraction(extraction)
        _enforce_tripwires(extraction, req)
        return extraction, None
    except ValidationError as e:
        return None, SchemaViolation(f"Pydantic validation failed: {e}")
    except SchemaViolation as e:
        return None, e
