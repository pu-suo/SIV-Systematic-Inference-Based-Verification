# Changelog

## Stage 3 (current)

### Added
- Frozen extraction pipeline: `siv/frozen_config.py`, `siv/frozen_client.py`,
  `.siv_cache/`. All API calls pin `gpt-4o-2024-08-06`, seed=42,
  temperature=0.0, and bind output to a JSON Schema derived from
  `siv/schema.py`.
- `scripts/siv_score.py` — CLI Evaluator with human and JSON output.
- `scripts/siv_generate.py` — CLI Generator with `--compare-to-gold` mode.
- `siv/generator.py`, `siv/invariants.py` — the Generator and its five
  programmatic invariants.
- `prompts/generation_system.txt`, `prompts/generation_examples.json`.
- `tests/test_soundness_tripwires.py` — mechanical enforcement of Stage 3
  philosophical commitments.
- `tests/test_metric_properties.py` — boundedness, determinism,
  short-circuits, and canonical-compilation identity properties.
- `tests/test_generator.py`, `tests/test_invariants.py`,
  `tests/test_frozen_client.py`, `tests/test_siv_score_script.py`,
  `tests/test_siv_generate_script.py`.

### Changed
- `siv/verifier.py`: `strict_mode` parameter removed. New parameter
  `unresolved_policy: Literal["raise", "exclude"]` with default `"raise"`.
- `siv/schema.py`: `VerificationResult.partial_credits` field removed.
  `siv_score` property short-circuits on `extraction_invalid` and handles
  precision-only / recall-only cases correctly.
- `siv/extractor.py`: routes all API calls through `FrozenClient`. The
  `model` parameter has been removed from public APIs.
- `prompts/extraction_system.txt`: ternary-fact rule removed; new
  `NEO-DAVIDSONIAN FORM` section added with ditransitive decomposition
  rules.
- `prompts/extraction_examples.json`: new ditransitive example; any
  ternary-arity examples fixed to binary decomposition.
- `siv/compiler.py::_compile_from_extraction`: positive-test dedup now
  preserves the most specific `test_type` tag.

### Removed
- `siv/partial_credit.py` (Tenet 1 cleanup).
- `data/perturbation_map.json` (unreferenced since Fix D1+D2).
- `USE_PARTIAL_CREDIT` notebook variable and all `strict_mode` arguments.

### Deprecated (kept but not a published metric path)
- `siv/vllm_backend.py` — now explicitly marked as not producing valid
  SIV scores.
