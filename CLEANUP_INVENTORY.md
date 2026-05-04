# SIV Repo Cleanup Inventory (Phase C, read-only)

This file enumerates every cleanup candidate and groups them by deletion
stage, with confidence (`yes` / `no` / `maybe`) and a one-line reason.

Stages match the spec:
- **Stage 1** — stale documentation
- **Stage 2** — retired pilot/exploratory artifacts
- **Stage 3** — LLM-extraction infrastructure (with dependency checks)
- **Stage 4** — stale scripts
- **Stage 5** — reports housekeeping

Nothing has been deleted. The user must approve stages (or files within a
stage) before Phase D executes.

---

## Top-level inventory (orientation)

| Path | Verdict | Notes |
| --- | --- | --- |
| `README.md` | **edit, keep** | Heavily pre-pivot. Describes v1 LLM-extraction pipeline as the architecture; references several scripts that no longer exist (`run_folio_evaluation.py`, `compute_baseline_metrics.py`, `soft_alignment_diagnostics.py`). Needs a Stage 1 rewrite to foreground the deterministic-gold-parser framing. |
| `requirements.txt`, `conftest.py`, `.gitignore`, `.env.example` | **keep** | Repo plumbing. |
| `.env`, `.DS_Store`, `__pycache__/`, `.pytest_cache/`, `.siv_cache/` | n/a | All gitignored. Local-only Stage 5 housekeeping. |
| `vampire` (43 MB binary) | **keep** | Used by `siv/vampire_interface.py`; required by every entailment check. |
| `CLEANUP_LOG.md`, `CLEANUP_INVENTORY.md` | **keep (transient)** | Will be removed at Phase E (or moved into `docs/`). |
| `docs/`, `archive/`, `prompts/`, `reports/`, `scripts/`, `siv/`, `tests/` | mixed | Detailed below. |

---

## Stage 1 — Stale documentation

| File | Action | Confidence | Reason |
| --- | --- | --- | --- |
| `archive/lessons.md` | delete | confident | Pre-pivot retro notes. Spec explicitly lists `archive/` for full removal. Preserved at snapshot. |
| `archive/perturbation_recipe.md` | delete | confident | Pre-pivot recipe doc. Same as above. |
| `archive/` (the directory itself) | delete | confident | Empties out after the two files above. |
| `docs/SIV_EXPERIMENTS_CONTEXT.md` | delete | confident | Pre-pivot session context (29 KB). Spec explicitly lists. Preserved at snapshot. |
| `README.md` | **edit in place** | confident | Rewrite to lead with the deterministic-gold-parser framing. Also remove or fix references to deleted scripts (`run_folio_evaluation.py`, `compute_baseline_metrics.py`, `soft_alignment_diagnostics.py`) and to v1 components being deleted in Stage 3 (`extractor.py`, `frozen_client.py`, etc.). Will show a diff before committing. The spec's requested "Prior exploration" pointer to the archive will be added in Phase E once the cleanup is verified. |

**Files in `docs/` that are NOT candidates (kept):**
- `docs/SIV.md` (101 KB canonical spec) — load-bearing reference.
- `docs/translation_prompt.md` — frozen NL→FOL prompt for the human-study models. Load-bearing.
- `docs/corrections_template.md` — **Hard Rule 4**: contains the 30 hand-corrected FOLIO gold annotations. KEEP. (See note on the second copy under Stage 5.)

**Other root-level `*_CONTEXT*.md` / `*_HANDOFF*.md` / `*_QUICK_REFERENCE*.md`:** none found. The only context doc is `docs/SIV_EXPERIMENTS_CONTEXT.md` already listed above.

---

## Stage 2 — Retired pilot/exploratory artifacts

| File | Action | Confidence | Reason |
| --- | --- | --- | --- |
| `reports/c2_pilots/pilot1_results.jsonl` | delete | confident | Pilot run pre-dating pre-registered Investigations. |
| `reports/c2_pilots/pilot2_results.jsonl` | delete | confident | Same. |
| `reports/c2_pilots/pilot3_results.jsonl` | delete | confident | Same. |
| `reports/c2_pilots/pilot4_results.jsonl` | delete | confident | Same. |
| `reports/c2_pilots/pilot_raw.json` | delete | confident | Same. |
| `reports/c2_pilots/pilot_report.json` | delete | confident | Same. |
| `reports/c2_pilots/pilot_results.json` | delete | confident | Same. |
| `reports/c2_pilots/` (directory) | delete | confident | Empties after the seven files above. |
| `reports/c2_investigations/investigation_1_load_bearing.json` | delete | confident | Superseded by Investigation 4. Spec explicit. |
| `reports/c2_investigations/investigation_1_load_bearing.md` | delete | confident | Same. |
| `reports/c2_investigations/investigation_2_metric_sensitivity.json` | delete | confident | Same. |
| `reports/c2_investigations/investigation_2_metric_sensitivity.md` | delete | confident | Same. |
| `reports/c2_investigations/investigation_3_hand_perturbation.json` | delete | confident | Same. |
| `reports/c2_investigations/investigation_3_hand_perturbation.md` | delete | confident | Same. |
| `reports/c2_investigations/c2_investigations_results.md` | **maybe** | open | Top-level summary of all four investigations. After Stage 2 deletions, sections about Inv 1/2/3 dangle. Two reasonable choices: (a) delete it (Inv 4 already has its own .md); (b) keep it as design-rationale memory and let it carry the now-dangling sections. Default proposal: **delete** since the design narrative is also in `docs/SIV.md` and `docs/SIV_EXPERIMENTS_CONTEXT.md` (the latter being deleted in Stage 1) — but please confirm. |

**Files in `reports/c2_investigations/` that are NOT candidates (kept):**
- `investigation_4_effect_size.json` / `investigation_4_effect_size.md` — Hard Rule 3.
- `path1/` (entire dir, 10 files) — Hard Rule 3.
- `path1_hard/` (entire dir, 10 files) — Hard Rule 3.

---

## Stage 3 — LLM-extraction infrastructure (dependency-aware)

### Dependency-check results

I traced who imports each candidate module across the whole repo (excluding
`.git/` and caches). The picture is more interconnected than the spec
assumed: the v1 LLM-extraction cluster pulls in **two more `siv/` modules
and three more `scripts/` files** that the spec didn't list, plus tests.
Here is the full v1 cluster, with imports recorded.

#### v1 cluster — proposed full deletion list

| File | Action | Confidence | Imported by | Reason |
| --- | --- | --- | --- | --- |
| `prompts/extraction_examples.json` | delete | confident | `tests/test_extraction_roundtrip.py`, `scripts/generate_folio_test_suites.py` (both in this same cluster) | Few-shot examples used only by v1 LLM extraction. |
| `prompts/extraction_system.txt` | delete | confident | (read at runtime via the cluster) | v1 extraction system prompt. |
| `prompts/` (directory) | delete | confident | — | Empties after the two files above. |
| `siv/extractor.py` | delete | confident | `siv/test_suite_generator.py`, `siv/__main__.py`, `tests/test_extractor.py`, `tests/test_extraction_roundtrip.py` | All importers are themselves v1; all are also being deleted in this stage. |
| `siv/json_schema.py` | delete | confident | `siv/frozen_client.py`, `tests/test_schema.py` | `frozen_client` is v1 (deleted below). `test_schema.py` will need a small edit (see below). |
| `siv/frozen_client.py` | delete | confident | `siv/__main__.py`, `tests/test_frozen_client.py`, `tests/test_extraction_roundtrip.py`, `scripts/generate_siv_tests.py`, `scripts/generate_folio_test_suites.py` | All importers are v1; all are also being deleted in this stage. |
| `siv/frozen_config.py` | delete | confident | `siv/frozen_client.py`, `tests/test_frozen_client.py` | Same. |
| `siv/test_suite_generator.py` | delete | confident | `scripts/generate_siv_tests.py`, `scripts/generate_folio_test_suites.py` | Composes extractor → compiler → contrastive for the v1 path. The v2 equivalent is `siv/gold_suite_generator.py`, which is independently load-bearing. **Spec did not list this; flagging.** |
| `siv/__main__.py` | delete | confident | — | Implements only `python -m siv extract`; depends on extractor + frozen_client. **Spec did not list this; flagging.** |
| `scripts/generate_siv_tests.py` | delete | confident | — | v1 single-sentence generator. **Spec did not list this; flagging.** |
| `scripts/generate_folio_test_suites.py` | delete | confident | — | v1 full-FOLIO generator (script that *originally produced* `reports/test_suites/test_suites.jsonl`). The output JSONL is now a frozen artifact and the v2 pipeline reads it as input — **see KEEP note below**. **Spec did not list this; flagging.** |
| `tests/test_extractor.py` | delete | confident | — | Tests the v1 extractor. Spec explicit. |
| `tests/test_frozen_client.py` | delete | confident | — | Tests the v1 frozen client. Spec explicit. |
| `tests/test_extraction_roundtrip.py` | delete | confident | — | Live LLM round-trip; gated `requires_llm`; loads `prompts/extraction_examples.json`. v1-only. **Spec did not list this; flagging.** |
| `tests/test_schema.py` | **edit, keep** | confident | — | 28 tests; only **4** functions reference `derive_extraction_schema` (`test_json_schema_*` at lines 312, 318, 333, 352). After the json_schema deletion, remove those 4 functions and the top-level `from siv.json_schema import derive_extraction_schema` import. Other 24 tests (which exercise `siv/schema.py`) remain. |
| `reports/experiments/exp2/.llm_cache/` (48 cached responses) | delete | confident | — | v1 LLM extraction cache. The locked exp2 headline is in `reports/stage4/rescore_exp2.json`. Cache dir adds nothing to a v2-only repo. Spec explicit. |

#### NOT in the v1 cluster (kept; load-bearing)

The following appeared in dep checks but are independently load-bearing
and **must not be deleted**:

- `siv/schema.py` — the central data model. Imported by 24 different files including `siv/gold_suite_generator.py`, `siv/scorer.py`, `siv/aligner.py`, `siv/compiler.py`, `siv/fol_parser.py`, all v2 scripts, and almost every test. KEEP.
- `siv/contrastive_generator.py` — imported by v2 scoring path (scorer, invariants), gold_suite_generator (transitively via compiler), and locked exp / stage4 / c2 scripts. KEEP.
- `siv/brunello_lt.py`, `siv/malls_le.py` — baseline metrics referenced by paper claims; imported by `scripts/experiments/common.py`. KEEP.
- `siv/stratum_classifier.py` — imported by `scripts/generate_candidates.py` (load-bearing for v2 candidate generation). KEEP. (Stage 0 already removed the orphaned test of this module.)
- `reports/test_suites/test_suites.jsonl` — although produced by the v1 generator, this is the frozen test-suite artifact consumed by `score_candidates.py`, `exp_c1_diagnostic_structure.py`, `stage4_rescore_exp1.py`, `c2_pilot_run.py`, `c2_pilots.py`, `run_exp1/2/3.py`, `exp1_analysis_revised.py`. **Locked input.** KEEP.

### Note on the spec's hard-rule wording

Hard Rule 5 says: *"Do NOT delete any siv/ source modules without first
checking whether tests/ depends on them. Run `pytest tests/ --collect-only`
before any siv/ deletion."* The dependency table above already records every
test that depends on each candidate; the proposed action for each test is
listed (delete vs. edit). I will run `pytest tests/ --collect-only` again
right before Stage 3 execution as a final check.

---

## Stage 4 — Stale scripts

| File | Action | Confidence | Reason |
| --- | --- | --- | --- |
| `scripts/c2_pilot_run.py` | delete | confident | Pilot scaffolding superseded by locked Investigation/Path runs. Spec explicit. |
| `scripts/c2_pilots.py` | delete | confident | Same. Spec explicit. |
| `scripts/c2_investigation_1.py` | delete | confident | Matches Stage-2 deletion of `investigation_1_*`. Spec explicit. |
| `scripts/c2_investigation_2.py` | delete | confident | Matches Stage-2 deletion. Spec explicit. |
| `scripts/c2_investigation_3.py` | delete | confident | Matches Stage-2 deletion. Spec explicit. |
| `scripts/c2_path1_hard_step5_main.py` (v1) | **maybe — likely delete** | open | A v2 sibling exists (`c2_path1_hard_step5_main_v2.py`, 257 vs 389 lines). The v2 is the optimized version (1 seed instead of 3) and its docstring explicitly says it's the live one. `git log` puts both in the same commit `008a6fa`, so log doesn't disambiguate. Default proposal: **delete the v1**, keep the v2. **Please confirm.** |

**Scripts that are NOT candidates (kept; load-bearing):**

- `scripts/c2_investigation_4.py` — Hard Rule 3.
- `scripts/c2_path1_step1.py`, `c2_path1_step3_pilot.py` — Path 1 (locked null).
- `scripts/c2_path1_hard_step1.py`, `step2.py`, `step4_pilot.py` — Path 1-Hard scaffolding for the locked null.
- `scripts/c2_path1_hard_step5_main_v2.py` — Path 1-Hard locked main run (v2 — see above).
- `scripts/exp_c1_diagnostic_structure.py` — Exp C1 (paper headline).
- `scripts/generate_candidates.py` — v2 candidate generation (uses `stratum_classifier`).
- `scripts/parser_coverage_report.py` — produces the 94.2% coverage stat (Stage 1 paper claim).
- `scripts/score_candidates.py` — v2 scoring.
- `scripts/setup.sh` — environment setup.
- `scripts/stage4_regenerate.py`, `stage4_rescore_exp1.py`, `stage4_rescore_exp2.py` — locked headline rescoring.
- `scripts/experiments/run_exp1.py`, `run_exp2.py`, `run_exp3.py`, `exp1_analysis_revised.py`, `common.py` — locked exp1/exp2/exp3 runners.
- `scripts/stage2_validation.py`, `scripts/stage3_perturbation_validation.py` — see Stage 5 "maybe" entries below.

---

## Stage 5 — Reports housekeeping

| File / action | Action | Confidence | Reason |
| --- | --- | --- | --- |
| `mv reports/COMPREHENSIVE_RESULTS.md docs/` | move | confident | Per spec — it's a paper-writing artifact, not an experiment result. (317 lines.) |
| `find reports/stage4 -name '*.tmp' -o -name '*.bak'` | n/a | confident | None exist. Stage 5 substep is a no-op. |
| `rm` (locally) all `__pycache__/`, `*.pyc`, `.DS_Store` | local clean | confident | None tracked by git (gitignored). Cleans local working tree only. Won't appear in any commit. |
| `reports/stage2_self_score.json` | **maybe** | open | Output of `stage2_validation.py`. Per the spec context, this is "early Approach-C validation scaffolding preserved in archive." Not referenced by any locked headline. Default proposal: **delete** (also delete `scripts/stage2_validation.py`). Please confirm. |
| `reports/stage3_perturbation_ordering.json` | **maybe** | open | Same shape: output of `stage3_perturbation_validation.py`. Default proposal: **delete** (also delete `scripts/stage3_perturbation_validation.py`). Please confirm. |
| `docs/corrections_template.md` (493 lines) | keep | confident | **Hard Rule 4** — the curated copy of the 30 hand-corrected FOLIO gold annotations. |
| `reports/experiments/exp3/corrections_template.md` (610 lines) | keep | confident | **Hard Rule 4** — the *original* exp3 working file; differs from `docs/corrections_template.md`. Both copies preserved. |

**Reports/ files that are NOT candidates (all kept; load-bearing):**

- `reports/parser_coverage_report.json` — Stage 1 / 94.2% claim.
- `reports/c1/` — Exp C1 outputs (coarse 0.81, fine 0.29).
- `reports/test_suites/test_suites.jsonl` — locked input artifact (see Stage 3 KEEP note).
- `reports/stage4/rescore_exp1.json`, `rescore_exp2.json`, `stage4b_regeneration.json`, `per_premise_deltas.jsonl` — Hard Rule 2 (locked headline).
- `reports/experiments/exp1/`, `exp2/`, `exp3/` (everything *except* the v1 `.llm_cache/` listed in Stage 3) — Hard Rule 2.

---

## Summary of open questions for you

Five things the inventory cannot decide unilaterally:

1. **`reports/c2_investigations/c2_investigations_results.md`** — delete (Stage 2) or keep as design-rationale memory? Default proposal: delete.
2. **v1 cluster expansion** — the spec listed 5 v1 deletions in Stage 3, but the dep graph shows 7 more files in the same cluster (`siv/test_suite_generator.py`, `siv/__main__.py`, `scripts/generate_siv_tests.py`, `scripts/generate_folio_test_suites.py`, `tests/test_extraction_roundtrip.py`, plus the test_schema.py edit). Default proposal: delete the lot. Confirm.
3. **`scripts/c2_path1_hard_step5_main.py` (v1)** — delete and keep only the v2? Default proposal: yes, delete v1.
4. **`reports/stage2_self_score.json` and `reports/stage3_perturbation_ordering.json` plus their two generator scripts (`scripts/stage2_validation.py`, `scripts/stage3_perturbation_validation.py`)** — delete? Default proposal: yes, delete.
5. **README.md edit scope** — the README is fundamentally pre-pivot; it's not a small tweak. Want me to (a) draft a full rewrite for your review before committing, or (b) make minimal edits (just remove/fix dead references and pivot framing) and we'll iterate? Default proposal: (a), draft full rewrite.

Reply with which stages to run and any per-question decisions, and I'll execute Phase D stage by stage with a pytest run between each.
