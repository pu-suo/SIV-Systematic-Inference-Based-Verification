"""
Frozen configuration for the SIV extraction pipeline.

Every reproducibility-relevant parameter lives here. If you find yourself
passing one of these values as a function argument elsewhere in the code,
that is a bug — route through this module instead.

Primary model is gpt-4o-2024-08-06 because it is a hardcoded snapshot
(not an alias), supports JSON Schema structured output, and has strong
compliance with the SIV extraction schema.
"""
from pathlib import Path

# Model snapshot — hardcoded, never an alias.
PRIMARY_MODEL = "gpt-4o-2024-08-06"

# Sampling — deterministic.
TEMPERATURE = 0.0
SEED = 42
MAX_TOKENS = 1200

# On-disk cache.
CACHE_DIR = Path(".siv_cache")
CACHE_FILE = CACHE_DIR / "extraction_cache.jsonl"
