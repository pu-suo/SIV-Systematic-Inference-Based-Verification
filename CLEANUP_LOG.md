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
