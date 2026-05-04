# SIV Repo Cleanup Log

This file tracks the pre-EMNLP cleanup operation. It will be removed (or moved
to `docs/`) once the cleanup is complete and the result is in `CLEANUP_RESULT.md`.

## Pre-flight state

- Date: 2026-05-03
- Branch: `main`
- HEAD SHA at start: `008a6fa14cc7b30d5e755b76a9c8e0117a291f44`
- Working tree: clean (`git status --porcelain` empty)
- Remote provider: GitHub
- Origin URL: `https://github.com/pu-suo/SIV-Systematic-Inference-Based-Verification.git`
- Local working dir: `siv-project`
- `gh` CLI: installed, authenticated as `pu-suo`

## Pre-cleanup metrics

Note: macOS `du` lacks GNU `-b`, so sizes are reported in 1024-byte blocks via `du -sk`.

- File count (excluding `.git/`): **426**
- Total size of working tree (excluding `.git/`): **~54,540 KB (~54.5 MB)**
  (Computed as `du -sk .` minus `du -sk .git`: 62,868 − 8,328.)
- `.git/` size: 8,328 KB

## Pre-flight pytest baseline (initial)

`pytest tests/ -x --tb=short` — **1 failed, 409 passed, 28 skipped** in 37.91s.

Failing test:
```
tests/test_stratum_classifier.py::test_s8_below_15_percent_on_train
ModuleNotFoundError: No module named 'scripts.run_folio_evaluation'
```

The referenced module `scripts/run_folio_evaluation.py` was deleted in
commit `81e532c "cleanup old files in preparation for pivot"`, so this is a
pre-existing orphaned test, not a regression introduced by this work.

### Dependency check (before deciding what to remove)

```
grep -rn "stratum_classifier\|load_folio_premise_pairs" --include="*.py"
```

Findings:
- `siv/stratum_classifier.py` is imported by **active code**:
  `scripts/generate_candidates.py:41` —
  `from siv.stratum_classifier import classify_stratum_from_fol`.
  The module is therefore load-bearing for the candidate-generation pipeline
  and **must be kept**.
- `load_folio_premise_pairs` appears **only** inside the failing test function;
  no other reference exists in the repo.
- The other 38 tests in `tests/test_stratum_classifier.py` exercise
  `classify_stratum_from_fol` and `STRATUM_LABELS` directly and are unaffected.

## Stage 0 — Orphaned test removal

Per the dependency check, only the failing test function was excised:

- File: `tests/test_stratum_classifier.py`
- Removed: lines 145–162 (the `# ── Distribution test on full train split ──`
  section comment plus the `test_s8_below_15_percent_on_train` function).
- Rationale: The test imports a script that no longer exists. The module
  it nominally tested (`siv/stratum_classifier.py`) is still load-bearing
  via `scripts/generate_candidates.py` and remains untouched.

### Post-Stage-0 pytest baseline

`pytest tests/ -x --tb=short` — **409 passed, 28 skipped, 0 failed** in 31.67s.

This is the green baseline against which all subsequent cleanup-stage test
runs will be compared.

## Phase B — Archive repo creation and snapshot

- Archive repo: **`https://github.com/pu-suo/SIV-archive`** (private)
- Created via `gh repo create SIV-archive --private --description ...`
- Archive remote configured locally as `archive`.
- Archive README swap: **skipped** (option A) — archive carries the same
  README as the main repo at the snapshot point.

### Snapshot tag

- Tag: `pre-cleanup-snapshot` (annotated)
  - Tag object SHA: `953fa5f9be07bb263672050c36fb7f0db35df74a`
  - Points at commit: `d864f328b9b11fb04f7578b5f5cf4ae26faac89e`
    (`main` head after Stage 0 orphan-test removal)

### Pushes performed by user

- `git push archive --all` → archive `refs/heads/main` = `d864f32` ✓
- `git push archive --tags` → `pre-cleanup-snapshot`, `v1-final`, `v2.0.0` all on archive ✓
- `git push origin pre-cleanup-snapshot` → origin retains tag at `953fa5f`/`d864f32` ✓

(`origin/main` intentionally still at `008a6fa`; user is holding all
origin pushes for the end of cleanup per Phase E.)

### Archive verification

`git ls-remote archive` matches local refs for `main` and all tags.

Archive-critical file presence at the snapshot SHA (verified locally on
`d864f32` which is identical to `archive/main`):

- `siv/extractor.py` — present, 5,715 B
- `prompts/extraction_system.txt` — present, 13,723 B
- `reports/c2_pilots/` — present, 7 files
- `reports/experiments/exp2/.llm_cache/` — present, 48 cached LLM responses

**Verification status: PASSED.**

The `archive` remote is intentionally retained until Phase E confirms cleanup
success (per spec).

## Phase C — Inventory (read-only)

`CLEANUP_INVENTORY.md` written. Five user decision points were raised; user
chose all defaults.

Inventory-time finding (not in any deletion stage): after Stage 3 deletes
`siv/extractor.py`, the only remaining importer of `siv/pre_analyzer.py` is
its own test. The module becomes orphan but harmless. Deferred for a
post-cleanup follow-up rather than expanding Stage 3.

## Phase D — Stage 1: stale documentation

Deleted:
- `archive/lessons.md`
- `archive/perturbation_recipe.md`
- `archive/` (directory; auto-removed once empty)
- `docs/SIV_EXPERIMENTS_CONTEXT.md`

Edited:
- `README.md` — full rewrite. Removed pre-pivot framing and references to
  scripts that no longer exist (`run_folio_evaluation.py`,
  `compute_baseline_metrics.py`, `soft_alignment_diagnostics.py`) and to v1
  components being deleted in Stage 3 (`extractor.py`, `frozen_client.py`,
  `frozen_config.py`, `test_suite_generator.py`, `pre_analyzer.py`). New
  README leads with the deterministic-gold-parser framing and lists the
  reproduction commands for the locked headline / Exp C1 / nulls.
  The "Prior exploration" archive pointer is held until Phase E.

## Phase D — Stage 2: retired pilots and superseded investigations

Inventory predicted ~14 file deletions; actual was **169**, triggering the
spec's >50-file sanity-check stop. Verification pass run before commit:

- All 155 extras live in `reports/c2_pilots/.cache/` — a hidden cache
  subdirectory under the c2_pilots tree the user already approved deleting
  in full. (My Phase C `ls` skipped dotfiles, hence the under-count.)
- Cache filenames are hash-keyed; none reference `path1`, `path1_hard`, or
  `investigation_4` tokens.
- No `.cache/` files outside `reports/c2_pilots/.cache/` were touched.
- Locked-null artifacts confirmed untouched: `path1/`, `path1_hard/`, and
  `investigation_4_*` files do not appear in the staged deletions.
- `path1_hard/step5_main_results.json` raw arrays intact: 3 models × 5
  conditions in `raw_results`.

User confirmed Path 1 (commit all 169 deletions as a single Stage 2 commit).

Deleted (169 files):
- `reports/c2_pilots/` (entire tree, 162 files: 7 top-level + 155 in `.cache/`)
- `reports/c2_investigations/investigation_1_load_bearing.{json,md}`
- `reports/c2_investigations/investigation_2_metric_sensitivity.{json,md}`
- `reports/c2_investigations/investigation_3_hand_perturbation.{json,md}`
- `reports/c2_investigations/c2_investigations_results.md`

KEPT (Hard Rule 3):
- `reports/c2_investigations/investigation_4_effect_size.{json,md}`
- `reports/c2_investigations/path1/` (10 files)
- `reports/c2_investigations/path1_hard/` (10 files)

## Phase D — Stage 3: LLM-extraction infrastructure

Hard Rule 5 final check (`pytest tests/ --collect-only`) caught a missed
dependency: `prompts/extraction_examples.json` was used as test fixture
data by three load-bearing v2 tests (`test_scorer.py`,
`test_contrastive_generator.py`, `test_soundness_invariants.py`), not just
the v1 cluster.

User chose Path B: relocate the corpus to `tests/data/` and split the work
into two commits.

### Pre-Stage-3 refactor (commit `1dc0be2`)

`refactor: relocate extraction_examples to tests/data`

- `git mv prompts/extraction_examples.json tests/data/extraction_examples.json`
  (preserves blame/log on the corpus content).
- Updated three test path references (`test_scorer.py:29`,
  `test_contrastive_generator.py:40`, `test_soundness_invariants.py:39`)
  to load from `Path(__file__).parent / "data" / ...`.
- `tests/data/` is gitignored at `.gitignore:44` (`data/`), but the file
  is tracked as a rename so the ignore rule doesn't re-fire (same as the
  pre-existing `tests/data/invariant_corpus.json`).

### Stage 3 deletions (61 changes total: 60 deletions + 1 edit)

Deleted:
- `prompts/extraction_system.txt` and the now-empty `prompts/` directory
- `siv/extractor.py`, `siv/json_schema.py`, `siv/frozen_client.py`,
  `siv/frozen_config.py`, `siv/test_suite_generator.py`, `siv/__main__.py`
- `scripts/generate_siv_tests.py`, `scripts/generate_folio_test_suites.py`
- `tests/test_extractor.py`, `tests/test_frozen_client.py`,
  `tests/test_extraction_roundtrip.py`
- `reports/experiments/exp2/.llm_cache/` (48 cached LLM responses)

Edited:
- `tests/test_schema.py` — dropped `from siv.json_schema import …` import,
  removed 4 test functions and the `# ── JSON Schema derivation` section
  comment (lines 312–357 in the pre-edit file).

### Hard Rule 5 collect-only check

`pytest tests/ --collect-only` after staging: **396 tests collected, 0
errors**. Drop from 438 (Stage 0 baseline) accounted for:

- 1 test removed in Stage 0 (orphaned stratum test)
- 9 tests in `test_extractor.py`
- 23 tests in `test_extraction_roundtrip.py` (all `requires_llm`-gated)
- 5 tests in `test_frozen_client.py`
- 4 tests in `test_schema.py` (json_schema-specific)
- Total removed: 42 → 438 − 42 = 396 ✓

### Stage 3 follow-up

`tests/test_main_dispatcher.py` was missed by the Phase C dependency
grep because it exercised `siv/__main__.py` via subprocess
(`python -m siv`) rather than via Python `import`. Same pattern as
Stage 0's stratum_classifier orphan. Lesson: dependency checks must
include subprocess-based invocations, not just Python import
statements.

Deleted in commit (separate from Stage 3): `tests/test_main_dispatcher.py`
(3 tests, all subprocess invocations of the deleted dispatcher).

Post-cleanup pytest: **388 passed, 5 skipped, 0 failed.** (Drop from 396
collected to 393 reflects the 3 dispatcher tests; the 5 remaining
skipped are pre-existing `vampire_required` skips in
`test_contrastive_generator.py`.)





