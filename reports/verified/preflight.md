# Preflight checks — PART 0

Date: 2026-05-04

## A. Working tree
`git status --porcelain`: clean (empty output).

## B. Commit position
HEAD: `21f89f4 docs: relocate CLEANUP_RESULT.md to docs/` — descendant of `37f3001 finalize cleanup record`.

Recent commits:
```
21f89f4 docs: relocate CLEANUP_RESULT.md to docs/
37f3001 finalize cleanup record
c243cd9 cleanup reports housekeeping (Stage 5/5)
bc1fee2 cleanup stale scripts (Stage 4/5)
7e551e6 cleanup: remove orphaned test for deleted siv/__main__.py CLI dispatcher
```

## C. Pytest
`pytest tests/ --tb=short -q`: **388 passed, 5 skipped, 0 failed** (3 warnings unrelated, all about `TestSuite` Pydantic class name collision with pytest collection — benign).

## D. Source-JSON existence
- OK reports/parser_coverage_report.json
- OK reports/stage4/rescore_exp1.json
- OK reports/stage4/rescore_exp2.json
- OK reports/stage4/stage4b_regeneration.json
- OK reports/experiments/exp2/rank_correlation.json
- OK reports/c1/c1_diagnostic_structure.json
- OK reports/c2_investigations/investigation_4_effect_size.json
- OK reports/c2_investigations/path1/step3_pilot.json
- OK reports/c2_investigations/path1_hard/step5_main_results.json
- OK reports/experiments/exp3/broken_gold_pool.jsonl
- OK reports/experiments/exp3/run_metadata.json

## E. Corrections artifacts
- OK docs/corrections_template.md (curated — canonical for Exp D)
- OK reports/experiments/exp3/corrections_template.md (original)

## F. Cleanup-removed JSONs (sanctioned secondary-source path)
- reports/stage2_self_score.json — DELETED in Stage 5; numbers will be read from docs/COMPREHENSIVE_RESULTS.md.
- reports/stage3_perturbation_ordering.json — DELETED in Stage 5; same.
- OK docs/COMPREHENSIVE_RESULTS.md (secondary source) present.

PREFLIGHT OK, proceeding to PART 1
