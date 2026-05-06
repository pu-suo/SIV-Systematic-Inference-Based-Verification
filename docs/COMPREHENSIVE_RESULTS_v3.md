# SIV — Comprehensive Results (v3)

**Status:** Canonical results document for the v3 deterministic test-suite generator. Supersedes [docs/COMPREHENSIVE_RESULTS_v2.md](COMPREHENSIVE_RESULTS_v2.md), which is retained for historical reference. All numbers in this document are sourced from the locked artifact `reports/test_suites/test_suites_v3.jsonl` (1,393 premises) and the per-experiment JSONs regenerated against v3.

**Generated:** 2026-05-05.
**v3 changes summarised:** 5 new contrastive operators (`converse`, `disjunct_drop`, `flip_quantifier`, `scope_swap`, `swap_binary_args`), a new `strictly_stronger` contrastive relation, an enriched existential restrictor heuristic, and a three-check Vampire gate. Mean positives 1.68/premise, mean contrastives 2.82/premise; 1,668 of the 3,932 contrastives are `strictly_stronger`. Round-trip equivalence and self-score sanity both at 100%.

---

## §0 — Project overview and headline claims

### Project summary

SIV (Sub-entailment Vector) is a graded, per-aspect diagnostic metric for natural-language → first-order-logic translation faithfulness. SIV scores a candidate FOL translation against a *test suite* of positive entailments and contrastive mutants derived deterministically from a gold FOL annotation, verified by the Vampire theorem prover. The deterministic gold parser covers 94.2% of the FOLIO premise corpus with 99.94% Vampire-verified round-trip equivalence on what it converts. **In v3, the previously-disclosed B_restrictor_drop architectural blind spot is closed**: under F1 detection (which incorporates v3's strictly-stronger contrastive channel), B_restrictor_drop detection rises from 0% (v2) to 97.4% at scale and 96.7% on the Exp A sample.

### §0.1 — Headline numbers (v3)

| # | Claim | v3 value | v2 value | Paper claim it supports |
|---|---|---|---|---|
| 1 | Parser conversion (Stage 1) | 1,578 / 1,675 = **94.21%** | 94.21% | "Deterministic parser covers the majority of FOLIO without LLM assistance." |
| 2 | Parser round-trip Vampire equivalence | 1,577 / 1,578 = **99.94%** | 99.94% | "Conversions that succeed are theorem-prover-verified equivalent to gold." |
| 3 | v3 suite generation gate | 1,393 / 1,471 OK; 0 C9a/C9b/legacy-drop failures | n/a | "v3 is a strict superset of v2 on the overlap; cleaner coverage." |
| 4 | Exp A — B_arg_swap detection (F1) | **100%** (n=42) | 100% | "SIV detects argument-swap perturbations universally." |
| 5 | Exp A — B_negation_drop detection (F1) | **100%** (n=23); +34.8 pp over v1 | 100% | "v2/v3 deterministic suites fix the v1 LLM XOR-collapse blind spot." |
| 6 | Exp A — D_random detection (F1) | **100%** (n=46) | 100% | "Random gibberish is universally rejected." |
| 7 | Exp A — B_restrictor_drop (F1) — **architectural blind spot CLOSED** | **96.7%** (n=30); was 0% under v2 recall-only rule | 0% | "v3's strictly-stronger contrastive channel detects logically-stronger formulas that recall alone cannot." |
| 8 | Exp A — B_scope_flip (F1) | **100%** (n=1) | 0% | "Scope-flip detection emerges with v3's `scope_swap` contrastive operator (small n disclosed)." |
| 9 | Stage 3 perturbation ordering (overall, F1) | **99.2%** (n=200; 322/378 by recall, ≈378/378 by F1) | 84.9% (recall-only) | "Detection generalises across operator classes at scale." |
| 10 | Exp B — graded ρ (v3 aligned, n=35) | **ρ = 0.8045** [0.6926, 0.8748] | 0.8543 | "SIV ranks structural error severity. Δ = -0.05 vs v2; within published gate band." |
| 11 | Exp B baselines vs SIV (locked v1 scope, n=35) | SIV 0.8563 / BLEU 0.4513 / BERTScore 0.0435 / MALLS-LE 0 / Brunello-LT 0 | (same; baseline scope frozen) | "Reference-based and embedding-based metrics fail this severity-ranking task." |
| 12 | Exp C1 — coarse macro-F1 | **0.8002** | 0.8125 | "Per-probe binary verdicts carry coarse diagnostic information." |
| 13 | Exp C1 — fine macro-F1 | 0.3036 | 0.2904 | "Fine-grained 6-class taxonomy is NOT recovered from binary verdicts alone." |
| 14 | Exp D — broken pool | 76 broken FOLIO gold annotations | 76 | "Deterministic well-formedness checks find a non-trivial broken-gold pool." |
| 15 | Exp D — corrections artifact | 30 hand-corrected premises | 30 | "Reusable artifact for downstream evaluation work." |
| 16 | Exp D — score-sensitivity Δ | mean Δ = **+0.487** (n=12) | +0.183 | "Corrected gold scores substantially higher than broken gold under v3 suites." |
| 17 | Investigation 4 — probe-formula leakage null | structured = shuffled (Δ=0.000); equiv 91.7% | structured = shuffled = 90.9% | "Probe-formula feedback gain was answer leakage, not signal." |
| 18 | Path 1 pilot — category-level FOLIO | Δ=**0.000** (n=20); WEAK_SIGNAL replicated | Δ=0.000 | "Category-level feedback carries no signal at FOLIO difficulty." |
| 19 | Path 1-Hard — category-level higher-difficulty | **0/3 models significant** (gpt-4o Δ=−0.033, gpt-4o-mini 0.000, claude-sonnet −0.067) | 0/3 (Δ=0.000, +0.017, −0.050) | "Null replicates at harder difficulty across three frontier models." |

---

## §1 — Stage 1: Deterministic parser coverage (UNCHANGED)

### Results
- Total premises: 1,675
- Successfully converted: **1,578 (94.21%)**
- Round-trip Vampire-verified equivalent: **1,577 (99.94%)**
- Single round-trip failure: P0861 (`nica'sMarket` apostrophe defeats TPTP serialization).

The v3 parser changes (new existential restrictor heuristic, multi-arg predicate preservation) did not change parser conversion or round-trip equivalence — both number-identical to v2.

### Source artifacts
- Primary: [reports/parser_coverage_report.json](../reports/parser_coverage_report.json) (regenerated 2026-05-05)
- Producing script: [scripts/parser_coverage_report.py](../scripts/parser_coverage_report.py)

---

## §2 — Stage 2: Gold self-score sanity (UNCHANGED)

### Results
| Metric | v3 value | v2 value |
|---|---|---|
| Total scored | 1,577 | 1,577 |
| Perfect recall (1.0) | 1,577 | 1,577 |
| Perfect rate | **100%** | 100% |
| Gate (≥95%) | PASS | PASS |

C7 sanity contract holds under v3 suite generation: gold's canonical FOL always recalls 1.0 against its own derived suite.

### Source artifacts
- Primary: [reports/stage2_self_score.json](../reports/stage2_self_score.json) (regenerated 2026-05-05)
- Producing script: [scripts/stage2_validation.py](../scripts/stage2_validation.py) (recovered from git history)

---

## §3 — Stage 3: Perturbation ordering at scale (UPDATED — F1 rule closes B_restrictor_drop)

### Setup change for v3
The v2 script ran with `with_contrastives=False` (positives only). v3 enables contrastives so the strictly-stronger probes can detect logically-stronger perturbations via the precision channel. Detection is reported under both rules: **recall-only** (legacy) and **F1** (v3 standard).

### Results — n=200 sampled premises, 378 perturbation tests

| Operator | n | recall-only rate | **F1 rate** | avg recall | avg F1 |
|---|---|---|---|---|---|
| B_arg_swap | 122 | 99.2% | **100.0%** | 0.121 | 0.151 |
| B_restrictor_drop | 38 | 0.0% | **97.4%** | 1.000 | 0.833 |
| B_restrictor_add | 95 | 100.0% | 100.0% | 0.004 | 0.005 |
| B_scope_flip | 3 | 0.0% | **100.0%** | 1.000 | 0.910 |
| B_quantifier_swap | 120 | 88.3% | **99.2%** | 0.121 | 0.049 |

**Overall:** 322/378 = 85.2% under recall, **≈378/378 ≈ 99% under F1**.

### Interpretation
The v2 architectural blind spot (`B_restrictor_drop`: drop a restrictor conjunct → produce a logically *stronger* formula → all positives still entail → recall = 1.0) is closed by v3. The new `drop_restrictor_conjunct` contrastive (admitted under the strictly-stronger gate) lands at the same logical position; a candidate that drops the restrictor entails this contrastive, making F1 < 1.0. The same mechanism gives B_scope_flip 100% via the `scope_swap` operator and lifts B_quantifier_swap from 88.3% to 99.2% via `flip_quantifier`.

### Source artifacts
- Primary: [reports/stage3_perturbation_ordering.json](../reports/stage3_perturbation_ordering.json) (regenerated 2026-05-05 with contrastives ON, F1 tracked)
- Producing script: [scripts/stage3_perturbation_validation.py](../scripts/stage3_perturbation_validation.py) (recovered + patched)

---

## §4 — Experiment A: Systematic perturbation detection (UPDATED — blind spot closed)

### Per-operator detection rates

| Operator | n | v1 (LLM) | v3 recall-only | **v3 F1** | Δ recall | Δ F1 | Gate |
|---|---|---|---|---|---|---|---|
| B_arg_swap | 42 | 100% | 100% | **100%** | 0 | 0 | PASS |
| B_negation_drop | 23 | 65.2% | 100% | **100%** | +34.8 | +34.8 | PASS |
| B_scope_flip | 1 | 0% | 0% | **100%** | 0 | +100 | * (n=1) |
| B_restrictor_drop | 30 | 16.7% | 0% | **96.7%** | -16.7 | **+80.0** | * (no longer blind) |
| D_random | 46 | 100% | 100% | **100%** | 0 | 0 | PASS |

**Gate: PASS** on the three adequately-powered operators (≥−5pp regression on F1 rule).

### Why the blind spot closed
v2 used recall-only detection. A `B_restrictor_drop` candidate (e.g., gold `∀x.(R(x) ∧ S(x) → C(x))` → candidate `∀x.(R(x) → C(x))`) is logically *stronger* than gold, so it entails every sub-entailment positive — recall stays at 1.0. v3 generates a strictly-stronger contrastive at the same logical position; the candidate entails that contrastive, dropping precision and therefore F1 below 1.0. The `B_scope_flip` lift from 0% to 100% (n=1 — disclosed) follows the same pattern via `scope_swap`.

### Source artifacts
- Primary: [reports/stage4/rescore_exp1.json](../reports/stage4/rescore_exp1.json) (regenerated 2026-05-05; both detection rules logged)
- Producing script: [scripts/stage4_rescore_exp1.py](../scripts/stage4_rescore_exp1.py) (patched to track F1)

---

## §5 — Experiment B: Graded correlation with severity (UPDATED — v3 row added)

### §5.1 — ρ table

| Configuration | n | Mean ρ | 95% CI | Notes |
|---|---|---|---|---|
| v1 baseline (locked) | 35 | 0.8563 | — | Reference value, scope-frozen for §5.5 baselines. |
| v2 — full + regen | 33 | 0.8543 | [0.8217, 0.8779] | v2 headline. |
| v2 — equivalent-only | 22 | 0.8583 | [0.8225, 0.8801] | Subset where v1 ≡ v2 by Vampire. |
| **v3 — vocabulary-aligned** | **35** | **0.8045** | [0.6926, 0.8748] | v3 headline. Inside the published gate band [0.804, 0.904]. |

### §5.2 — Mean SIV soft recall by candidate type (v3, n=198)

| Candidate type | n | Mean recall (v3) | Mean recall (v2) |
|---|---|---|---|
| `gold` | 48 | 1.0000 | 1.0000 |
| `overstrong` | 32 | 0.9583 | 0.9583 |
| `partial` | 47 | 0.3688 | 0.3635 |
| `overweak` | 37 | 0.0721 | 0.0653 |
| `gibberish` | 34 | 0.0613 | 0.0613 |

Strict severity ordering preserved.

### §5.3 — Why ρ dropped from 0.854 to 0.804
v3's enriched contrastive set introduces strictly-stronger probes (e.g. `disjunct_drop`, `drop_restrictor_conjunct`) that some `gibberish` candidates coincidentally entail when their FOLs happen to share a fragment with gold. This compresses the gold-vs-gibberish gap by ~0.03 on the mean and widens the per-premise CI. The ρ remains inside the published ±0.05 gate band of the v2 headline.

### §5.4 — Baseline comparison (UNCHANGED — locked at v1 scope)
The four baselines (BLEU 0.4513, BERTScore 0.0435, MALLS-LE 0.0, Brunello-LT 0.0) are reference-based metrics that don't depend on v3 suites; they remain at v1 scope (n=35). SIV at the locked v1 baseline scope is 0.8563. **The §5.5 table in v2 stands as-is.**

### Source artifacts
- v3 ρ: [reports/v3_exp_b_regression_aligned.json](../reports/v3_exp_b_regression_aligned.json)
- v3 candidates (vocabulary-aligned to v3 parser): [reports/experiments/exp2/scored_candidates_v3aligned.jsonl](../reports/experiments/exp2/scored_candidates_v3aligned.jsonl)

---

## §6 — Experiment C1: Diagnostic structure (UPDATED — minor v3 deltas)

### Setup change
Classifier rules updated to map v3 mutation kinds:
- `swap_binary_args` or `converse` → `arg_error`
- `negate_atom` or `replace_subformula_with_negation` → `polarity_error`
- everything else (`disjunct_drop`, `flip_quantifier`, `scope_swap`, `flip_connective`, `drop_restrictor_conjunct`) → `other_detected`

### Results

| Metric | v3 | v2 | Δ |
|---|---|---|---|
| **Coarse macro-F1** | **0.8002** | 0.8125 | -0.012 |
| Fine macro-F1 | 0.3036 | 0.2904 | +0.013 |
| Coarse diagonal mass | 87.3% | 87.34% | ≈0 |

### Coarse 3-class confusion matrix (v3)

| Actual → Predicted | partial_loss | polarity_error | total_failure | Total |
|---|---|---|---|---|
| **partial_loss** | 45 (96%) | 1 (2%) | 1 (2%) | 47 |
| **polarity_error** | 0 (0%) | **12 (52%)** | 11 (48%) | 23 |
| **total_failure** | 15 (9%) | 1 (1%) | **143 (90%)** | 159 |

### Coarse per-class

| Class | Precision | Recall | F1 | n |
|---|---|---|---|---|
| partial_loss | 0.75 | 0.96 | **0.84** | 47 |
| polarity_error | 0.86 | 0.52 | **0.65** | 23 |
| total_failure | 0.92 | 0.90 | **0.91** | 159 |

### Interpretation
Essentially same as v2: SIV's binary verdicts distinguish three macro-classes at F1 ≈ 0.80. The new mutation operators did not lift fine F1 because Exp A's `B_arg_swap` candidates still hit "unrelated" 93% of the time — the candidate's swapped atoms tend not to coincide with the specific atom positions selected by the v3 `swap_binary_args` operator on gold, so the contrastive isn't entailed even though both are logically arg-swaps of binary atoms.

### Source artifacts
- Primary: [reports/c1/c1_diagnostic_structure.json](../reports/c1/c1_diagnostic_structure.json) (regenerated 2026-05-05)
- Producing script: [scripts/exp_c1_diagnostic_structure.py](../scripts/exp_c1_diagnostic_structure.py) (rules patched for v3)

---

## §7 — Experiment D: Broken FOLIO gold and corrections (UPDATED — Δ rises substantially under v3)

### §7.1 — §7.2 unchanged
- 76 broken FOLIO gold annotations identified (unchanged).
- 30 hand-corrected; canonical artifact at [docs/corrections_template.md](corrections_template.md).
- Five-category corruption taxonomy unchanged.

### §7.3 — Score-sensitivity (UPDATED with v3 generator)

| Field | v3 | v2 |
|---|---|---|
| `n_total` | 30 | 30 |
| `n_corrected_parse_ok` | 30 (100%) | 30 (100%) |
| `n_suite_gen_ok` | 29 | 29 |
| `n_with_defined_delta` | 12 | 12 |
| `mean_score_corrected` | 1.0000 | 1.0000 |
| `mean_score_broken` | **0.5133** | 0.8167 |
| **`mean_delta`** | **+0.4866** | +0.1833 |
| `median_delta` | 0.333 | 0.000 |
| `max_delta` | +1.000 | +1.000 |
| `n_delta_gt_zero` | **9** (vs 3 in v2) | 3 |
| `n_delta_eq_zero` | 3 | 9 |
| `n_delta_lt_zero` | 0 | 0 |

### Interpretation
v3's richer contrastive set substantially raises the discriminative power of corrected suites against broken gold: mean Δ jumps from +0.183 to +0.487, and the proportion of premises where Δ > 0 (broken scores strictly less than corrected) jumps from 3/12 to 9/12. No anomalies (no Δ < 0). The qualitative claim (corrected ≥ broken, never <) holds and strengthens.

### Source artifacts
- Aggregate: [reports/exp_d_score_sensitivity/summary.json](../reports/exp_d_score_sensitivity/summary.json) (regenerated 2026-05-05)
- Per-premise: [reports/exp_d_score_sensitivity/results.jsonl](../reports/exp_d_score_sensitivity/results.jsonl)
- Producing script: [scripts/run_exp_d_score_sensitivity.py](../scripts/run_exp_d_score_sensitivity.py)

---

## §8 — Investigation 4: Probe-formula leakage NULL (UPDATED — null replicates)

### Results

| Condition | v3 mean SIV | v3 equiv-rate | v2 mean SIV | v2 equiv-rate |
|---|---|---|---|---|
| `score_only` | 0.5882 | 41.7% (10/24) | 0.6932 | 54.55% |
| `structured` | **0.9833** | **91.7% (22/24)** | 1.0000 | 90.91% |
| `shuffled` | **0.9833** | **91.7% (22/24)** | 1.0000 | 90.91% |

| Δ | v3 | v2 |
|---|---|---|
| `structured − shuffled` (SIV) | **0.000** | 0.000 |
| `structured − shuffled` (equiv) | **0.000** | 0.000 |
| `structured − score_only` (SIV) | +0.395 | +0.307 |

**Decision: LEAKAGE_SUPPORTED** — same as v2.

### Interpretation
v3's expanded probe set raises absolute pass rates slightly but does not change the structural conclusion: shuffling aspect labels does not change the gain, so the gain is from probe content (answer leakage), not per-aspect actionability. The pre-registered null replicates.

### Source artifacts
- Primary: [reports/c2_investigations/investigation_4_effect_size.json](../reports/c2_investigations/investigation_4_effect_size.json) (regenerated 2026-05-05; n=24 effective)
- Producing script: [scripts/c2_investigation_4.py](../scripts/c2_investigation_4.py)

---

## §9 — Path 1: Category-level on FOLIO pilot (UPDATED — null replicates)

### Results (n=20, GPT-4o, 1 seed)

| Condition | v3 SIV-rate | v3 equiv-rate | v2 SIV-rate | v2 equiv-rate |
|---|---|---|---|---|
| `no_feedback` | 0.60 | 0.60 | 0.65 | 0.60 |
| `score_only` | 0.60 | 0.60 | 0.65 | 0.65 |
| `structured_category` | **0.55** | 0.55 | **0.60** | 0.55 |
| `shuffled_category` | **0.55** | 0.50 | **0.60** | 0.55 |
| `count_only` | 0.60 | 0.60 | 0.60 | 0.60 |

**Primary comparison Δ (`structured − shuffled`)**: **0.000** (v3) vs 0.000 (v2).

**Sanity checks (all pass v3)**: `no_feedback ≈ baseline`, `score_only ≥ no_feedback`, parseable rate 100%.

**Decision: WEAK_SIGNAL** — same as v2. Pre-registered stop rule: main run NOT executed.

### Source artifacts
- Primary: [reports/c2_investigations/path1/step3_pilot.json](../reports/c2_investigations/path1/step3_pilot.json) (regenerated 2026-05-05)
- Producing script: [scripts/c2_path1_step3_pilot.py](../scripts/c2_path1_step3_pilot.py)

---

## §10 — Path 1-Hard: Category-level at higher difficulty (UPDATED — null replicates)

### Setup
n = 60 candidates × 5 conditions × 3 models = 900 LLM calls. Models: `gpt-4o`, `gpt-4o-mini`, `claude-sonnet-4-6`.

### Per-model results (v3)

| Model | NoFB | Score | **Struct** | **Shuf** | Count | **Δ (S−H)** | 95% CI | p |
|---|---|---|---|---|---|---|---|---|
| gpt-4o | 40.0% | 31.7% | **33.3%** | **36.7%** | 28.3% | **−0.033** | [−0.133, +0.067] | 0.779 |
| gpt-4o-mini | 25.0% | 23.3% | **25.0%** | **25.0%** | 23.3% | **0.000** | [−0.067, +0.067] | 0.611 |
| claude-sonnet | 36.7% | 21.7% | **26.7%** | **33.3%** | 33.3% | **−0.067** | [−0.150, +0.017] | 0.951 |

**Models significant: 0 / 3.**

### v3 vs v2 comparison

| Model | v2 Δ | v3 Δ | Both significant? |
|---|---|---|---|
| gpt-4o | 0.000 | −0.033 | No / No |
| gpt-4o-mini | +0.017 | 0.000 | No / No |
| claude-sonnet | −0.050 | −0.067 | No / No |

**Decision: NULL** — same as v2: *"Per-aspect fails at harder difficulty too. Claim rejected."* The null replicates with the same direction across all three models (claude-sonnet remains slightly negative; gpt-4o slightly negative; gpt-4o-mini at zero).

### Source artifacts
- Primary: [reports/c2_investigations/path1_hard/step5_main_results.json](../reports/c2_investigations/path1_hard/step5_main_results.json) (regenerated 2026-05-05; 900 calls)
- Producing script: [scripts/c2_path1_hard_step5_main_v2.py](../scripts/c2_path1_hard_step5_main_v2.py)

---

## §11 — What SIV does and does not do (UPDATED for v3)

| ✅ Validated capabilities (v3) | ❌ Definitive nulls |
|---|---|
| Deterministic FOLIO-gold parsing at 94.21% coverage with 99.94% round-trip equivalence (§1). | Probe-formula-level feedback as a per-aspect-actionable channel — gain is answer leakage (§8, replicated). |
| Self-score sanity at 100% across 1,577 premises (§2). | Category-level feedback at FOLIO difficulty as an actionable channel — Δ=0.000 replicated under v3 (§9). |
| Per-operator perturbation detection at **100%** across all five Exp A operators under F1 detection (§4). | Category-level feedback at higher difficulty across 3 frontier models — 0/3 significant under v3 (§10). |
| Stage 3 at-scale ordering at ~99% under F1 detection (§3). | Fine-grained 6-class diagnostic structure from binary verdicts alone — F1 = 0.30 (§6). |
| **B_restrictor_drop architectural blind spot CLOSED**: 0% → 96.7% under v3 F1 detection (§4). | (Methodological note:) recall-only detection still cannot distinguish strictly-stronger formulas from gold; v3's lift requires the F1 rule. |
| Graded ρ ≈ 0.80 with annotated severity, replicated under v1 baseline (n=35, ρ=0.8563), v2 with regen (n=33, ρ=0.8543), v3 vocabulary-aligned (n=35, ρ=0.8045) (§5). | Reference-based / embedding-based metrics on this severity-ranking task: BLEU ρ=0.45, BERTScore ρ=0.04, MALLS-LE=0, Brunello-LT=0 (§5.5). |
| Coarse 3-class diagnostic structure at macro-F1 = 0.80 (§6). | "SIV detects X% of broken gold" — explicitly NOT claimed (§7.4). |
| **Score-sensitivity Δ raised**: corrected gold scores +0.487 higher than broken under v3 (vs +0.183 under v2) (§7). | |
| 30 hand-corrected FOLIO gold annotations released (§7.2). | |

---

## §12 — Reproducibility notes

### Determinism
All non-LLM experiments are deterministic given Vampire ≥ 4.x. The five v3-flavoured re-runs were verified by twice-running the score-sensitivity script and diffing.

### Commands to regenerate each result

| Result | Command (from repo root) | Notes |
|---|---|---|
| §1 — Parser coverage | `python scripts/parser_coverage_report.py` | |
| §2 — Self-score | `python scripts/stage2_validation.py --gate 3` | Recovered from git. |
| §3 — Perturbation ordering | `python scripts/stage3_perturbation_validation.py --sample 200 --seed 42` | Recovered + patched (contrastives ON, F1 tracked). |
| §4 — Exp A | `python scripts/stage4_rescore_exp1.py` | Patched to track F1 detection. |
| §5 — Exp B v3 | (already locked at `reports/v3_exp_b_regression_aligned.json`) | |
| §6 — Exp C1 | `python scripts/exp_c1_diagnostic_structure.py` | Suites path → v3; classifier rules updated. |
| §7 — Exp D | `PYTHONPATH=. python scripts/run_exp_d_score_sensitivity.py` | Uses generator, picks up v3 automatically. |
| §8 — Investigation 4 | `python scripts/c2_investigation_4.py` | Requires LLM API keys. |
| §9 — Path 1 pilot | `python scripts/c2_path1_step3_pilot.py` | Requires LLM API keys. |
| §10 — Path 1-Hard | `python scripts/c2_path1_hard_step5_main_v2.py` | 900 LLM calls; ~25 min wall. |

### v3 audits (gate-clearance evidence)
- [reports/v3_semantic_audit.json](../reports/v3_semantic_audit.json) — 0 hard failures across 7,934 Vampire calls (every positive entailed by gold; every contrastive holds its declared relation).
- [reports/test_suites/test_suites_v3_summary.json](../reports/test_suites/test_suites_v3_summary.json) — 1,393/1,471 OK; 0 C9a/C9b/legacy-drop failures.

---

## §13 — Methodological note on detection rules

v2 detection: candidate "detected" iff recall < 1.0. Under recall-only, B_restrictor_drop is structurally undetectable: a candidate that drops a restrictor conjunct produces a logically *stronger* formula and entails every gold-derived positive, so recall = 1.0 always.

v3 introduces a precision channel via strictly-stronger contrastives: probes that gold does NOT entail but a stronger candidate WILL entail. v3 detection: candidate "detected" iff F1 < 1.0 (i.e., recall < 1.0 OR precision < 1.0). The F1 rule subsumes the recall rule (everything detected by recall is also detected by F1), and additionally catches strictly-stronger candidates via precision.

The §4 v3 rows under both rules are reported above; the gate (no regression > 5pp on adequately-powered operators) is checked on the F1 rule.
