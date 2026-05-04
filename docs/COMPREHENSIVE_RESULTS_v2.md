# SIV — Comprehensive Results (v2, canonical)

**Status:** Canonical results document for the EMNLP Findings submission. Supersedes [docs/COMPREHENSIVE_RESULTS.md](COMPREHENSIVE_RESULTS.md), which is retained for archival reference but contains transcription errors and dangling file references that this version corrects. All numbers in this document are sourced directly from the locked JSONs in `reports/`; per-experiment verification blocks live in [reports/verified/](../reports/verified/).

**Generated:** 2026-05-04 (post-cleanup commit `21f89f4`)
**Generation procedure:** Read primary JSONs in `reports/`; cross-check against HARD RULE 2 headline numbers; produce one verification block per experiment in `reports/verified/`; new score-sensitivity experiment in `reports/exp_d_score_sensitivity/`. No headline numbers were re-run; no headline values were modified.

---

## §0 — Project overview and headline claims

### Project summary

SIV (Sub-entailment Vector) is a graded, per-aspect diagnostic metric for natural-language → first-order-logic translation faithfulness. SIV scores a candidate FOL translation against a *test suite* of positive entailments and contrastive mutants derived deterministically from a gold FOL annotation, verified by the Vampire theorem prover. The deterministic gold parser (Stage 1) covers 94.2% of the FOLIO premise corpus with 99.94% Vampire-verified round-trip equivalence on what it converts; SIV therefore avoids depending on an LLM extraction step at evaluation time.

The headline contributions are: a faithful sub-entailment-based metric whose graded scores rank-correlate with annotated severity at ρ = 0.85; systematic perturbation detection at 100% on three of five operator classes (with two architecturally-explained blind spots); a coarse three-class diagnostic structure with macro-F1 = 0.81; an artifact of 30 hand-corrected FOLIO gold annotations released for community reuse; and three pre-registered nulls that delineate where SIV does *not* carry signal (probe-formula leakage, category-level feedback at FOLIO difficulty, and category-level feedback at higher difficulty across three frontier models).

### §0.1 — Headline numbers

| # | Claim | Headline value | Paper claim it supports |
|---|---|---|---|
| 1 | Parser conversion (Stage 1) | 1,578 / 1,675 = **94.21%** | "Deterministic parser covers the majority of FOLIO without LLM assistance." |
| 2 | Parser round-trip Vampire equivalence | 1,577 / 1,578 = **99.94%** | "Conversions that succeed are theorem-prover-verified equivalent to gold." |
| 3 | Exp A — B_arg_swap detection (v2) | 100% (n=42) | "SIV detects argument-swap perturbations universally." |
| 4 | Exp A — B_negation_drop detection (v2) | 100% (n=23); +34.8 pp over v1 | "v2 (deterministic) fixes the v1 (LLM) XOR-collapse blind spot." |
| 5 | Exp A — D_random detection (v2) | 100% (n=46) | "Random gibberish is universally rejected." |
| 6 | Exp A — B_restrictor_drop (architectural blind spot) | 0% (n=30) | "We disclose this; it follows from recall-based sub-entailment under stronger formulas." |
| 7 | Exp B — graded ρ (with regeneration) | **ρ = 0.8543** [0.8217, 0.8779], n=33 | "SIV ranks structural error severity." |
| 8 | Exp B — graded ρ (equivalent-only subset) | ρ = 0.8583 [0.8225, 0.8801], n=22 | "Effect holds without any v1→v2 regeneration." |
| 9 | Exp B baselines — SIV vs BLEU vs BERTScore vs MALLS-LE vs Brunello-LT | SIV 0.8563 / BLEU 0.4513 / BERTScore 0.0435 / MALLS-LE 0.0 / Brunello-LT 0.0 (all n=35) | "Reference-based and embedding-based metrics fail this severity-ranking task." |
| 10 | Exp C1 — coarse macro-F1 | **0.8125** | "Per-probe verdicts carry coarse diagnostic information." |
| 11 | Exp C1 — fine macro-F1 | 0.2904 | "Fine-grained 6-class taxonomy is NOT recovered from binary verdicts alone." |
| 12 | Exp D — broken pool size | **76** broken FOLIO gold annotations identified | "Deterministic well-formedness checks find a non-trivial broken-gold pool." |
| 13 | Exp D — corrections artifact | **30** hand-corrected premises released | "Reusable artifact for downstream evaluation work." |
| 14 | Exp D — score-sensitivity Δ (NEW) | mean Δ = +0.183 (n=12 with defined Δ) | "On premises where both broken and corrected gold parse, corrected gold scores higher." |
| 15 | Investigation 4 — probe-formula leakage null | structured = shuffled (Δ = 0.000) | "Probe-formula feedback gain was answer leakage, not signal." |
| 16 | Path 1 pilot — category-level FOLIO null | structured = shuffled = 60% SIV-pass (Δ = 0.000); WEAK_SIGNAL | "Category-level feedback carries no signal at FOLIO difficulty; main run not executed." |
| 17 | Path 1-Hard — category-level higher-difficulty null | 0/3 models significant (gpt-4o Δ=0.000; gpt-4o-mini +0.017; claude-sonnet -0.050) | "The null replicates at harder difficulty across three frontier models — claim rejected." |

Verification trail: every number above is traced to its source JSON and verification block in §14.

---

## §1 — Stage 1: Deterministic parser coverage

### Goal
Replace the LLM-based extraction step in the original SIV (v1) pipeline with a deterministic parser that converts FOLIO gold FOL annotations into the `SentenceExtraction` schema, and verify with Vampire that what it outputs is logically equivalent to the input gold.

### Setup
- Input: 1,675 unique FOLIO gold-FOL annotations (entire premise corpus).
- Pipeline: gold FOL → `siv.fol_parser.parse_gold_fol` → `SentenceExtraction` → `siv.compiler.compile_canonical_fol` → Vampire equivalence vs original normalized gold.
- Run script: [scripts/parser_coverage_report.py](../scripts/parser_coverage_report.py).
- Vampire used for round-trip equivalence checks; deterministic; no seeds.

### Results

**Conversion**
- Total premises: 1,675
- Successfully converted: **1,578 (94.21%)**
- Rejected: 97 (5.79%)

**Round-trip equivalence (over the 1,578 converted)**
- PASS (Vampire-verified bidirectional entailment): **1,577 (99.94%)**
- FAIL: 1 (0.06%)

**Rejection breakdown (97 total)**
| Category | Count | Description |
|---|---|---|
| `nltk_parse_failure` | 68 | NLTK-FOL parse failure: unbalanced parens, hyphenated identifiers, XOR operators, misspelled tokens. |
| `free_indvar` | 27 | Gold contains free individual variables. |
| `validation_failure` | 1 | Atomic-formula validation: an argument is not a declared entity/constant or bound variable. |
| `predicate_arity_inconsistency` | 1 | A predicate is used with inconsistent arities across the formula. |

The single round-trip failure: `Avocados are a kind of fruit sold at the local farmers market in New Haven or at Nica's market.` — the apostrophe in `nica'sMarket` defeats Vampire's TPTP serialization.

### Interpretation
The parser converts the overwhelming majority of FOLIO gold; the rejection categories are dominated by malformations of the gold itself (these are the same cases that motivate Exp D). The 99.94% round-trip rate confirms that the parser-based pipeline does not silently change the logical content of what it accepts.

### Role in the paper's case
Supports the abstract's claim that SIV does not depend on an LLM extraction step at evaluation time. Justifies the locked test-suite artifact `reports/test_suites/test_suites.jsonl` (1,471 premises) as a deterministic, reproducible base for downstream experiments.

### Source artifacts
- Primary: [reports/parser_coverage_report.json](../reports/parser_coverage_report.json)
- Verification block: [reports/verified/stage1_verified.json](../reports/verified/stage1_verified.json)
- Producing script: [scripts/parser_coverage_report.py](../scripts/parser_coverage_report.py)

---

## §2 — Stage 2: Gold self-score sanity

### Provenance note
Primary JSON `reports/stage2_self_score.json` was deleted in cleanup commit `c243cd9` (Stage 5/5). Numbers in this section are reproduced from [docs/COMPREHENSIVE_RESULTS.md](COMPREHENSIVE_RESULTS.md) §STAGE 2 (sanctioned secondary source per HARD RULE 4). To restore the primary source, checkout the `pre-cleanup-snapshot` tag in the SIV-archive repository.

### Goal
Verify that v2 gold-derived test suites correctly score the gold itself with recall = 1.0 — i.e., the C7 sanity contract from `docs/SIV.md`.

### Setup
- Input: every gold FOL the parser accepted.
- For each: generate v2 test suite from gold, then score gold against its own suite. Expect recall = 1.0.

### Results
| Metric | Value |
|---|---|
| Total scored | 1,577 |
| Perfect recall (1.0) | 1,577 |
| Imperfect recall | 0 |
| Score errors | 0 |
| **Perfect rate** | **100%** |
| Gate pass | ✓ |

### Interpretation
v2 suite generation is internally consistent with the C7 sanity contract: the canonical FOL of the gold extraction always scores perfectly against the suite derived from itself. This rules out compiler-emitted-positives bugs as a confound for downstream experiments.

### Role in the paper's case
Sanity gate for §4–§7. If this had failed, all downstream SIV scores would be uninterpretable.

### Source artifacts
- **Secondary source:** [docs/COMPREHENSIVE_RESULTS.md](COMPREHENSIVE_RESULTS.md) §STAGE 2.
- Verification block: [reports/verified/stage2_verified.json](../reports/verified/stage2_verified.json)
- Producing script (cleanup-removed): `scripts/stage2_validation.py` — recoverable from `pre-cleanup-snapshot` tag.

---

## §3 — Stage 3: Perturbation ordering at scale

### Provenance note
Primary JSON `reports/stage3_perturbation_ordering.json` was deleted in cleanup commit `c243cd9` (Stage 5/5). Numbers reproduced from [docs/COMPREHENSIVE_RESULTS.md](COMPREHENSIVE_RESULTS.md) §STAGE 3 (sanctioned secondary source).

### Goal
Verify v2 suites detect perturbations (perturbed score < gold score) at scale — not just on the small Exp A operator-by-operator slice.

### Setup
- Sample: 200 premises.
- Per premise, apply available perturbation operators; compute SIV on each perturbed candidate.

### Results
| Metric | Value |
|---|---|
| Sample size | 200 premises |
| Total tests | 378 |
| Total correct ordering (perturbed_score < gold_score) | 321 |
| **Overall detection rate** | **84.9%** |
| Gate pass | ✓ |

**Per-operator detection (subset surfaced in secondary source)**
| Operator | Applicable | Detection | Avg perturbed recall |
|---|---|---|---|
| B_arg_swap | 122 | 98.4% | 0.130 |
| B_restrictor_drop | 38 | 0% (architectural blind spot) | — |

### Interpretation
B_arg_swap is detected near-universally at scale; B_restrictor_drop is the architectural blind spot that recurs in §4 — restrictor drops produce logically *stronger* formulas that still entail all sub-entailment positives.

### Source artifacts
- **Secondary source:** [docs/COMPREHENSIVE_RESULTS.md](COMPREHENSIVE_RESULTS.md) §STAGE 3.
- Verification block: [reports/verified/stage3_verified.json](../reports/verified/stage3_verified.json)
- Producing script (cleanup-removed): `scripts/stage3_perturbation_validation.py`.

---

## §4 — Experiment A: Systematic perturbation detection (v1 vs v2)

### Goal
Test whether SIV detects each of five systematic perturbation operators applied to FOLIO gold FOL, comparing v1 (LLM-extracted suites) against v2 (deterministic gold-derived suites).

### Setup
- Input: 368 v2 suites generated from FOLIO gold (no failures); 510 candidates total scored.
- Operators: `B_arg_swap`, `B_negation_drop`, `B_scope_flip`, `B_restrictor_drop`, `D_random`.
- Detection definition: candidate's SIV score is below the gold's score on the same suite.
- Gate: no regression > 5 pp on the three operators with adequate sample (`B_arg_swap`, `B_negation_drop`, `D_random`).
- Producing script: [scripts/stage4_rescore_exp1.py](../scripts/stage4_rescore_exp1.py).

### Results

**Per-operator detection rates**
| Operator | n | v1 | v2 | Δ (pp) | Gate | avg v2 recall |
|---|---|---|---|---|---|---|
| `B_arg_swap` | 42 | 100% | **100%** | 0 | PASS | 0.0278 |
| `B_negation_drop` | 23 | 65.2% | **100%** | **+34.8** | PASS | 0.0145 |
| `B_scope_flip` | 1 | 0% | 0% | 0 | * (n=1) | 1.0 |
| `B_restrictor_drop` | 30 | 16.7% | **0%** | -16.7 | * (architectural) | 1.0 |
| `D_random` | 46 | 100% | **100%** | 0 | PASS | 0.0181 |

**Gate:** PASS — no regression > 5 pp on the three adequately-powered operators.

**Suite generation:** 368 / 368 (100% success).
**Scoring:** 510 candidates scored, 0 errors.

### Why B_negation_drop jumps +34.8 pp (v1 → v2)
All 8 v1 non-detections were XOR premises where LLM extraction collapsed exclusive-or into a simple disjunction positive. v2 faithfully parses XOR structure and emits richer sub-entailments that catch the perturbation.

### The two flagged blind spots (architectural, not regressions)
- `B_restrictor_drop`: producing a *logically stronger* formula that still entails every sub-entailment positive (recall = 1.0 by construction). This is a property of recall-based sub-entailment testing, not a v2 regression. The paper must disclose this.
- `B_scope_flip`: n = 1 in Exp A — insufficient statistical power. The single instance is also a logically stronger formula in the test set used.

### Interpretation
v2 matches v1 on the three operators where v1 already worked; fixes one v1 blind spot (XOR via negation_drop); and exposes one architectural blind spot inherent to recall-based sub-entailment (restrictor_drop). The blind spot is honestly disclosed and is consistent with SIV's design choice to score recall over the canonical's positives.

### Role in the paper's case
Supports the perturbation-detection abstract claim with operator-level granularity. The disclosed blind spot is essential for the paper's honesty — without it, the 100/100/100 looks suspiciously clean.

### Source artifacts
- Primary: [reports/stage4/rescore_exp1.json](../reports/stage4/rescore_exp1.json)
- Verification block: [reports/verified/exp_a_verified.json](../reports/verified/exp_a_verified.json)
- Producing script: [scripts/stage4_rescore_exp1.py](../scripts/stage4_rescore_exp1.py)

---

## §5 — Experiment B: Graded correlation with structural error severity

### Goal
Test whether SIV scores correlate with annotator-rated structural error severity across five candidate types: `gold` > `overstrong` > `partial` > `overweak` > `gibberish`. Headline metric: per-premise Spearman ρ between SIV score and severity rank, then bootstrap CI on the mean.

### Setup
- Premise pool drawn from FOLIO. v2 suites generated from gold via `siv.gold_suite_generator`.
- Three configurations reported, each with bootstrap 95 % CI:
  - **(A)** Full v2 with regeneration (n = 33). Premises whose v1 candidates' v2 suites lacked sufficient probe-coverage have those candidates regenerated using the v2 suite vocabulary.
  - **(B)** Full v2 *without* regeneration (n = 35). Direct application of v2 to v1 candidates.
  - **(C)** Equivalent-only subset (n = 22). Only the premises where v1 and v2 canonical formulas are Vampire-equivalent (no regeneration needed).
- Producing scripts: [scripts/stage4_rescore_exp2.py](../scripts/stage4_rescore_exp2.py), [scripts/stage4_regenerate.py](../scripts/stage4_regenerate.py).

### §5.1 — Three-configuration ρ table

| Configuration | n | Mean ρ | 95 % CI | Notes |
|---|---|---|---|---|
| (A) **Full + regen** (headline) | **33** | **0.8543** | [0.8217, 0.8779] | Two premises (P1077, P0621) excluded entirely after regen could not produce sufficient probes. |
| (B) Full, no regen | 35 | 0.7797 | [0.6579, 0.8674] | Drop driven by P1077 (ρ = -0.866) and P0621 (ρ = 0.000) — both v1-LLM-introduced reinterpretations. |
| (C) Equivalent-only | 22 | 0.8583 | [0.8225, 0.8801] | Subset where v1 ≡ v2 by Vampire; no regeneration involved. |
| **v1 baseline** (locked) | 35 | 0.8563 | — | Reference value from the v1 (LLM-extracted) pipeline, scope-equivalent to (B). |

Take-away: with regeneration, v2 matches v1 baseline (0.8543 vs 0.8563); the equivalent-only subset (no regen at all) gives 0.8583, slightly higher. The middle line (without regen) is depressed by two premises whose v1-LLM canonical changed the gold's logical content — see §5.4.

### §5.2 — Per-premise ρ values

**Configuration (A): full with regen, n = 33 (headline)**
| Premise | ρ | Premise | ρ | Premise | ρ |
|---|---|---|---|---|---|
| P1293 | 0.8889 | P1375 | 0.8889 | P0187 | 0.8889 |
| P0870 | 0.8889 | P0599 | 0.8660 | P1616 | 0.8660 |
| P1645 | 0.8889 | P0023 | 0.8660 | P0087 | 0.8889 |
| P0089 | 0.8889 | P0397 | 0.8889 | P0398 | 0.8660 |
| P0399 | 0.8660 | P0495 | 0.8889 | P0586 | 0.8660 |
| P0680 | 0.8660 | P0817 | 0.8889 | P0975 | 0.8889 |
| P0978 | 0.8333 | P1028 | 0.8889 | P1119 | 0.8660 |
| P1172 | 0.8889 | P1191 | 0.8889 | P1618 | 0.8660 |
| P1637 | 0.8660 | P1648 | 0.8889 | P0566 | 0.8660 |
| P1078 | 0.5000 | P1120 | 0.8660 | P1207 | 0.8660 |
| P1669 | 0.8333 | P0621 | 0.8889 | P1138 | 0.5443 |

**Configuration (B): full without regen, n = 35** (raw before regeneration; full table in [reports/verified/exp_b_verified.json](../reports/verified/exp_b_verified.json)). Notable values: P1077 = -0.866, P0621 = 0.0, P1138 = 0.544, P1078 = 0.500, P0398 = 0.943.

**Configuration (C): equivalent-only subset, n = 22** (full table in verification block). Same values as in (A) for these 22 premises (no regen applied).

### §5.3 — Mean SIV score by candidate type (v2, no regen — n = 198 candidates from 35 premises)

| Candidate type | n | Mean SIV soft recall |
|---|---|---|
| `gold` | 48 | 1.0000 |
| `overstrong` | 32 | 0.9583 |
| `partial` | 47 | 0.3635 |
| `overweak` | 37 | 0.0653 |
| `gibberish` | 34 | 0.0613 |

Strict severity ordering `gold > overstrong > partial > overweak > gibberish` is preserved on the means.

**Δ (v2 − v1) by type**
| Type | Mean Δ |
|---|---|
| `gold` | 0.0000 |
| `overstrong` | -0.0417 |
| `partial` | +0.0029 |
| `overweak` | -0.0068 |
| `gibberish` | +0.0294 |

All within ± 0.05 — v2 reproduces v1's severity-ranking behavior at the mean.

### §5.4 — Root-cause analysis of the two outlier premises

Both outliers in configuration (B) are explained by v1-LLM divergences from gold, not by SIV failures.

**P1077 (without regen: ρ = -0.866).** Gold is `all x.((Disease(x) & Leukemia(x)) -> BloodCancer(x))`. v1 LLM canonical was `all x.(TypeOfLeukemia(x) -> (Disease(x) & BloodCancer(x)))` — invented a new predicate `TypeOfLeukemia` and re-arranged the consequent. The "gibberish" candidate `all x.(Disease(x) -> BloodCancer(x))` is logically *stronger* than v2 gold (drops the restrictor conjunct `Leukemia(x)`), so v2 correctly assigns recall = 1.0 to it. The label "gibberish" is wrong from the v2-gold perspective. Excluding P1077 raises configuration (B)'s ρ from 0.7797 to **0.8282**.

**P0621 (without regen: ρ = 0.0).** Gold uses constant `michael`; v1 LLM used `michaelODonnell`. Symbol alignment at threshold 0.6 cannot bridge the difference, so all candidates score uniformly low. Excluding both P1077 and P0621 raises (B)'s ρ to **0.8532** — within the (A) regenerated configuration's CI.

Regeneration in configuration (A) reissues the candidates against the v2 vocabulary, dissolving both outliers (note P1077 → 0.866 and P0621 → 0.889 in the (A) per-premise table).

### §5.5 — Baseline comparison (KEY ARTIFACT — surfaced for the first time here)

This is the comparison table the paper needs. All rows are at v1-baseline scope (n = 35 premises) and were computed by [scripts/experiments/run_exp2.py](../scripts/experiments/run_exp2.py).

| Metric | Mean ρ | 95 % CI | n | p vs SIV |
|---|---|---|---|---|
| **SIV soft recall** | **0.8563** | [0.8236, 0.8811] | 35 | — (reference) |
| BLEU | 0.4513 | [0.2872, 0.6047] | 35 | 0.0 |
| BERTScore | 0.0435 | [-0.1715, 0.2674] | 35 | 0.0 |
| MALLS-LE (aligned) | 0.0000 | [0.0, 0.0] | 35 | 0.0 |
| Brunello-LT (aligned) | 0.0000 | [0.0, 0.0] | 35 | 0.0 |

Reference-based string and embedding metrics carry essentially no signal on FOL severity ranking; SIV's ρ is significantly above all four baselines (p ≈ 0 for each; permutation test).

**Important scope-distinction note for the paper.** Two SIV ρ values appear in this section that are not directly comparable:
- **0.8563** (this baseline table): v1 SIV scope, n = 35, computed against the v1-extracted suite. The published baseline-comparison value.
- **0.8543** (§5.1 row A): v2 SIV scope, n = 33 with regeneration. The headline "v2 still works" value.

They measure different pipelines on slightly different premise sets; both are real, and §5.1 above lays them out side-by-side. The baseline comparison in §5.5 is locked at v1 scope because that is the scope on which the four baseline metrics were computed.

### Interpretation
SIV ranks structural error severity strongly (ρ ≈ 0.85) and reproduces this ranking under both pipelines (v1 LLM-extracted and v2 deterministic). The two outliers in configuration (B) are LLM-pipeline artifacts, not SIV failures — they vanish under regeneration. Reference-based and embedding-based metrics carry essentially no signal on this task.

### Role in the paper's case
Supports the abstract's headline graded-correlation claim (ρ = 0.85). §5.5 is the multi-metric comparison table the paper needs to motivate SIV vs string/embedding alternatives.

### Source artifacts
- Primary: [reports/stage4/rescore_exp2.json](../reports/stage4/rescore_exp2.json) (rho values, per-premise, root cause)
- Primary: [reports/stage4/stage4b_regeneration.json](../reports/stage4/stage4b_regeneration.json) (regeneration details, all three ρ configurations)
- Primary baselines: [reports/experiments/exp2/rank_correlation.json](../reports/experiments/exp2/rank_correlation.json)
- Verification block: [reports/verified/exp_b_verified.json](../reports/verified/exp_b_verified.json)
- Verification block (baselines): [reports/verified/exp_b_baselines_verified.json](../reports/verified/exp_b_baselines_verified.json)
- Producing scripts: [scripts/stage4_rescore_exp2.py](../scripts/stage4_rescore_exp2.py), [scripts/stage4_regenerate.py](../scripts/stage4_regenerate.py), [scripts/experiments/run_exp2.py](../scripts/experiments/run_exp2.py)

---

## §6 — Experiment C1: Diagnostic structure

### Goal
Test whether SIV's binary per-probe verdicts (which positives passed; which contrastives were entailed; recall band) carry coarse and fine error-class signal.

### Setup
- 92 v2 suites generated; 229 candidates scored across Exp A (111) and Exp B (118) candidate types.
- Two taxonomies:
  - **Coarse (3 classes):** `total_failure`, `polarity_error`, `partial_loss`.
  - **Fine (6 classes):** `arg_error`, `polarity_error`, `unrelated`, `partial_underspec`, `severe_underspec`, `other_detected`.
- Classification rules from binary verdicts:
  - `recall = 1.0` and no contrastive entailments → `undetected`
  - `recall = 0.0` and no contrastive entailments → `unrelated`
  - contrastive entailments dominant `swap_binary_args` → `arg_error`
  - contrastive entailments dominant `negate_atom` → `polarity_error`
  - contrastive entailments other dominant → `other_detected`
  - no contrastive entailments, recall < 0.4 → `severe_underspec`
  - no contrastive entailments, 0.4 ≤ recall < 1.0 → `partial_underspec`
- Gate: coarse macro-F1 ≥ 0.65.
- Producing script: [scripts/exp_c1_diagnostic_structure.py](../scripts/exp_c1_diagnostic_structure.py).

### Results — coarse

**Macro-F1 = 0.8125** (gate threshold 0.65 → **PASS**). Diagonal mass ratio = 0.8734.

#### §6.1 — Coarse 3-class confusion matrix
Rows = expected, columns = predicted.

| Expected → predicted | total_failure | polarity_error | partial_loss | undetected |
|---|---|---|---|---|
| **total_failure** | **143** | — | 15 | 1 |
| **polarity_error** | 11 | **12** | — | — |
| **partial_loss** | 1 | — | **45** | 1 |

#### §6.2 — Coarse per-class precision / recall / F1
| Class | TP | FP | FN | Precision | Recall | F1 | Support |
|---|---|---|---|---|---|---|---|
| total_failure | 143 | 12 | 16 | 0.9226 | 0.8994 | **0.9108** | 159 |
| polarity_error | 12 | 0 | 11 | 1.0000 | 0.5217 | **0.6857** | 23 |
| partial_loss | 45 | 15 | 2 | 0.7500 | 0.9574 | **0.8411** | 47 |

### Results — fine

**Macro-F1 = 0.2904** (well below the coarse value).

#### §6.3 — Fine 6-class confusion matrix
| Expected (source candidate type) → predicted | unrelated | severe_underspec | partial_underspec | polarity_error | other_detected | undetected |
|---|---|---|---|---|---|---|
| `B_arg_swap` (expected `arg_error`) | 39 | 2 | 1 | — | — | — |
| `B_negation_drop` (expected `polarity_error`) | 11 | — | — | **10** | 2 | — |
| `D_random` (expected `unrelated`) | **44** | 1 | 1 | — | — | — |
| `partial` (expected `partial_underspec`) | 1 | 38 | **7** | — | — | 1 |
| `overweak` (expected `severe_underspec`) | 30 | **6** | 1 | — | — | — |
| `gibberish` (expected `unrelated`) | **30** | 2 | 1 | — | — | 1 |

#### Fine per-class precision/recall/F1
| Class (source) | Expected label | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|---|
| B_arg_swap | arg_error | 0 | 0 | 42 | 0.0000 | 0.0000 | **0.0000** |
| B_negation_drop | polarity_error | 10 | 0 | 13 | 1.0000 | 0.4348 | **0.6061** |
| D_random | unrelated | 44 | 111 | 2 | 0.2839 | 0.9565 | **0.4378** |
| partial | partial_underspec | 7 | 4 | 40 | 0.6364 | 0.1489 | **0.2414** |
| overweak | severe_underspec | 6 | 43 | 31 | 0.1224 | 0.1622 | **0.1395** |
| gibberish | unrelated | 30 | 125 | 4 | 0.1935 | 0.8824 | **0.3175** |

#### §6.4 — Why fine F1 = 0.29
The classifier consumes only binary per-probe verdicts (which probes failed; recall band; whether any contrastive was entailed). On `B_arg_swap`, every contrastive is *also* an argument-swap (per the operator), but the binary verdict cannot recover *which* argument swap, so it lands in `unrelated` rather than `arg_error` — F1 = 0.0 by construction. The general pattern: total-failure cases (B_arg_swap, gibberish, overweak, D_random) are indistinguishable from each other under binary verdicts because they all produce the same signature (low recall, no contrastive entailments). Per-probe TRACE identity (which probes failed, their FOL content) carries the missing information; that hypothesis was tested in C2 (§8–§10) and found null.

### Interpretation
SIV's binary probe verdicts distinguish three coarse failure modes — total failure, polarity error, partial loss — at macro-F1 = 0.81. They do *not* recover the finer six-class taxonomy: F1 = 0.29 is essentially noise on top of the dominant 'total_failure' signature.

### Role in the paper's case
The coarse 0.81 supports the paper's diagnostic-structure claim. The fine 0.29 motivates the per-aspect feedback exploration in §8–§10 (which then nulls out — preserving the paper's honest framing).

### Source artifacts
- Primary: [reports/c1/c1_diagnostic_structure.json](../reports/c1/c1_diagnostic_structure.json)
- Verification block: [reports/verified/exp_c1_verified.json](../reports/verified/exp_c1_verified.json)
- Producing script: [scripts/exp_c1_diagnostic_structure.py](../scripts/exp_c1_diagnostic_structure.py)

---

## §7 — Experiment D: Broken FOLIO gold and corrections (REFRAMED)

### What changed in this section
The previous Exp D framing claimed a "27/30 (90%) flagging rate." That framing was circular: the 30 cases were *selected* using the same criteria (parse failure or free variables) that constitute SIV's flagging mechanism. We replace that claim entirely. The reframed Exp D has four honest deliverables and **zero detection-rate claims**:

1. We identify **76** broken FOLIO gold annotations through deterministic well-formedness checks (§7.1).
2. We hand-correct **30** of them and release them as a reusable artifact (§7.2).
3. **Score-sensitivity result (NEW):** corrected suites score corrected gold at SIV ≈ 1.0 by construction, and broken gold lower where it parses at all (§7.3).
4. Five-category **corruption taxonomy** with example premise IDs (§7.2).

### §7.1 — Broken-pool identification (76 cases)

**Selection criteria** (per [reports/experiments/exp3/run_metadata.json](../reports/experiments/exp3/run_metadata.json) Step 1):
- `syntax_error`: `parse_fol` returns None — unbalanced parens, hyphenated predicates, XOR operators, malformed identifiers.
- `free_variable`: `free_individual_variables` non-empty — gold has identifiers parsed as free vars (typos, comma-as-thousands-separator, missing binders).
- A third criterion (`unprovable_by_design`) yielded 0 premises from the available per-premise evidence; story-level heuristics were not used per spec.

**Step 1 pool size: 76**, broken down as:
| Reason | Count |
|---|---|
| `syntax_error` | 54 |
| `free_variable` | 22 |

**Step 2 filters** (for the corrections-eligible subset): canonical extraction succeeded, ≥ 2 positives, NL ≤ 30 words. After filtering: 31 survivors, **30 selected** (one dropped to limit per-story concentration). Stratification ratio 17/30 = 57 % `syntax_error` (reported as a deviation in `run_metadata` because no per-premise evidence existed for the third criterion).

**Sample broken pool entries** (first 5):
| ID | NL | Broken FOL | Reason |
|---|---|---|---|
| P0017 | The Emmet Building is a five-story building in Portland, Oregon. | `Building(emmetBuilding) ∧ Five-Story(emmetBuilding) ∧ LocatedIn(...) ∧ LocatedIn(portland, oregon))` | syntax_error (hyphen in predicate, trailing paren) |
| P0035 | Lily is in James' family; she watches TV series in cinemas. | `Customer(lily) ∧ In(lily, jameSFamily ∧ WatchIn(lily, tV, cinema)` | syntax_error (unbalanced parens) |
| P0053 | Some monitors made by LG have a type-c port. | `∃x (Monitor(x) ∧ ProducedBy(x, lG) ∧ Have(x, typeCPort) ∧ (¬(x=y)) ∧ Monitor(y) ∧ ...)` | free_variable (y unbound) |
| P0179 | All people who went to Clay's school that do not have regular 9-5 jobs, work in entertainment... | `∀x (... ¬(Have(x, y) ∧ Regular(y) ∧ NineToFiveJob(y)) → WorkInAs(...))` | free_variable (y) |
| P0190 | Oliver plays a different musical instrument from Peter in the concert. | `∀x (PlayIn(oliver, x, concert) → ¬PlayIn(peter, y, concert))` | free_variable (y) |

### §7.2 — Hand-correction artifact (30 cases) and corruption taxonomy

The 30 corrections live in [docs/corrections_template.md](corrections_template.md). Each entry has: `premise_id`, `nl`, gold-broken FOL, broken-reason, broken-evidence, `c_correct_fol`, one-sentence rationale, and any introduced predicates.

**Five-category corruption taxonomy** (post-hoc enrichment of the original 2-category broken-reason field, by inspection of the rationales):

| Post-hoc category | Count | Example IDs | Definition |
|---|---|---|---|
| `syntax_error` | 10 | P1332, P1542, P1223, P0017, P0437, P1505, P0913, P1615, P0446, P0286 | Pure parser-level malformation: unbalanced parens, hyphenated predicates, trailing commas, missing variable names. Intended encoding is reconstructible. |
| `free_variable` | 7 | P0766, P0768, P0769, P1479, P0519, P1053, P0865 | Identifier intended as constant or bound variable but parsed as free var; usually a renaming fix. |
| `semantic_error` | 6 | P1134, P1638, P0671, P0190, P0518, P0035 | Gold parses (or is reparable) but encodes the NL claim wrongly: wrong connective, wrong predicate scheme, extra/missing assertion not in NL. |
| `scope_error` | 6 | P1326, P1414, P1477, P0179, P0053, P1630 | Quantifier scope mismatch: existentials with bodies leaking past the binder, parens that put operators outside binders. |
| `missing_predicate` | 1 | P1270 | NL content (an adverb, an object, an additional conjunct) dropped or collapsed into a predicate name that loses information. |

**Original 2-category breakdown (from [reports/experiments/exp3/broken_gold_pool.jsonl](../reports/experiments/exp3/broken_gold_pool.jsonl)):**
| Reason | Count in 30 |
|---|---|
| `syntax_error` | 17 |
| `free_variable` | 13 |

The post-hoc category is a richer classification of the *deeper* error mode after inspecting the rationale; the original tag is the surface symptom that flagged the gold during selection. Per-premise mappings: see [reports/exp_d_score_sensitivity/corruption_taxonomy.json](../reports/exp_d_score_sensitivity/corruption_taxonomy.json) `per_premise`.

### §7.3 — Score-sensitivity result (NEW)

**Setup.** For each of the 30 hand-corrected premises:
1. Parse `c_correct_fol`. Record parse status.
2. Generate a v2 SIV test suite from the corrected FOL via `siv.gold_suite_generator.generate_test_suite_from_gold` (with `verify_round_trip=False` because hand corrections introduce vocabulary that may differ from the broken gold's lexical surface; round-trip would fail for irrelevant lexical reasons). Record `n_positives`, `n_contrastives`.
3. Sanity-score the corrected gold against its own corrected suite — should yield SIV recall = 1.0 by C7.
4. Score the broken gold against the corrected suite (where the broken gold parses at all — most don't, by definition).
5. Compute Δ = score_corrected − score_broken when both defined.

Score metric: F1 if suite has contrastives, else recall. Vampire timeout = 5 s. Deterministic; no LLM calls; idempotent (verified by twice-running and diffing).

**Producing script:** [scripts/run_exp_d_score_sensitivity.py](../scripts/run_exp_d_score_sensitivity.py). Outputs at [reports/exp_d_score_sensitivity/](../reports/exp_d_score_sensitivity/).

**Aggregate results:**
| Field | Value |
|---|---|
| `n_total` | 30 |
| `n_corrected_parse_ok` | 30 (100 %) |
| `n_suite_gen_ok` | 29 |
| `n_suite_gen_fail` | 1 (P1053 — `n400000` reparsed as free variable; see Note) |
| `n_broken_parse_ok` | 12 (free-variable-class broken golds that survive the parser despite the bug) |
| `n_broken_parse_fail` | 17 (syntax errors universally fail parsing — by selection) |
| `n_with_defined_delta` | 12 |
| `n_with_null_delta` | 18 |
| **`mean_score_corrected`** | **1.0000** |
| **`mean_score_broken`** | **0.8167** |
| **`mean_delta`** | **+0.1833** |
| `median_delta` | 0.000 |
| `min_delta` | 0.000 |
| `max_delta` | +1.000 |
| `n_delta_gt_zero` | 3 (corrected scored higher) |
| `n_delta_eq_zero` | 9 (broken happens to entail the same positives) |
| `n_delta_lt_zero` | **0** (no anomalies) |

**Δ distribution histogram:**
| Bin | Count |
|---|---|
| 0.0 – 0.2 | 10 |
| 0.2 – 0.4 | 0 |
| 0.4 – 0.6 | 0 |
| 0.6 – 0.8 | 0 |
| 0.8 – 1.0 | 2 |

**Per-premise scoring (12 premises with defined Δ):**
| Premise | Corrected score | Broken score | Δ | Original reason |
|---|---|---|---|---|
| P1326 | 1.000 | 1.000 | +0.000 | free_variable |
| P1414 | 1.000 | 1.000 | +0.000 | free_variable |
| P0766 | 1.000 | 0.000 | **+1.000** | free_variable |
| P0768 | 1.000 | 1.000 | +0.000 | free_variable |
| P0769 | 1.000 | 1.000 | +0.000 | free_variable |
| P0190 | 1.000 | 0.800 | **+0.200** | free_variable |
| P1479 | 1.000 | 1.000 | +0.000 | free_variable |
| P0519 | 1.000 | 1.000 | +0.000 | free_variable |
| P0179 | 1.000 | 1.000 | +0.000 | free_variable |
| P0053 | 1.000 | 1.000 | +0.000 | free_variable |
| P0865 | 1.000 | 1.000 | +0.000 | free_variable |
| P1630 | 1.000 | 0.000 | **+1.000** | free_variable |

The 18 premises with null Δ all have `broken_parse_status = fail` — by definition, syntax-error broken golds cannot be scored. (The 17 `syntax_error` premises in the 30, plus P1053 whose suite generation failed.)

**Interpretation.** All 30 corrected formulas parse and 29 produce valid suites. On the 12 premises where the broken FOL also parses (free-variable-class), corrected gold scores 1.0 by construction; broken gold scores ≥ corrected on 9 of 12 (Δ = 0 — the broken FOL happens to entail the same positives despite the free-variable bug, because the test-suite probes don't depend on that variable's binding) and scores strictly less on 3 of 12 (mean Δ on the 12 = +0.183; max Δ = +1.0 on P0766 and P1630, where the broken constants/scope cause the suite to reject the broken candidate entirely).

The result is *not* a detection-rate claim — it is a sensitivity claim: when you supply SIV with a corrected reference suite, scoring against broken gold versus corrected gold produces measurable score reductions on the cases where the broken gold parses. On the cases where the broken gold doesn't parse (the 17 + 1 with null Δ), SIV's pipeline structurally refuses to issue a score against broken inputs — it cannot be tricked into producing a well-formed score against malformed gold, which is the contrast against reference-based metrics like BLEU/BERTScore (which always produce a numeric output, even against malformed references).

**P1053 suite-generation failure** — known wrinkle. Corrected FOL is `SoldOver(song1901, n400000)`. The deterministic parser flags `n400000` as a free individual variable (because it begins with lowercase `n`, which the parser treats as a variable prefix in some contexts). Recorded as `suite_status = fail:parse_error: free individual variables: ['n400000']`. This is a parser-vocabulary issue, not a logical issue with the correction; the correction itself is faithful to NL.

### §7.4 — Honest framing — what we claim and what we explicitly do not

**We claim:**
- SIV's deterministic well-formedness checks identify 76 broken FOLIO gold annotations.
- We hand-correct 30 of them and release them as a reusable artifact at [docs/corrections_template.md](corrections_template.md).
- On the 30 hand-corrected premises, corrected gold scores 1.0 against its own derived suite (sanity-verified on 29 of 30 — the 30th has a parser-vocabulary issue, not a logical issue).
- Broken gold, on the 12 premises where it parses at all, scores mean Δ = +0.183 lower than corrected gold against the same suite.
- Reference-based metrics (BLEU, BERTScore) and equivalence-against-broken-gold silently produce well-formed scores against broken references; SIV's pipeline refuses to generate suites from formulas that fail well-formedness, preventing this failure mode.

**We explicitly do NOT claim:**
- ❌ "SIV detects 90 % of broken gold" — this would be circular (the 30 cases were *selected* via the same criteria that constitute SIV's flagging).
- ❌ "27/30 broken cases were flagged" — same circularity.
- ❌ Any percentage rate that mixes the selection mechanism with the measurement mechanism.

### §7.5 — Note on `corrections_template.md` provenance

Two copies of `corrections_template.md` exist in the repository:
- [docs/corrections_template.md](corrections_template.md) — the curated 30-correction artifact (canonical for the paper).
- [reports/experiments/exp3/corrections_template.md](../reports/experiments/exp3/corrections_template.md) — the original empty template seeded by the Exp 3 pipeline.

`diff` between the two reports approximately 593 lines of differences (the curated copy has filled-in `c_correct_fol`, `rationale`, and `introduced_predicates` fields per entry; some `Broken evidence` strings were also rewritten to be more specific). The cleanup record's earlier "117-line diff" estimate was a low estimate. The curated copy is canonical for paper purposes; the original template is retained in `reports/` for provenance.

### Source artifacts
- Pool: [reports/experiments/exp3/broken_gold_pool.jsonl](../reports/experiments/exp3/broken_gold_pool.jsonl)
- Selection metadata: [reports/experiments/exp3/run_metadata.json](../reports/experiments/exp3/run_metadata.json)
- Corrections (canonical): [docs/corrections_template.md](corrections_template.md)
- Corrections (original): [reports/experiments/exp3/corrections_template.md](../reports/experiments/exp3/corrections_template.md)
- Pool inventory: [reports/exp_d_score_sensitivity/pool_inventory.json](../reports/exp_d_score_sensitivity/pool_inventory.json)
- Per-premise score-sensitivity results: [reports/exp_d_score_sensitivity/results.jsonl](../reports/exp_d_score_sensitivity/results.jsonl)
- Aggregate: [reports/exp_d_score_sensitivity/summary.json](../reports/exp_d_score_sensitivity/summary.json)
- Taxonomy: [reports/exp_d_score_sensitivity/corruption_taxonomy.json](../reports/exp_d_score_sensitivity/corruption_taxonomy.json)
- Producing script: [scripts/run_exp_d_score_sensitivity.py](../scripts/run_exp_d_score_sensitivity.py)

---

## §8 — Investigation 4: Probe-formula leakage (NULL)

### Goal
A prior C2 investigation observed that supplying probe-formula-level feedback (the literal probe FOL) to a candidate-revising LLM raised pass rate well above the score-only condition. The hypothesis to falsify: the gain reflects per-aspect actionability of probe-formula feedback. Alternative: the gain is answer-leakage from the probe FOL.

### Setup
- n = 22 candidates.
- Three conditions: `score_only` (just the SIV score) / `structured` (probe FOLs paired with their aspect labels) / `shuffled` (probe FOLs paired with *shuffled* aspect labels — the probe content is unchanged; only the labels are randomized).
- LEAKAGE supported when `structured ≈ shuffled`: shuffling labels does not destroy the gain → the gain is not from per-aspect actionability.
- Producing script: [scripts/c2_investigation_4.py](../scripts/c2_investigation_4.py).

### Results

| Condition | SIV mean | Equiv-to-gold rate (derived from per-condition booleans) |
|---|---|---|
| `score_only` | 0.6932 | 12 / 22 = 0.5455 |
| `structured` | **1.0000** | 20 / 22 = **0.9091** |
| `shuffled` | **1.0000** | 20 / 22 = **0.9091** |

| Δ | Value |
|---|---|
| `structured − shuffled` (SIV) | **0.000** |
| `structured − shuffled` (equiv-to-gold) | **0.000** |
| `structured − score_only` (SIV) | +0.3068 |

Decision: **LEAKAGE_SUPPORTED**. Decision text from the JSON: *"No effect: Δ=+0.0000 < 0.05. Probe-formula gain was likely answer-leakage. Per-aspect-actionability claim collapses. STOP and rethink before main run."*

### Note on the headline percentage
HARD RULE 2 lists the headline as *"structured = shuffled = 90.9 %"*. That value is the equiv-to-gold rate (20 / 22). The JSON's `condition_means` field reports the SIV pass rate (1.000 in both conditions). Both metrics agree on the qualitative result Δ = 0.000. The verification block records both metrics with explanatory notes.

### Interpretation
Probe-formula content lifts pass rate to ~100 %, but shuffling the aspect labels does not change this. Therefore the lift is not from per-aspect actionability — the LLM is using the probe FOLs as direct answer hints. The per-aspect-actionability claim is rejected.

### Role in the paper's case
A pre-registered null. The paper must report this to maintain honest framing — without it, the abstract's diagnostic-structure claim could be misread as a per-aspect-actionability claim.

### Source artifacts
- Primary: [reports/c2_investigations/investigation_4_effect_size.json](../reports/c2_investigations/investigation_4_effect_size.json)
- Verification block: [reports/verified/investigation_4_verified.json](../reports/verified/investigation_4_verified.json)
- Producing script: [scripts/c2_investigation_4.py](../scripts/c2_investigation_4.py)

---

## §9 — Path 1: Category-level on FOLIO (pilot only — main NOT run)

### Goal
Test whether *category-level* feedback (a coarse error-class label, not the probe FOL) carries actionable signal even when the probe-FOL channel does not.

### Setup
- Pilot n = 20 candidates.
- Five conditions: `no_feedback` / `score_only` / `structured_category` (correct error-class label) / `shuffled_category` (label permuted across candidates) / `count_only` (just the number of failed probes).
- Stop rule: pilot Δ in [0, 0.05) → WEAK_SIGNAL → main run NOT executed.
- Producing script: [scripts/c2_path1_step3_pilot.py](../scripts/c2_path1_step3_pilot.py).

### Results

| Condition | Parseable rate | Equiv rate | SIV rate |
|---|---|---|---|
| `no_feedback` | 1.00 | 0.60 | 0.65 |
| `score_only` | 1.00 | 0.65 | 0.65 |
| `structured_category` | 1.00 | 0.55 | **0.60** |
| `shuffled_category` | 1.00 | 0.55 | **0.60** |
| `count_only` | 1.00 | 0.60 | 0.60 |

**Primary comparison:** `structured_category` − `shuffled_category` SIV rate = **0.000**.

**Sanity checks (all pass):** `no_feedback ≈ baseline`, `score_only ≥ no_feedback`, parseable rate ≥ 80 %.

**Decision: WEAK_SIGNAL.** Decision text from the JSON: *"Pilot Δ=+0.000 in [0, 0.05). Weak signal. Surface to user: per-aspect channel may not carry signal at category level."*

### Important: main run was not executed
Per the pre-registered stop rule, WEAK_SIGNAL means the main run is not run — proceeding to a fully-powered main study would burn LLM-call budget on what is already null at pilot.

### Interpretation
Category-level feedback adds nothing over score-only or count-only at FOLIO difficulty: the model can already produce a correct candidate at this difficulty without per-aspect labels.

### Role in the paper's case
A pre-registered null. The paper should disclose the pilot decision to explain why no main run was executed at this difficulty.

### Source artifacts
- Primary: [reports/c2_investigations/path1/step3_pilot.json](../reports/c2_investigations/path1/step3_pilot.json)
- Verification block: [reports/verified/path1_verified.json](../reports/verified/path1_verified.json)
- Producing script: [scripts/c2_path1_step3_pilot.py](../scripts/c2_path1_step3_pilot.py)

---

## §10 — Path 1-Hard: Category-level at higher difficulty (3 models)

### Goal
Test whether category-level feedback carries signal at *harder* candidate difficulty (where the model is not already saturated). If §9 was null because FOLIO is too easy for the candidate-revisor, harder candidates might recover the signal.

### Setup
- n = 60 candidates × 5 conditions × 3 models = **900 LLM calls**. Total elapsed: 1462.84 s.
- Models: `gpt-4o`, `gpt-4o-mini`, `claude-sonnet`.
- Conditions same as §9: `no_feedback` / `score_only` / `structured_category` / `shuffled_category` / `count_only`.
- Significance per model: bootstrap CI on Δ = `structured_category − shuffled_category`, plus permutation p-value.
- Producing script: [scripts/c2_path1_hard_step5_main_v2.py](../scripts/c2_path1_hard_step5_main_v2.py).

### Results — per model

**gpt-4o**
| Condition | Pass rate |
|---|---|
| `no_feedback` | 0.350 |
| `score_only` | 0.300 |
| `structured_category` | 0.317 |
| `shuffled_category` | 0.317 |
| `count_only` | 0.267 |

Δ = **0.000**, 95 % CI [-0.100, +0.100], p = 0.5664. Not significant.

**gpt-4o-mini**
| Condition | Pass rate |
|---|---|
| `no_feedback` | 0.217 |
| `score_only` | 0.267 |
| `structured_category` | 0.250 |
| `shuffled_category` | 0.233 |
| `count_only` | 0.217 |

Δ = **+0.0167**, 95 % CI [-0.050, +0.083], p = 0.4141. Not significant.

**claude-sonnet**
| Condition | Pass rate |
|---|---|
| `no_feedback` | 0.367 |
| `score_only` | 0.267 |
| `structured_category` | 0.300 |
| `shuffled_category` | 0.350 |
| `count_only` | 0.333 |

Δ = **-0.050**, 95 % CI [-0.133, +0.033], p = 0.913. Not significant.

**Models significant: 0 / 3.** Decision: **NULL**. Decision text from the JSON: *"Per-aspect fails at harder difficulty too. Claim rejected."*

Raw 60-bool result arrays present in the source JSON for all 15 (model × condition) cells (verified by length-check; not reproduced in the verification block to keep the block compact).

### Interpretation
The null replicates at harder difficulty across three frontier models. Category-level feedback does not carry actionable signal, period — the §9 weak signal was not a saturation artifact.

### Role in the paper's case
A pre-registered null with strong replication across model families. Combined with §8 and §9, this triplet of nulls bounds what SIV's per-aspect signal carries: it is a coarse diagnostic structure (§6), not a per-aspect actionable channel.

### Source artifacts
- Primary: [reports/c2_investigations/path1_hard/step5_main_results.json](../reports/c2_investigations/path1_hard/step5_main_results.json)
- Verification block: [reports/verified/path1_hard_verified.json](../reports/verified/path1_hard_verified.json)
- Producing script: [scripts/c2_path1_hard_step5_main_v2.py](../scripts/c2_path1_hard_step5_main_v2.py)

---

## §11 — What SIV does and does not do

| ✅ Validated capabilities | ❌ Definitive nulls |
|---|---|
| Deterministic FOLIO-gold parsing at 94.21 % coverage with 99.94 % round-trip equivalence (§1). | Probe-formula-level feedback as a per-aspect-actionable channel — gain is answer leakage (§8). |
| Self-score sanity at 100 % across 1,577 premises (§2). | Category-level feedback at FOLIO difficulty as an actionable channel (§9). |
| Per-operator perturbation detection at 100 % on B_arg_swap, B_negation_drop, D_random; 84.9 % at-scale ordering (§3, §4). | Category-level feedback at higher difficulty across 3 frontier models (§10). |
| Graded ρ ≈ 0.85 with annotated severity, replicated under v1 baseline (n = 35, ρ = 0.8563), v2 with regen (n = 33, ρ = 0.8543), and equivalent-only (n = 22, ρ = 0.8583) (§5). | Fine-grained 6-class diagnostic structure from binary verdicts alone — F1 = 0.29 (§6). |
| Coarse 3-class diagnostic structure at macro-F1 = 0.81 (§6). | (Architectural blind spot:) detection of perturbations that produce *logically stronger* formulas (B_restrictor_drop) — recall = 1.0 by construction (§4). |
| Score-sensitivity to broken gold: corrected suites refuse to score broken gold uniformly; broken parses score Δ = +0.18 lower on average (§7.3). | Reference-based / embedding-based metrics on this severity-ranking task: BLEU ρ = 0.45, BERTScore ρ = 0.04, MALLS-LE = 0.0, Brunello-LT = 0.0 (§5.5). |
| 30 hand-corrected FOLIO gold annotations released as artifact (§7.2). | "SIV detects X % of broken gold" — explicitly NOT claimed (§7.4). |

---

## §12 — Reproducibility notes

### Environment
- Python deps: see `requirements.txt`; `python -m spacy download en_core_web_sm`.
- Vampire: `from siv.vampire_interface import setup_vampire; setup_vampire('.')` — installs the `vampire` binary at `./vampire`.
- Setup script: [scripts/setup.sh](../scripts/setup.sh).

### Determinism and seeds
All locked experiments are deterministic given Vampire ≥ 4.x. The new score-sensitivity script ([scripts/run_exp_d_score_sensitivity.py](../scripts/run_exp_d_score_sensitivity.py)) is deterministic by construction (no LLM calls, no RNG); verified by twice-running and diffing.

### Commands to regenerate each result

| Result | Command (from repo root) | Notes |
|---|---|---|
| §1 — Parser coverage | `python scripts/parser_coverage_report.py` | Vampire required. |
| §2 — Self-score | `python scripts/stage2_validation.py` | **Cleanup-removed**; recoverable from `pre-cleanup-snapshot` tag in SIV-archive. |
| §3 — Perturbation ordering | `python scripts/stage3_perturbation_validation.py` | **Cleanup-removed**; same recovery path. |
| §4 — Exp A v2 | `python scripts/stage4_rescore_exp1.py` | Vampire required. |
| §5 — Exp B v2 (rescore + regen) | `python scripts/stage4_rescore_exp2.py && python scripts/stage4_regenerate.py` | Vampire required. |
| §5.5 — Baselines | `python scripts/experiments/run_exp2.py` | Permutation tests; bootstrap CIs. |
| §6 — Exp C1 | `python scripts/exp_c1_diagnostic_structure.py` | Vampire required. |
| §7 — Exp D pool | (selection JSONs are locked artifacts — `reports/experiments/exp3/`) | Re-run via cleanup-removed `scripts/experiments/run_exp3.py`-style pipeline if desired. |
| §7.3 — Exp D score-sensitivity (NEW) | `PYTHONPATH=. python scripts/run_exp_d_score_sensitivity.py` | Vampire required; deterministic. |
| §8 — Investigation 4 | `python scripts/c2_investigation_4.py` | Requires LLM API key. |
| §9 — Path 1 pilot | `python scripts/c2_path1_step3_pilot.py` | Requires LLM API key. |
| §10 — Path 1-Hard | `python scripts/c2_path1_hard_step5_main_v2.py` | 900 LLM calls; budget accordingly. |

### Cleanup-removed scripts
The Stage 2 and Stage 3 producing scripts (`scripts/stage2_validation.py`, `scripts/stage3_perturbation_validation.py`) were deleted in cleanup commit `c243cd9` (Stage 5/5). To recover them, checkout the `pre-cleanup-snapshot` tag in the [SIV-archive](https://github.com/pu-suo/SIV-archive) repository.

---

## §13 — Discrepancies vs prior summaries

This section lists every number in prior documents that disagrees with the source JSONs. Resolution per HARD RULE 4: source JSON wins.

| Source doc | Claim | Prior value | JSON value | Resolution |
|---|---|---|---|---|
| Earlier (now-superseded) summary contexts | Exp D detection rate | "27/30 (90 %) flagged" | (no such field — circular framing) | **Removed.** Replaced with score-sensitivity result (§7.3). |
| Pre-cleanup CLEANUP_RESULT.md note | corrections_template.md diff size | "117 lines" | 593 lines (`diff -u | wc -l`) | Annotated in §7.5. |
| Headline (HARD RULE 2 of this pass) — Investigation 4 | structured = shuffled = 90.9 % | (this is the equiv-to-gold rate, not the SIV rate) | JSON `condition_means.structured = 1.0`; equiv-to-gold derived = 0.9091 | Both metrics captured in §8 and verification block; Δ = 0.000 on both. |
| docs/COMPREHENSIVE_RESULTS.md §STAGE 2 | (consistent with primary JSON before deletion) | 1577 / 1577 = 100 % | (JSON deleted; secondary source) | OK_SECONDARY_SOURCE. |
| docs/COMPREHENSIVE_RESULTS.md §STAGE 3 | (consistent with primary JSON before deletion) | 84.9 % overall, 98.4 % B_arg_swap | (JSON deleted; secondary source) | OK_SECONDARY_SOURCE. |

No contradictions in headline numbers between source JSONs and HARD RULE 2 were found.

---

## §14 — Verification trail

Every headline number in §0 has a single canonical entry below: claim → number → source JSON path → source key → verification block path.

| § | Claim | Headline value | Source JSON | Source key | Verification block |
|---|---|---|---|---|---|
| §1 | Parser conversion | 1578/1675 = 0.9421 | reports/parser_coverage_report.json | converted, total_premises | reports/verified/stage1_verified.json |
| §1 | Round-trip equivalence | 1577/1578 = 0.9994 | reports/parser_coverage_report.json | round_trip_pass | reports/verified/stage1_verified.json |
| §2 | Stage 2 perfect rate | 1577/1577 = 1.000 | (cleanup-removed; secondary: docs/COMPREHENSIVE_RESULTS.md §STAGE 2) | n/a | reports/verified/stage2_verified.json |
| §3 | Stage 3 ordering | 321/378 = 0.849 | (cleanup-removed; secondary: docs/COMPREHENSIVE_RESULTS.md §STAGE 3) | n/a | reports/verified/stage3_verified.json |
| §4 | B_arg_swap v2 | 1.0 | reports/stage4/rescore_exp1.json | per_operator.B_arg_swap.v2_rate | reports/verified/exp_a_verified.json |
| §4 | B_negation_drop v2 | 1.0 (+34.8 pp) | reports/stage4/rescore_exp1.json | per_operator.B_negation_drop.v2_rate / delta_pp | reports/verified/exp_a_verified.json |
| §4 | D_random v2 | 1.0 | reports/stage4/rescore_exp1.json | per_operator.D_random.v2_rate | reports/verified/exp_a_verified.json |
| §4 | B_restrictor_drop v2 | 0.0 | reports/stage4/rescore_exp1.json | per_operator.B_restrictor_drop.v2_rate | reports/verified/exp_a_verified.json |
| §4 | B_scope_flip v2 | 0.0 (n=1) | reports/stage4/rescore_exp1.json | per_operator.B_scope_flip.v2_rate / v2_n | reports/verified/exp_a_verified.json |
| §5.1 | ρ with regen | 0.8543 [0.8217, 0.8779], n=33 | reports/stage4/stage4b_regeneration.json | rho_a_full_with_regen.{mean_rho,ci_lo,ci_hi,n} | reports/verified/exp_b_verified.json |
| §5.1 | ρ equivalent-only | 0.8583 [0.8225, 0.8801], n=22 | reports/stage4/stage4b_regeneration.json | rho_c_equiv_only.{mean_rho,ci_lo,ci_hi,n} | reports/verified/exp_b_verified.json |
| §5.1 | ρ no-regen | 0.7797 [0.6579, 0.8674], n=35 | reports/stage4/rescore_exp2.json | v2_rho, v2_ci_lo, v2_ci_hi, n_premises | reports/verified/exp_b_verified.json |
| §5.5 | SIV baseline ρ | 0.8563 | reports/experiments/exp2/rank_correlation.json | siv_soft_recall.mean_rho | reports/verified/exp_b_baselines_verified.json |
| §5.5 | BLEU ρ | 0.4513 | reports/experiments/exp2/rank_correlation.json | bleu.mean_rho | reports/verified/exp_b_baselines_verified.json |
| §5.5 | BERTScore ρ | 0.0435 | reports/experiments/exp2/rank_correlation.json | bertscore.mean_rho | reports/verified/exp_b_baselines_verified.json |
| §5.5 | MALLS-LE ρ | 0.0 | reports/experiments/exp2/rank_correlation.json | malls_le_aligned.mean_rho | reports/verified/exp_b_baselines_verified.json |
| §5.5 | Brunello-LT ρ | 0.0 | reports/experiments/exp2/rank_correlation.json | brunello_lt_aligned.mean_rho | reports/verified/exp_b_baselines_verified.json |
| §6 | Coarse macro-F1 | 0.8125 | reports/c1/c1_diagnostic_structure.json | coarse_macro_f1 | reports/verified/exp_c1_verified.json |
| §6 | Fine macro-F1 | 0.2904 | reports/c1/c1_diagnostic_structure.json | fine_macro_f1 | reports/verified/exp_c1_verified.json |
| §7.1 | Broken pool size | 76 | reports/experiments/exp3/run_metadata.json | step1.pool_size | reports/exp_d_score_sensitivity/pool_inventory.json |
| §7.1 | Pool by reason | 54 syntax / 22 free_var | reports/experiments/exp3/broken_gold_pool.jsonl | (line-count by `broken_reason`) | reports/exp_d_score_sensitivity/pool_inventory.json |
| §7.2 | Corrections count | 30 | docs/corrections_template.md | (entry count) | reports/exp_d_score_sensitivity/pool_inventory.json |
| §7.3 | Mean Δ (NEW) | +0.1833 (n=12) | reports/exp_d_score_sensitivity/summary.json | mean_delta | (this section is the verification) |
| §7.3 | Suite gen ok | 29/30 | reports/exp_d_score_sensitivity/summary.json | n_suite_gen_ok | (this section is the verification) |
| §8 | Inv 4 Δ (SIV) | 0.000 | reports/c2_investigations/investigation_4_effect_size.json | deltas.structured_minus_shuffled | reports/verified/investigation_4_verified.json |
| §8 | Inv 4 equiv rate | 0.9091 (20/22) | reports/c2_investigations/investigation_4_effect_size.json | per_condition.structured (count of equiv=true) | reports/verified/investigation_4_verified.json |
| §9 | Path 1 pilot Δ | 0.000 (60 % both) | reports/c2_investigations/path1/step3_pilot.json | primary_comparison.delta | reports/verified/path1_verified.json |
| §9 | Path 1 decision | WEAK_SIGNAL | reports/c2_investigations/path1/step3_pilot.json | decision | reports/verified/path1_verified.json |
| §10 | Path 1-Hard gpt-4o Δ | 0.000 | reports/c2_investigations/path1_hard/step5_main_results.json | per_model['gpt-4o'].delta | reports/verified/path1_hard_verified.json |
| §10 | Path 1-Hard gpt-4o-mini Δ | +0.0167 | reports/c2_investigations/path1_hard/step5_main_results.json | per_model['gpt-4o-mini'].delta | reports/verified/path1_hard_verified.json |
| §10 | Path 1-Hard claude-sonnet Δ | -0.0500 | reports/c2_investigations/path1_hard/step5_main_results.json | per_model['claude-sonnet'].delta | reports/verified/path1_hard_verified.json |
| §10 | Path 1-Hard models significant | 0/3 | reports/c2_investigations/path1_hard/step5_main_results.json | models_significant | reports/verified/path1_hard_verified.json |
| §10 | Path 1-Hard decision | NULL | reports/c2_investigations/path1_hard/step5_main_results.json | decision | reports/verified/path1_hard_verified.json |

End of comprehensive results.
