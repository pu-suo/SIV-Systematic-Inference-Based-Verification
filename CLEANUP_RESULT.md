# SIV Repo Cleanup — Result

The pre-EMNLP cleanup is complete. This file records what was preserved,
what was removed, and where to find the pre-cleanup state.

## Archive

The full pre-cleanup repo state (including the LLM-extraction pipeline,
retired pilots, and exploratory work) is preserved at
**<https://github.com/pu-suo/SIV-archive>**, tag `pre-cleanup-snapshot`,
which points at commit `d864f328b9b11fb04f7578b5f5cf4ae26faac89e`.

The same tag also exists on `origin` for redundancy.

## Metrics

| | Pre-cleanup | Post-cleanup | Δ |
| --- | --- | --- | --- |
| Files (excl. `.git/`) | 426 | 170 | **−256 (−60%)** |
| Working-tree size | ~54.5 MB | ~53.0 MB | −1.5 MB (−3%) |
| Working-tree size, excl. 43 MB `vampire` binary | 11.1 MB | 9.7 MB | **−1.5 MB (−13%)** |
| pytest collected | 438 | 393 | −45 |
| pytest passed | 409 | 388 | −21 |
| pytest skipped | 28 | 5 | −23 (mostly `requires_llm`-gated) |
| pytest failed | 1 (pre-existing) | 0 | — |

## Commits since the snapshot

```
c243cd9 cleanup reports housekeeping (Stage 5/5)
bc1fee2 cleanup stale scripts (Stage 4/5)
7e551e6 cleanup: remove orphaned test for deleted siv/__main__.py CLI dispatcher
e511414 cleanup: remove LLM-extraction infrastructure (Stage 3/5)
1dc0be2 relocate extraction_examples to tests/data
6c8c689 cleanup retired pilots (Stage 2/5)
624f65e cleanup stale docs (Stage 1/5)
d864f32 remove orphaned stratum test                 (Stage 0; pre-flight fix)
```

## What was removed and why

### Stage 0 — pre-flight orphaned test
- `tests/test_stratum_classifier.py::test_s8_below_15_percent_on_train`
  (the function only) — imported the previously-deleted
  `scripts/run_folio_evaluation.py`. Other 38 tests in the file unchanged
  (they exercise `siv/stratum_classifier.py`, which is still load-bearing
  via `scripts/generate_candidates.py`).

### Stage 1 — stale documentation (commit `624f65e`)
- `archive/lessons.md`, `archive/perturbation_recipe.md` — pre-pivot retro
  notes; archive directory removed.
- `docs/SIV_EXPERIMENTS_CONTEXT.md` — pre-pivot context dump.
- `README.md` rewritten to lead with the deterministic-gold-parser framing.
  Removed references to deleted scripts and to v1 components.

### Stage 2 — retired pilots and superseded investigations (commit `6c8c689`)
- `reports/c2_pilots/` (entire tree, 162 files: 7 top-level result files
  + 155 hidden LLM cache files in `.cache/`).
- `reports/c2_investigations/investigation_1_load_bearing.{json,md}`
- `reports/c2_investigations/investigation_2_metric_sensitivity.{json,md}`
- `reports/c2_investigations/investigation_3_hand_perturbation.{json,md}`
- `reports/c2_investigations/c2_investigations_results.md`

KEPT (Hard Rule 3): `investigation_4_*`, `path1/`, `path1_hard/`.

### Refactor — relocate extraction corpus (commit `1dc0be2`)
- `git mv prompts/extraction_examples.json tests/data/extraction_examples.json`
- Updated three test path references (`test_scorer.py`,
  `test_contrastive_generator.py`, `test_soundness_invariants.py`).
- The corpus is dual-purpose: it was the v1 few-shot prompt, but it's
  also load-bearing fixture data for v2 soundness/scorer/contrastive
  tests. Moving to `tests/data/` keeps it as test data without
  preserving the misleading top-level `prompts/` directory.

### Stage 3 — LLM-extraction infrastructure (commits `e511414` + `7e551e6`)
- `prompts/extraction_system.txt` and the `prompts/` directory.
- `siv/extractor.py`, `siv/json_schema.py`, `siv/frozen_client.py`,
  `siv/frozen_config.py`, `siv/test_suite_generator.py`,
  `siv/__main__.py` (the CLI dispatcher).
- `scripts/generate_siv_tests.py`, `scripts/generate_folio_test_suites.py`
  (v1 generators that originally produced `reports/test_suites/test_suites.jsonl`,
  which is itself a frozen artifact and is **kept**).
- `tests/test_extractor.py`, `tests/test_frozen_client.py`,
  `tests/test_extraction_roundtrip.py`, `tests/test_main_dispatcher.py`
  (the last one is the follow-up; it exercised `siv/__main__.py` via
  subprocess and was missed by the import-only Phase C grep).
- `reports/experiments/exp2/.llm_cache/` (48 cached LLM responses).
- `tests/test_schema.py` — dropped `from siv.json_schema import …` and 4
  `test_json_schema_*` functions (lines 312–357 in the pre-edit file).

### Stage 4 — stale scripts (commit `bc1fee2`)
- `scripts/c2_pilot_run.py`, `scripts/c2_pilots.py`
- `scripts/c2_investigation_1.py`, `c2_investigation_2.py`, `c2_investigation_3.py`
- `scripts/c2_path1_hard_step5_main.py` (v1; the optimized v2 sibling
  `c2_path1_hard_step5_main_v2.py` is the live Path 1-Hard runner)

### Stage 5 — housekeeping (commit `c243cd9`)
- `git mv reports/COMPREHENSIVE_RESULTS.md docs/COMPREHENSIVE_RESULTS.md`
- `reports/stage2_self_score.json`, `reports/stage3_perturbation_ordering.json`
- `scripts/stage2_validation.py`, `scripts/stage3_perturbation_validation.py`
- Local cleanup of `__pycache__/`, `*.pyc`, `.DS_Store` (45 items;
  untracked, so not in any commit).

## What was preserved (and why)

All paper-supporting artifacts are intact:

- **Stage 1 — parser coverage:** `reports/parser_coverage_report.json`
  (94.2% / 99.94%).
- **Locked test-suite artifact:** `reports/test_suites/test_suites.jsonl`
  (1,471 premises, frozen).
- **Exp 1, 2, 3 (Exp A, B, D):** all of `reports/experiments/exp{1,2,3}/`
  except the v1 LLM cache deleted in Stage 3.
- **Stage 4 rescore (locked headline):** all of `reports/stage4/`
  (`stage4b_regeneration.json`, `rescore_exp1.json`, `rescore_exp2.json`,
  `per_premise_deltas.jsonl`).
- **Exp C1:** `reports/c1/` (coarse 0.81 / fine 0.29).
- **Pre-registered nulls:** `reports/c2_investigations/investigation_4_*`,
  `path1/`, `path1_hard/`.
- **Hand-corrected gold annotations (Exp D, Hard Rule 4):** *both* copies
  preserved — `docs/corrections_template.md` (curated) and
  `reports/experiments/exp3/corrections_template.md` (original; differs
  by 117 lines).
- **Frozen translation prompt:** `docs/translation_prompt.md`.
- **Canonical spec:** `docs/SIV.md`.
- **Vampire binary:** `./vampire`.
- **Soundness invariants test (the floor):** `tests/test_soundness_invariants.py`.
- **All `siv/` modules** load-bearing for the v2 pipeline:
  `fol_parser`, `gold_suite_generator`, `compiler`, `contrastive_generator`,
  `scorer`, `vampire_interface`, `aligner`, `schema`, `fol_utils`,
  `stratum_classifier`, `nltk_perturbations`, `invariants`, `malls_le`,
  `brunello_lt`.

## Deferred / known issues (not blocking)

1. **`siv/pre_analyzer.py` is now an orphan.** Its only consumer was the
   deleted `siv/extractor.py`, plus its own test. Harmless (the test still
   passes) but dead weight. Suggested follow-up: delete
   `siv/pre_analyzer.py` and `tests/test_pre_analyzer.py` together.

2. **`docs/COMPREHENSIVE_RESULTS.md` has dangling references.** Its
   "Key Files" table still points at `reports/c2_pilots/pilot_results.json`,
   `reports/c2_investigations/investigation_*.json` (now resolves only to
   `investigation_4_*`), `reports/stage2_self_score.json`, and
   `reports/stage3_perturbation_ordering.json` — all removed. Edit when
   revising the doc for paper writing.

3. **Phase C dependency-grep methodology lesson.** Stage 0 and the Stage 3
   follow-up were both orphan tests for modules removed earlier. Stage 0's
   test was caught by pytest baseline; the Stage 3 follow-up
   (`tests/test_main_dispatcher.py`) was missed by the import-only grep
   because it invoked the dispatcher via `subprocess`. For future cleanups,
   dependency checks should also grep for filenames as bare strings (catches
   subprocess invocations and string references in docs/configs).

## Reproducibility check

Final `pytest tests/ -x --tb=short`:
**388 passed, 5 skipped, 0 failed.** The 5 skipped tests are the
pre-existing `vampire_required` skips in `test_contrastive_generator.py`.

## What you need to push to origin

The cleanup commits and the snapshot tag are not yet on `origin`:

```bash
git push origin main
git push origin pre-cleanup-snapshot
```

(The `archive` remote retains everything you already pushed there; once
you've pushed `origin`, you can run `git remote remove archive` to keep
your `git remote -v` output clean for reviewers.)
