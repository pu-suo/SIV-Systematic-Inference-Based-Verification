"""
Derive the API-level JSON Schema for SentenceExtraction from the Pydantic model.

This is the single source of truth for the JSON Schema passed to the LLM's
structured-output / response_format channel. Hand-rolled JSON Schemas are
forbidden anywhere in the codebase (SIV.md §5, §6.2.7).

Derivation steps:
  1. SentenceExtraction.model_json_schema() to get the raw schema.
  2. Inline all non-recursive $refs. Recursive $refs (Formula references
     itself via `negation`, `operands`, and `TripartiteQuantification.nucleus`)
     are preserved as $ref, and their $defs entries are retained at the root
     of the output. OpenAI strict mode permits recursion via $ref to a
     colocated $defs entry; fully inlining a self-referential type is
     mathematically impossible.
  3. Set additionalProperties: false on every object.
  4. Mark every property required (optional fields express null via union).
  5. Strip title / description / default.
"""
from __future__ import annotations

import copy
import json
from typing import Any

from siv.schema import SentenceExtraction


_STRIP_KEYS = ("title", "description", "default")
_REF_PREFIX = "#/$defs/"


def _key_of(ref: str) -> str:
    if not ref.startswith(_REF_PREFIX):
        raise ValueError(f"Unexpected $ref target: {ref}")
    return ref[len(_REF_PREFIX):]


def _inline(node: Any, defs: dict, stack: list, kept: set) -> Any:
    if isinstance(node, dict):
        if "$ref" in node and len(node) == 1:
            key = _key_of(node["$ref"])
            if key in stack:
                # Cycle — preserve $ref; mark def for retention.
                kept.add(key)
                return {"$ref": node["$ref"]}
            stack.append(key)
            expanded = _inline(copy.deepcopy(defs[key]), defs, stack, kept)
            stack.pop()
            return expanded
        return {k: _inline(v, defs, stack, kept) for k, v in node.items()}
    if isinstance(node, list):
        return [_inline(x, defs, stack, kept) for x in node]
    return node


def _is_object_schema(node: dict) -> bool:
    t = node.get("type")
    if t == "object":
        return True
    return "properties" in node


def _tighten(node: Any) -> None:
    if isinstance(node, dict):
        for k in _STRIP_KEYS:
            node.pop(k, None)
        if _is_object_schema(node):
            node["additionalProperties"] = False
            props = node.get("properties", {})
            if props:
                node["required"] = list(props.keys())
        for v in node.values():
            _tighten(v)
    elif isinstance(node, list):
        for item in node:
            _tighten(item)


def derive_extraction_schema() -> dict:
    """Return the OpenAI-compatible JSON Schema derived from SentenceExtraction.

    Deterministic: identical inputs produce byte-identical outputs across runs.
    """
    raw = SentenceExtraction.model_json_schema()
    defs = raw.pop("$defs", {})
    kept: set = set()
    inlined = _inline(raw, defs, [], kept)
    # Retain $defs only for refs that appear in cycles. Expand those defs'
    # bodies too (inlining inside them, which will again hit cycles and retain).
    if kept:
        inlined["$defs"] = {}
        # Iterate until fixpoint: expanding a kept def may reveal more kept refs.
        to_process = list(kept)
        processed: set = set()
        while to_process:
            name = to_process.pop()
            if name in processed:
                continue
            processed.add(name)
            stack = [name]
            body = _inline(copy.deepcopy(defs[name]), defs, stack, kept)
            inlined["$defs"][name] = body
            for new_name in kept:
                if new_name not in processed:
                    to_process.append(new_name)
    _tighten(inlined)
    # Round-trip through json with deterministic key ordering.
    return json.loads(json.dumps(inlined))
