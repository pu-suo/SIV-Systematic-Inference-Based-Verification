"""
Frozen configuration for the SIV extraction pipeline.

Every reproducibility-relevant parameter lives here. If you find yourself
passing one of these values as a function argument elsewhere in the code,
that is a bug — route through this module instead.

Primary model is gpt-4o-2024-08-06 because it is a hardcoded snapshot
(not an alias), supports JSON Schema structured output, and has strong
compliance with the SIV extraction schema.

Fallback model is gpt-4-0613 for reproducibility-cross-check runs only.
It is NOT the primary published-metric model.
"""
from pathlib import Path

# Model snapshots — hardcoded, never aliases.
PRIMARY_MODEL = "gpt-4o-2024-08-06"
FALLBACK_MODEL = "gpt-4-0613"

# Sampling — deterministic.
TEMPERATURE = 0.0
SEED = 42
MAX_TOKENS = 1200

# On-disk cache.
CACHE_DIR = Path(".siv_cache")
CACHE_FILE = CACHE_DIR / "extraction_cache.jsonl"


def get_extraction_json_schema() -> dict:
    """
    Return the OpenAI-compatible JSON Schema for the SIV extraction output.

    Derived from siv.schema dataclasses. This schema is passed to the API
    as response_format={"type": "json_schema", "json_schema": {...}} so
    the model is bound to produce structurally valid JSON on every call.
    """
    return {
        "name": "siv_extraction",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["constants", "entities", "facts", "macro_template"],
            "properties": {
                "constants": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["id", "surface"],
                        "properties": {
                            "id": {"type": "string"},
                            "surface": {"type": "string"},
                        },
                    },
                },
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["id", "surface", "entity_type"],
                        "properties": {
                            "id": {"type": "string"},
                            "surface": {"type": "string"},
                            "entity_type": {
                                "type": "string",
                                "enum": ["existential", "universal"],
                            },
                        },
                    },
                },
                "facts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["pred", "args", "negated"],
                        "properties": {
                            "pred": {"type": "string"},
                            "args": {
                                "type": "array",
                                "items": {"type": "string"},
                                "maxItems": 2,  # Tenet 2: unary or binary only
                            },
                            "negated": {"type": "boolean"},
                        },
                    },
                },
                "macro_template": {
                    "type": "string",
                    "enum": [
                        "universal_affirmative",
                        "universal_negative",
                        "existential_affirmative",
                        "existential_negative",
                        "ground_positive",
                        "ground_negative",
                        "conditional",
                        "biconditional",
                    ],
                },
            },
        },
    }
