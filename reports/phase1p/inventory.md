# Phase 1P Artifact Inventory

Generated: 2026-04-30

## SIV Pipeline Caches

| Cache | Entries | FOLIO Train Coverage | Notes |
|---|---|---|---|
| `.siv_cache/extraction_cache.jsonl` | 2798 | 1658/1677 (98.9%) | Only 19 new extractions needed |
| `.siv_cache/translation_cache.jsonl` | 3354 | 1677/1677 (100%) | GPT-4o + GPT-4o-mini, not needed for perturbation experiment |

## Perturbation Candidates

| Item | Status |
|---|---|
| `reports/human_study/candidates.jsonl` | 63 rows, 10 premises only — too small, regenerate at scale |
| Candidate types present | C_gold, C_model_strong, C_model_weak, C_pert_tierA/B/C/D |
| Fields present | bleu_vs_gold, parse_valid, stratum, perturbation_operator |

## Test Suites

| Item | Status |
|---|---|
| Saved test suites on disk | **None** — need to run `generate_folio_test_suites.py` |
| Generation script | Exists at `scripts/generate_folio_test_suites.py`, uses extraction cache |

## Phase 1 Data (Pillar 1)

| File | Rows | Status |
|---|---|---|
| `reports/phase1/entailment_results.jsonl` | 3003 | Complete |
| `reports/phase1/metric_scores.jsonl` | 3003 | Complete (all metrics) |
| `reports/phase1/correlation_results.json` | — | Complete |
| `reports/phase1/failure_analysis.json` | — | Complete |
| `reports/phase1/localization_results.json` | — | Complete |

## Modules

| Module | Status |
|---|---|
| `siv/malls_le.py` | Exists, tested |
| `siv/brunello_lt.py` | Exists, tested (renamed to Z3-equiv in paper) |
| `siv/aligner.py` | Hardcoded MiniLM-L6-v2; needs parametrization for Ablation 3 |
| `siv/nltk_perturbations.py` | 11 operators across 4 tiers |

## Reuse Assessment

- Extraction cache: **reuse** (98.9% coverage)
- Translation cache: **not needed** (dropping model translations)
- Existing candidates: **regenerate** (only 10 premises, need ~1600)
- Phase 1 data: **reuse as-is** (Pillar 1)
- All siv/ modules: **reuse**
- All scripts: **reuse** (generate_candidates, score_candidates, generate_folio_test_suites)

**Estimated reuse rate: ~70%**

## Test-Set Integrity

- Evaluation: FOLIO train (not touched during Phase 0)
- Development: FOLIO validation (Phase 0 pipeline work)
- Threshold 0.6: intended calibration against validation (see aligner.py:226)
- Perturbation operators: designed against validation
