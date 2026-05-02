# SIV Paper — Experiment Specification

This is the implementation spec for the four experiments that define SIV's empirical
case. Read this entire document before writing any code. The experiments are listed in
execution order. Each experiment has a smoke test that **must pass** before its full run.

## What this paper claims

SIV is the only NL→FOL evaluation metric that is simultaneously:

- **Reference-free**: scores against the natural-language premise, not against a gold FOL.
- **Label-free**: requires no entailment labels (unlike EPR).
- **Graded**: produces a continuous score (unlike binary equivalence-based metrics).
- **Per-aspect diagnostic**: produces a structured per-probe verdict (unlike single-number metrics).

Each experiment validates one of these properties. Don't conflate experiments — each one
targets a specific claim, and the data each one produces is non-substitutable.

## Properties → experiments map

| Property | Experiment | Headline finding |
|---|---|---|
| Logical correctness (parity) | Exp 1 — binary correctness | SIV ≥ MALLS-LE-aligned, Brunello-LT on the standard task; BLEU/BERTScore lose |
| Graded scoring | Exp 2 — graded correctness | SIV produces a meaningful gradient where binary metrics produce a cliff |
| Reference-free | Exp 3 — reference failure | When gold is broken, reference-based metrics inherit the brokenness; SIV doesn't |
| Per-aspect diagnostic | Exp 4 — diagnostic confusion matrix | SIV's per-probe pattern identifies error type; single-number metrics cannot |
| Label-free | (statement only) | No experiment in the paper uses entailment labels |

## Repository assumptions

The cleanup pass has been run. The relevant modules are:

- `siv/extractor.py` — `extract_sentence(nl: str, client) -> SentenceExtraction`
- `siv/compiler.py` — `compile_canonical_fol`, `compile_sentence_test_suite`
- `siv/contrastive_generator.py` — `derive_witness_axioms`, `classify_structure`
- `siv/scorer.py` — `score(test_suite, candidate_fol, timeout_s) -> ScoreReport`
- `siv/aligner.py` — `extract_symbols_from_fol`, `align_symbols`, `rewrite_test_suite`, `rewrite_fol_strings`
- `siv/malls_le.py` — `malls_le_equivalence(candidate, gold, timeout)` and aligned variant
- `siv/brunello_lt.py` — Z3 equivalence check, raw and aligned variants
- `siv/nltk_perturbations.py` — operators including `B_arg_swap`, `B_scope_flip`,
  `B_restrictor_drop`, `C_negation_drop`, `D_random_predicates`, plus
  `select_perturbation(expr, tier, ...)` dispatcher and `NotApplicable` exception
- `siv/stratum_classifier.py` — `classify_stratum_from_fol(fol_string) -> Optional[str]`
- `siv/fol_utils.py` — `parse_fol`, `normalize_fol_string`, `is_valid_fol`
- `siv/vampire_interface.py` — `vampire_check`, `check_entailment`, `prove_strict`

The cached test suites live at `reports/test_suites/test_suites_train.jsonl` (FOLIO train
split, ~1500 premises). **Reuse the cache. Never regenerate cached extractions** — they
are expensive and the cache covers 98.9% of FOLIO train.

The new experiment outputs go in `reports/experiments/{exp1,exp2,exp3,exp4}/`. Each
experiment writes its own subtree; do not write outside it.

## Required pre-work (do this first, before any experiment)

These bug fixes are blocking. They corrupt scores in unknown ways if left in. Do not
start any experiment until they are fixed and the regression test passes.

### Pre-work A — Validator escape: free-variable canonicals

Diagnostic showed 46 of 1523 cached canonicals contain free variables (e.g.,
`CopyrightViolation(x)` with no enclosing quantifier). The validator at the
extraction-to-compilation boundary should reject these but doesn't.

**Fix location**: `siv/compiler.py`, in the function that produces canonical FOL from
a `SentenceExtraction`. Add a post-compilation check: parse the result with
`siv.fol_utils.parse_fol`, walk the AST, and assert every variable referenced in an
`ApplicationExpression` argument position is bound by an enclosing `AllExpression` or
`ExistsExpression`. If not, raise `SchemaViolation("free variable in canonical FOL: {var}")`.

**Test**: add a regression test in `tests/test_compiler.py` that constructs a
`SentenceExtraction` with a known-broken formula (atomic predicate referencing
unbound `x` at the top level) and asserts the validator raises.

**Cache cleanup**: re-validate the existing cache. For each row in
`reports/test_suites/test_suites_train.jsonl`, run the new validator on `canonical_fol`.
Rows that fail get marked `extraction_failure: validator_post_fix` in a new
`reports/test_suites/test_suites_train.failures.jsonl` file and dropped from the active
cache. Do not re-run the extractor on these — they are dropped from the corpus.

### Pre-work B — Suite-generator scope bug

Diagnostic showed 16 premises where the suite generator strips outer quantifiers from
nested existentials and leaves the inner variable free in the generated probe (e.g.,
canonical `exists y.(exists z.(...PerformanceOf(y,z)...))` becomes probe
`exists v0.(PerformanceOf(v0, v1))` with `v1` unbound).

**Fix location**: `siv/compiler.py`, the test-suite generator path that produces
"atomic positive" probes from sub-formulas. When emitting a probe that contains a free
variable in the original formula's binding scope, either re-bind the variable with an
existential at the top of the probe, or skip the probe entirely (whichever the existing
generator semantics call for).

**Test**: regression test that constructs a canonical with nested `exists y.(exists z.(...))`
and asserts every generated positive probe is closed.

### Pre-work C — Contrastive coverage scoping

Diagnostic showed 271 premises (17.8%) have zero contrastives, concentrated in
`simple_existential` (94%), `bare_implies_atomic_antecedent` (80%),
`existential_compound_nucleus` (75%), `top_level_disjunction` (75%).

**Decision**: do not expand the contrastive operators in this round. Instead:

1. Tag every cached test suite with its `structural_class` (already present in
   `test_suites_train.jsonl` per inspection).
2. In the paper's results sections, when reporting any contrastive-dependent metric
   (precision, F1), explicitly scope the denominator: "computed on the
   contrastive-eligible subset (N=1252, 82.2% of FOLIO train)."
3. The non-eligible subset still gets reported, just on recall-only.

This is a scope statement, not a code change. **No code action required for
pre-work C** beyond making sure downstream analyses respect the scoping. Add a
helper in `scripts/experiments/common.py` (see below) called
`is_contrastive_eligible(test_suite_row) -> bool`.

### Pre-work D — Common utilities

Create `scripts/experiments/common.py` with these helpers, used by all four experiments:

```python
# Loaders for cached artifacts
def load_test_suites(path) -> Dict[premise_id, dict]: ...
def load_candidates(path) -> List[dict]: ...

# Subset definitions
def is_contrastive_eligible(test_suite_row) -> bool: ...
def passes_aligned_subset_filter(test_suite_row, gold_fol) -> Tuple[bool, dict]:
    """Returns (passes, criteria_dict). See Exp 1 for criteria definition."""

# Metric runners — single (candidate, reference) call per metric
def score_bleu(candidate_fol, gold_fol) -> float: ...
def score_bertscore(candidate_fol, gold_fol) -> float: ...
def score_malls_le_raw(candidate_fol, gold_fol, timeout) -> float: ...
def score_malls_le_aligned(candidate_fol, gold_fol, timeout) -> float: ...
def score_brunello_lt_raw(candidate_fol, gold_fol, timeout) -> float: ...
def score_brunello_lt_aligned(candidate_fol, gold_fol, timeout) -> float: ...
def score_siv_strict(test_suite_row, candidate_fol, timeout) -> ScoreReport: ...
def score_siv_soft(test_suite_row, candidate_fol, timeout, threshold=0.6) -> ScoreReport: ...

# Stats
def paired_bootstrap_ci(scores_a, scores_b, n_resamples=1000, alpha=0.05) -> Tuple[float, float]: ...
def paired_permutation_p(scores_a, scores_b, n_permutations=10000) -> float: ...
def auc_roc(scores, labels) -> float: ...
```

Each metric runner returns either a float in `[0, 1]` or `None` on parse error / timeout.
Log `None` cases with the reason; never silently coerce to 0.

---

# Experiment 1 — Binary Correctness (parity demonstration)

**Claim**: On the standard logical-correctness task, SIV is at least as good as the
strongest reference-based baselines (MALLS-LE-aligned, Brunello-LT-aligned), and all
three crush surface metrics (BLEU, BERTScore).

**Why this experiment exists**: reviewers will ask "does SIV at least handle the basic
case?" Without this, the harder experiments don't get credit. This is parity, not a
unique win. Treat it as a supporting result, not the headline.

## 1.1 Aligned-subset filter

The filter excludes premises where SIV's extraction style diverges from FOLIO gold
in ways that confound metric comparison. The filter is applied once, deterministically,
producing `reports/experiments/exp1/aligned_subset_manifest.jsonl`.

A premise enters the aligned subset iff **all** of these hold:

1. **SIV extraction succeeded.** `canonical_fol` is non-null and passes the post-fix
   validator (no free variables, no vacuous quantifiers).
2. **Gold parses cleanly.** `parse_fol(gold_fol)` returns a non-None expression.
3. **Predicate-name Jaccard ≥ 0.6** between SIV canonical and gold. Lowercase, strip
   non-alphanumerics, compare as sets.
4. **Arity match for shared predicates.** Every predicate name appearing in both SIV
   canonical and gold has the same arity in both.
5. **Quantifier-skeleton match.** Same number of universals, same number of
   existentials, max nesting depth differs by at most 1.
6. **Not in the broken-gold list.** Cross-reference against
   `reports/phase1_pillar1/failure_analysis.json`; exclude the 149 syntax-error gold
   and ~200 unprovable-by-design gold.

Manifest schema, one row per premise:

```json
{
  "premise_id": "P0096",
  "passes": true,
  "criteria": {
    "extraction_ok": true,
    "gold_parses": true,
    "jaccard": 0.83,
    "arity_match": true,
    "quant_skeleton_match": true,
    "not_broken_gold": true
  },
  "siv_canonical_fol": "...",
  "gold_fol": "..."
}
```

**Acceptance**: yield is between 400 and 700 premises. If under 400, relax criterion 3
to Jaccard ≥ 0.5 and document the relaxation. Do not relax criteria 1, 4, or 5.

## 1.2 Candidate construction

For each premise in the aligned subset, the candidate set is **6 candidates**:

| Index | Candidate type | Operator | Source module |
|---|---|---|---|
| 0 | gold | (identity) | gold FOL |
| 1 | B_arg_swap | `B_arg_swap` | `siv.nltk_perturbations` |
| 2 | B_negation_drop | `C_negation_drop` | `siv.nltk_perturbations` |
| 3 | B_scope_flip | `B_scope_flip` | `siv.nltk_perturbations` |
| 4 | B_restrictor_drop | `B_restrictor_drop` | `siv.nltk_perturbations` |
| 5 | D_random | `D_random_predicates` | `siv.nltk_perturbations` |

Note: the spec calls index 2 "B_negation_drop". The library function is named
`C_negation_drop` because in the original tier taxonomy negation-removal was a Tier-C
operator. We rename it for the paper's purposes; the function call stays the same.

Each operator runs on the **gold FOL**, not on SIV canonical. Operators may raise
`NotApplicable`. If fewer than 2 Tier-B operators apply (indices 1-4), drop the premise
from this experiment with `applicable: false` recorded in the candidate file.

Output: `reports/experiments/exp1/candidates.jsonl`. One row per (premise, candidate)
pair. Schema:

```json
{
  "premise_id": "P0096",
  "candidate_index": 1,
  "candidate_type": "B_arg_swap",
  "candidate_fol": "...",
  "applicable": true,
  "applicability_reason": null  // or NotApplicable.message if false
}
```

**Determinism**: lock the seed for `D_random_predicates`. Save the seed value in
`reports/experiments/exp1/run_metadata.json`.

## 1.3 Smoke test (pass before full scoring)

Pull 30 random premises from the aligned subset. For each, score `(gold,
B_arg_swap_perturbation)` with SIV-soft. Compute fraction where SIV-soft(gold) >
SIV-soft(perturbation).

**Pass criterion**: ≥ 0.80 (24 of 30). Log the result to
`reports/experiments/exp1/smoke_test.json`.

**If it fails**: stop. The aligned-subset filter is not tight enough. Do not proceed to
full scoring. Surface the failure with the 30-row score table for manual inspection.

## 1.4 Score all candidates with all metrics

For every `(premise, candidate)` row in `candidates.jsonl` where `applicable=true`,
compute:

- BLEU vs gold FOL string
- BERTScore F1 vs gold FOL string
- MALLS-LE-raw with `timeout=10`
- MALLS-LE-aligned with `timeout=10`
- Brunello-LT-raw with `timeout=10`
- Brunello-LT-aligned with `timeout=10`
- SIV-strict (mean recall, mean F1, min recall) with `timeout=10`
- SIV-soft (mean recall, mean F1, min recall) with `timeout=10`, `threshold=0.6`

Reuse the cached test suite for each premise. Generate a fresh suite **only** if the
premise is missing from the cache.

Output: `reports/experiments/exp1/scored_candidates.jsonl`. One row per
`(premise, candidate)` with all metric scores attached. `null` for any metric that
returned `None` (parse error or timeout); record the reason in a parallel
`metric_status` field.

**Implementation note**: SIV scoring is the slowest. Run candidates in batches and
parallelize across premises. Timeout per Vampire call is 10s.

## 1.5 Primary analysis

Two tables, one figure.

**Table 1.5a — Per-tier discrimination AUC**

For each metric M, compute AUC of `M predicting "is_gold"` across all
`(premise, candidate)` pairs in the experiment. Compute paired-bootstrap 95% CI and
paired-permutation p-value vs SIV-soft (min-recall) as the reference.

Output: `reports/experiments/exp1/per_tier_auc.csv` and `.json`.

| Metric | AUC | 95% CI | p (vs SIV-soft min-recall) |
|---|---|---|---|
| BLEU | … | … | … |
| BERTScore | … | … | … |
| MALLS-LE-raw | … | … | … |
| MALLS-LE-aligned | … | … | … |
| Brunello-LT-raw | … | … | … |
| Brunello-LT-aligned | … | … | … |
| SIV-strict (mean recall) | … | … | … |
| SIV-strict (min recall) | … | … | … |
| SIV-soft (mean recall) | … | … | … |
| SIV-soft (min recall) | reference | — | — |

**Table 1.5b — Per-operator detection rate**

Detection rate for operator O = fraction of premises where M(gold) > M(O-perturbation).
For each operator and each metric.

Output: `reports/experiments/exp1/per_operator.csv` and `.json`.

| Operator | BLEU | BERTScore | MALLS-LE-aligned | Brunello-LT-aligned | SIV-soft (min recall) |
|---|---|---|---|---|---|
| B_arg_swap | … | … | … | … | … |
| B_negation_drop | … | … | … | … | … |
| B_scope_flip | … | … | … | … | … |
| B_restrictor_drop | … | … | … | … | … |
| D_random | … | … | … | … | … |

**Figure 1.5c — Score-gap distributions**

For each metric, plot the distribution of `M(gold) − M(perturbation)` across all
premises and all four Tier-B operators. SIV's distribution should be tight and
right-shifted. BLEU/BERTScore distributions should be near zero.

Output: `reports/experiments/exp1/score_gap_distributions.png` (multi-panel).

## 1.6 Acceptance

Experiment 1 succeeds if **either**:

(a) SIV-soft (min-recall) is statistically tied with or above MALLS-LE-aligned and
Brunello-LT-aligned on Tier-B AUC (no significant difference, p > 0.05); both crush
BLEU/BERTScore (significant, p < 0.01).

OR

(b) SIV-soft is significantly above all baselines on at least 2 of 4 Tier-B operators.

Either way, the result is "SIV handles the standard task." If neither (a) nor (b)
holds, escalate before writing up — the parity story is not supported and the paper
needs a re-think.

---

# Experiment 2 — Graded Correctness (the gradedness pillar)

**Claim**: SIV produces a meaningful continuous score across a spectrum of
partial-correctness candidates. Binary equivalence-based metrics (MALLS-LE,
Brunello-LT) collapse all non-equivalent candidates to a single value (0), losing the
ability to rank "almost correct" above "completely wrong."

**Why this experiment matters**: this is one of the only places SIV provably wins
against the equivalence-based baselines, because they cannot in principle distinguish
levels of incorrectness.

## 2.1 Premise selection

Subset: 50 hand-curated premises from the aligned subset of Experiment 1. Curation
criterion: structurally rich enough to support partial-correctness candidates
(rules out simple atomics; favors universals with multiple consequents, conjunctive
restrictors, nested quantifiers).

Output: `reports/experiments/exp2/curated_premises.jsonl`. Schema:

```json
{
  "premise_id": "P0123",
  "nl": "...",
  "gold_fol": "...",
  "siv_canonical_fol": "...",
  "selection_reason": "two-consequent universal — supports partial-consequent"
}
```

**Manual step**: hand-pick the 50. Curate from the aligned-subset manifest, biased
toward premises with antecedent_conjunct_count ≥ 2 or consequent conjunctions.

## 2.2 Candidate generation via LLM + Vampire verification

For each curated premise, generate 4 candidate types:

- **C_gold** — FOLIO gold (the positive control).
- **C_partial_consequent** (Type 1) — preserves antecedent and one consequent, drops the other.
- **C_overweak** (Type 4) — entailed by gold but doesn't entail gold (drops a constraint).
- **C_overstrong** (Type 3) — entails gold but is not entailed by gold (adds a constraint).

The LLM generates candidates; **Vampire labels them**. Trust only the Vampire label.

### LLM prompt

Use Claude Sonnet 4 or GPT-4o, temperature 0, with this prompt:

```
You are constructing test cases for a first-order-logic (FOL) translation metric.

Premise (natural language):
{nl}

Gold FOL translation:
{gold_fol}

Predicates available (from gold): {predicate_signatures}
Constants available (from gold): {constants}

Your task: produce 4 candidate FOL formulas, each using ONLY the predicates and
constants listed above. Each candidate must be syntactically valid FOL. Output
each candidate on its own line, prefixed with the label.

CANDIDATE_PARTIAL: A formula that captures part of what gold says but is missing
a key consequent or conjunct. Should still be a plausible (but incomplete)
translation of the natural-language premise.

CANDIDATE_OVERWEAK: A formula that is logically WEAKER than gold — gold entails
this formula, but this formula does not entail gold. Drop a restrictor or
universally quantify a too-broad set.

CANDIDATE_OVERSTRONG: A formula that is logically STRONGER than gold — this
formula entails gold, but gold does not entail this formula. Add a restrictor
or strengthen a quantifier.

CANDIDATE_GIBBERISH: A formula that is syntactically valid but unrelated to the
premise. Use the available predicates randomly.
```

### Vampire verification

For each LLM-generated candidate, classify against gold using
`siv.vampire_interface.check_entailment`:

- `gold ⊨ candidate`: yes/no
- `candidate ⊨ gold`: yes/no

The four-cell matrix maps to:

| `gold ⊨ candidate` | `candidate ⊨ gold` | Category |
|---|---|---|
| yes | yes | equivalent (drop, not what we want) |
| no | yes | overstrong |
| yes | no | overweak |
| no | no | incompatible (could be partial, could be gibberish) |

For the "incompatible" bucket, manually inspect: if the candidate captures partial
content of gold, label `partial`; otherwise label `gibberish`.

**Keep only candidates whose Vampire-derived category matches the LLM's claimed
category.** Discard mismatches. If yield drops below 30 candidates per type after
filtering, increase the LLM batch size and retry; report the keep rate in
`run_metadata.json`.

Output: `reports/experiments/exp2/verified_candidates.jsonl`. Schema:

```json
{
  "premise_id": "P0123",
  "candidate_type": "partial_consequent",
  "candidate_fol": "...",
  "llm_claimed_type": "CANDIDATE_PARTIAL",
  "vampire_category": "partial",
  "gold_entails_candidate": true,
  "candidate_entails_gold": false,
  "kept": true
}
```

## 2.3 Smoke test (pass before full scoring)

Pull 5 premises with all 4 candidate types verified. Score with all 7 metrics.
Manually inspect:

- SIV-soft on `C_gold` should be high (typically ≥ 0.9).
- SIV-soft on `C_partial_consequent` should be **strictly between** `C_gold` and
  `C_overweak` for at least 3 of 5 premises.
- MALLS-LE-aligned and Brunello-LT-aligned on `C_overstrong`, `C_overweak`,
  `C_partial_consequent` should all be 0 (they're all non-equivalent).

**Pass criterion**: SIV produces an intermediate score on ≥ 3 of 5 partial cases AND
equivalence-based metrics collapse to 0 on all non-gold candidates. Log to
`reports/experiments/exp2/smoke_test.json`.

**If it fails**: SIV's gradedness claim is not supported. Stop. Do not proceed.

## 2.4 Score all candidates with all metrics

Same metric set as Experiment 1. Same timeouts. Output:
`reports/experiments/exp2/scored_candidates.jsonl`.

## 2.5 Primary analysis

**Table 2.5a — Mean score per candidate type per metric**

For each metric M and candidate type T, compute mean(M(candidate)) across all
premises. The expected pattern:

- For SIV: gold > overstrong ≈ partial > overweak > gibberish.
- For MALLS-LE-aligned, Brunello-LT-aligned: gold = 1, all others = 0.
- For BLEU, BERTScore: depends on lexical similarity, which is high for partial,
  variable for over-strong/over-weak.

Output: `reports/experiments/exp2/mean_by_type.csv`.

**Table 2.5b — Spearman rank correlation with ground-truth ordering**

For each premise, define the ground-truth ranking:
`gold > overstrong ≈ partial > overweak > gibberish`. (Treat overstrong and partial
as a tie at rank 2.) For each metric, compute Spearman ρ between the metric's scores
on this premise's 4 candidates and the ground-truth ranking. Average ρ across
premises. Bootstrap CI.

This is the **headline number for Exp 2**. Binary metrics will get ρ ≈ 0.5 (they
distinguish gold from non-gold but cannot rank within non-gold). SIV should get
ρ ≈ 0.85+.

Output: `reports/experiments/exp2/rank_correlation.csv` and `.json`.

| Metric | Mean Spearman ρ | 95% CI | p (vs SIV-soft min-recall) |
|---|---|---|---|
| BLEU | … | … | … |
| BERTScore | … | … | … |
| MALLS-LE-aligned | ~0.5 | … | … |
| Brunello-LT-aligned | ~0.5 | … | … |
| SIV-soft | … | … | reference |

**Table 2.5c — Adjacent-pair discrimination AUC**

For each metric and each adjacent pair in the ground-truth ordering
(`gold` vs `overstrong`, `partial` vs `overweak`, `overweak` vs `gibberish`),
compute AUC. SIV should be > 0.5 on every pair. Equivalence-based metrics will be
near 0.5 on `partial vs overweak` and `overweak vs gibberish` because they collapse
both to 0.

Output: `reports/experiments/exp2/adjacent_pair_auc.csv`.

## 2.6 Acceptance

Experiment 2 succeeds if SIV-soft achieves mean Spearman ρ ≥ 0.7 with bootstrap
lower-CI ≥ 0.6 AND is statistically above MALLS-LE-aligned, Brunello-LT-aligned on
the rank correlation (paired permutation, p < 0.01). If ρ < 0.6, the gradedness
claim is unsupported.

---

# Experiment 3 — Reference Failure (the reference-free pillar)

**Claim**: When the reference (FOLIO gold) is itself wrong, every reference-based
metric inherits the wrongness. SIV does not, because SIV scores against the natural
language, not the reference. This is the only experiment that demonstrates
reference-free as a load-bearing advantage rather than a stated property.

## 3.1 Premise selection — broken-gold subset

Source: `reports/phase1_pillar1/failure_analysis.json`, the unprovable-by-design
gold subset (~200 premises). Hand-pick **30 premises** with these criteria:

- The NL is unambiguous (the human can write a correct FOL).
- The gold FOL is provably weaker than the NL (e.g., disjunction without
  commitment, missing world-knowledge restrictor, dropped consequent).
- The gold predicate vocabulary is reasonable (so SIV's extraction can plausibly
  align with gold's signature for the BLEU/BERTScore/MALLS-LE comparison).

Output: `reports/experiments/exp3/curated_premises.jsonl`.

```json
{
  "premise_id": "P0477",
  "nl": "TikTok provides a chat feature.",
  "gold_fol": "exists x.((ChatFeature(x) | VideoFeature(x)) & Provides(tiktok, x))",
  "gold_failure_mode": "disjunction without commitment",
  "selection_reason": "NL clearly says chat feature specifically; gold under-commits"
}
```

## 3.2 Hand-author corrected translations

For each of the 30 premises, the human author writes a corrected FOL using the same
predicate signature as gold (so reference-based metrics can be compared on
vocabulary-match terms). The corrected FOL must:

- Be a faithful translation of the NL (not just a fix to gold).
- Use only predicates and constants present in gold's signature, OR introduce new
  ones if the NL requires them. Document additions.
- Pass `is_valid_fol` and `parse_fol`.

Output: `reports/experiments/exp3/corrections.jsonl`.

```json
{
  "premise_id": "P0477",
  "c_gold_fol": "exists x.((ChatFeature(x) | VideoFeature(x)) & Provides(tiktok, x))",
  "c_correct_fol": "exists x.(ChatFeature(x) & Provides(tiktok, x))",
  "rationale": "NL specifies chat feature; gold's disjunction allows video feature instead"
}
```

This file is a **paper artifact** — it will be released with the paper as a
hand-corrected subset of FOLIO. Treat it as a public dataset; clean comments,
no stray notes.

## 3.3 Candidate scoring

For each premise, two candidates exist: `C_gold` (the broken FOLIO gold) and
`C_correct` (the hand-authored correction). Score each with all 7 metrics.

**Reference for reference-based metrics**: `C_gold`. This is what FOLIO supplies.

**Reference for SIV**: the NL premise (via the cached test suite).

Output: `reports/experiments/exp3/scored_candidates.jsonl`. Each row:

```json
{
  "premise_id": "P0477",
  "candidate_label": "C_gold",  // or "C_correct"
  "candidate_fol": "...",
  "scores": {
    "bleu_vs_gold": 1.0,
    "bertscore_vs_gold": 1.0,
    "malls_le_raw_vs_gold": 1.0,
    "malls_le_aligned_vs_gold": 1.0,
    "brunello_lt_raw_vs_gold": 1.0,
    "brunello_lt_aligned_vs_gold": 1.0,
    "siv_soft_recall": 0.4,
    "siv_soft_f1": 0.5
  }
}
```

By construction, the `C_gold` row will have all reference-based scores at 1.0
(it is the reference). SIV's score on `C_gold` is what the experiment measures —
expected to be low because gold doesn't satisfy the NL.

## 3.4 Smoke test

Pull 5 premises. Manually verify:

- For each premise, the human-authored `C_correct` is genuinely correct
  (read it out loud, check it against the NL).
- For each premise, the SIV test suite's positive probes correspond to atomic
  claims the NL makes that gold misses.

This is a **manual** smoke test — no automated criterion. The author signs off
with a comment in `reports/experiments/exp3/smoke_test.md`.

## 3.5 Primary analysis

**Table 3.5a — Inversion rate**

For each reference-based metric M, compute:

- **Inversion rate** = fraction of premises where M(C_gold, gold) > M(C_correct, gold).
  Expected to be near 100% by construction — `C_gold` is the reference, so it
  always scores 1.0 against itself, and `C_correct ≠ C_gold` so it scores < 1.0.

For SIV:

- **Correct-preference rate** = fraction of premises where SIV(C_correct, NL) >
  SIV(C_gold, NL). Expected high.

Output: `reports/experiments/exp3/inversion_rate.csv` and `.json`.

| Metric | Inversion rate (C_gold > C_correct) | Correct-preference rate |
|---|---|---|
| BLEU | … (expect ~100%) | (n/a — same as 1 − inversion) |
| BERTScore | … (expect ~100%) | … |
| MALLS-LE-aligned | … (expect ~100%) | … |
| Brunello-LT-aligned | … (expect ~100%) | … |
| SIV-soft | (n/a) | … (expect high) |

**Table 3.5b — Score on C_gold vs C_correct, mean and distribution**

For each metric, mean score on `C_gold` and mean score on `C_correct`, with
distribution. SIV's mean on `C_correct` should be substantially above its mean on
`C_gold`. All other metrics are inverted.

## 3.6 Honest disclosure for the paper

This experiment uses a **hand-curated** broken-gold subset. The selection is
adversarial by design — these are cases where gold is wrong. The paper must
report:

- The selection rate from the unprovable-by-design pool (30 of ~200 = 15%).
- That the experiment demonstrates a **specific failure mode** of reference-based
  metrics, not a uniform statement that SIV is always better than reference-based
  metrics on FOLIO.
- The complementary failure mode for SIV: when SIV's extractor is wrong, SIV
  inherits the extraction-error (reported in limitations).

These disclosures are **non-negotiable**. Paper acceptance depends on them.

## 3.7 Acceptance

Experiment 3 succeeds if inversion rate for reference-based metrics is ≥ 90% AND
SIV's correct-preference rate is ≥ 70%. The 90% bar is essentially structural;
the 70% bar is the real bar. If SIV's correct-preference rate is below 70%, the
reference-free claim does not hold up under adversarial reference and the paper
must scope the claim more narrowly.

---

# Experiment 4 — Per-Aspect Diagnostic (the diagnostic pillar)

**Claim**: SIV's per-probe verdicts encode information about *what kind* of error a
candidate has, not just whether it is wrong. Binary metrics produce a single
0/1 — they cannot distinguish "argument-swapped" from "missing-restrictor" from
"over-weak." SIV can.

## 4.1 Data sources

Reuse the scored candidates from Experiments 1 and 2:

- From Exp 1: candidates with `applicable=true`, scored with SIV.
  Each row has a known operator type (`B_arg_swap`, etc.).
- From Exp 2: verified candidates labeled by Vampire-category
  (`partial`, `overweak`, `overstrong`).

For each scored candidate, we have access to the SIV scoring's
`per_test_results` field (in `ScoreReport`), which is a list of
`(kind, fol, verdict)` tuples where `kind ∈ {positive, contrastive}` and `verdict
∈ {entailed, not_entailed, timeout, unknown, no_contrastives}`.

## 4.2 Failed-probe pattern extraction

For each scored candidate that SIV correctly catches (SIV-soft(gold) >
SIV-soft(candidate)), extract the **failure pattern**:

```python
def failure_pattern(score_report) -> dict:
    return {
        "n_positive_failed": count(t for t in per_test_results
                                    if t.kind == "positive"
                                    and t.verdict != "entailed"),
        "n_positive_total": count(t for t in per_test_results if t.kind == "positive"),
        "n_contrastive_failed": count(t for t in per_test_results
                                       if t.kind == "contrastive"
                                       and t.verdict == "entailed"),
        "n_contrastive_total": count(t for t in per_test_results
                                      if t.kind == "contrastive"),
        "pattern_signature": one of {
            "all_positive_pass_some_contrastive_fail",  # Type 3 / overstrong-ish
            "some_positive_fail_all_contrastive_pass",  # Type 4 / overweak
            "some_positive_fail_some_contrastive_fail", # mixed
            "all_positive_fail",                        # mostly Tier-D / gibberish
            "all_pass",                                 # SIV missed
        }
    }
```

The exact pattern names can be adjusted based on what the data shows. Run this
extraction on all scored candidates from Exp 1 and Exp 2; output to
`reports/experiments/exp4/patterns.jsonl`.

## 4.3 Confusion matrix

Build a confusion matrix:

- **Rows**: actual error type. Categories from Exp 1: `B_arg_swap`,
  `B_negation_drop`, `B_scope_flip`, `B_restrictor_drop`, `D_random`. Categories
  from Exp 2: `partial`, `overweak`, `overstrong`.
- **Columns**: SIV's failure pattern signature.

Each cell: count of candidates that fell into that (row, column).

Output: `reports/experiments/exp4/confusion_matrix.csv` and a heatmap PNG.

The expected pattern:

- `B_negation_drop` and `partial` and `overweak` rows concentrate in
  `some_positive_fail_all_contrastive_pass`.
- `B_arg_swap` row may concentrate in
  `all_positive_pass_some_contrastive_fail` or `some_positive_fail_some_contrastive_fail`
  depending on whether the swap creates a probe-violating asymmetry.
- `D_random` concentrates in `all_positive_fail`.
- `overstrong` concentrates in `all_positive_pass_some_contrastive_fail`.

If the confusion matrix is highly diagonal (each error type has a distinct
pattern signature), SIV's diagnostic claim is supported. If it's diffuse,
**drop the per-aspect diagnostic claim from the paper.** Honesty is more
defensible than overreach.

## 4.4 Qualitative case studies

Pick 5-10 candidates from the matrix's diagonal cells. For each, produce a
case-study row:

- The NL premise.
- Gold FOL.
- Candidate FOL.
- Error type (operator or category).
- SIV's per-probe verdict trace, formatted for human reading.
- Comparison: what BLEU, BERTScore, MALLS-LE-aligned reported (a single number
  each, no traceable failure pattern).

Output: `reports/experiments/exp4/case_studies.md`. This becomes a paper figure /
table directly.

## 4.5 Acceptance

Experiment 4 succeeds if the confusion matrix has at least 3 diagonal cells with
≥ 60% concentration (i.e., for at least 3 error types, the dominant pattern
signature accounts for the majority of candidates). If fewer than 3 diagonal
cells, the diagnostic claim is too weak to feature; report the matrix in the
appendix and frame the qualitative case studies as the contribution instead.

---

# Required ablations (appendix-grade, run after primary experiments)

These are appendix-grade. Run them after the four primary experiments. Reviewers
will demand each of them.

## A1 — Threshold sensitivity

Run SIV-soft on Experiment 1's candidates at thresholds {0.4, 0.5, 0.6, 0.7, 0.8}.
Plot per-operator detection rate as function of threshold.

Output: `reports/experiments/ablations/threshold_sensitivity.csv` and `.png`.

## A2 — Embedding model

Repeat Experiment 1's SIV-soft scoring with `all-mpnet-base-v2` instead of
`all-MiniLM-L6-v2`. Confirm per-operator detection rates are within ±5 percentage
points.

Output: `reports/experiments/ablations/embedding_model.csv`.

## A3 — Type 2 sensitivity (the limitations stress test)

Construct ~30 cases where a candidate is logically equivalent to gold but uses
different vocabulary. Method: take Exp 1's aligned subset; for each premise, ask
the LLM to generate "an equivalent FOL using slightly different predicate names
or argument orderings" (no logical change). Verify equivalence via Vampire. Score
all candidates with all metrics.

Expected: MALLS-LE-aligned and Brunello-LT-aligned score 1.0 (they're equivalent).
SIV-soft scores variably depending on alignment success.

Output: `reports/experiments/ablations/type2_sensitivity.csv`. Headline number
for the limitations section: "SIV-soft mean recall on logically-equivalent
candidates is X%; reference-based metrics correctly score these at 1.0."

This is **for limitations**, not a primary result. Reporting honestly here is
required.

## A4 — Gameability check (CORE-style)

Construct adversarial candidates of the form `gold ∧ Trivial(x) ∧ Exists(y)` —
gold conjuncted with tautologies. Score with SIV. SIV's score must not inflate
above SIV(gold) alone.

Output: `reports/experiments/ablations/gameability.csv`. If SIV's score
inflates, surface immediately — this is a paper-blocker.

---

# Pillar 1 (Phase 1 ceiling) — already done, just write up

Phase 1's gold-ceiling finding is already collected. The artifacts live in
`reports/phase1_pillar1/`. The paper's Section 4 cites these directly. Tables to
include:

- Gold ceiling breakdown (149 syntax errors / ~200 unprovable / 6 UNA / 15
  wrong labels).
- Verdict distribution per translator (the neutral-by-default skew).
- Metric AUC clustering (0.55-0.58, all metrics indistinguishable).

No new experiments required for Pillar 1. The writeup work consists of producing
the markdown section in `reports/phase1_pillar1/section_writeup.md` from the
existing data.

---

# Capabilities table (paper figure)

Hand-construct the comparison table from the paper outline:

| Method | Reference-free | Label-free | Graded | Per-aspect diagnostic |
|---|---|---|---|---|
| BLEU | No | Yes | Yes | No |
| BERTScore | No | Yes | Yes | No |
| MALLS-LE | No | Yes | No (binary) | No |
| Brunello-LT | No | Yes | No (binary) | No |
| EPR | Yes | **No** | Yes | No |
| **SIV** | **Yes** | **Yes** | **Yes** | **Yes** |

This table is the conceptual contribution. SIV is the only row with all four
checks. Each experiment in the paper validates one column.

Output: `reports/experiments/capabilities_table.csv` (machine readable for the
paper's LaTeX).

---

# Execution order

1. **Pre-work A, B, C, D**: bug fixes, common utilities. ~3 days.
2. **Pillar 1 writeup**: tables A, B, C from existing data. ~1 day. Can run in
   parallel with everything else.
3. **Experiment 1**: aligned-subset filter, candidate generation, smoke test, full
   scoring, primary analysis. ~3 days.
4. **Experiment 2**: curated-premise selection, LLM generation + Vampire
   verification, smoke test, scoring, analysis. ~4 days.
5. **Experiment 3**: hand-author corrections, scoring, analysis. ~5 days
   (hand-authoring dominates).
6. **Experiment 4**: pattern extraction from Exp 1+2 outputs, confusion matrix,
   case studies. ~1 day.
7. **Ablations A1-A4**: ~2 days.
8. **Capabilities table + cross-experiment writeup**: ~1 day.

**Total: roughly 2.5 weeks of execution.** Plus 1 week of paper writing on top.

---

# Hard rules (do not violate)

- **Never modify SIV strict mode** (CI-enforced soundness; C9a/C9b on the
  invariant corpus must always pass).
- **Never regenerate cached extractions.** The cache covers 98.9% of FOLIO train
  at considerable LLM cost. Use the cache.
- **Never lower SIV-soft alignment threshold below 0.6** without running the
  Ablation A1 sensitivity sweep first.
- **Never report SIV scores from premises that fail the post-fix free-variable
  validator.** They are dropped from the corpus and excluded from all aggregate
  numbers.
- **Never report a metric average that includes `None` values.** `None`
  (parse error / timeout) is reported separately as a coverage statistic.
- **Smoke tests are blocking.** If an experiment's smoke test fails, surface the
  failure with the data that produced it. Do not proceed to full scoring on a
  hunch.
- **No experiment depends on FOLIO entailment-via-Vampire as ground truth.** That
  was Phase 1, and Phase 1 showed it doesn't work. Don't relitigate.
- **Hand-authored artifacts (Exp 3 corrections, Exp 4 case studies) are paper
  outputs.** Format them carefully — they will be in the published paper.

---

# Output directory layout

```
reports/
├── phase1_pillar1/                   ← from cleanup, paper inputs
│   ├── correlation_results.{csv,json}
│   ├── entailment_results_test.jsonl
│   ├── failure_analysis.json
│   ├── metric_scores_test.jsonl
│   └── section_writeup.md            ← NEW (Pillar 1 paper section draft)
├── diagnostic/                       ← from cleanup
├── test_suites/                      ← from cleanup; cache lives here
│   ├── test_suites_train.jsonl
│   └── test_suites_train.failures.jsonl   ← NEW (post-fix dropped premises)
└── experiments/                      ← NEW
    ├── capabilities_table.csv
    ├── exp1/
    │   ├── aligned_subset_manifest.jsonl
    │   ├── candidates.jsonl
    │   ├── smoke_test.json
    │   ├── scored_candidates.jsonl
    │   ├── per_tier_auc.{csv,json}
    │   ├── per_operator.{csv,json}
    │   ├── score_gap_distributions.png
    │   └── run_metadata.json
    ├── exp2/
    │   ├── curated_premises.jsonl
    │   ├── verified_candidates.jsonl
    │   ├── smoke_test.json
    │   ├── scored_candidates.jsonl
    │   ├── mean_by_type.csv
    │   ├── rank_correlation.{csv,json}
    │   ├── adjacent_pair_auc.csv
    │   └── run_metadata.json
    ├── exp3/
    │   ├── curated_premises.jsonl
    │   ├── corrections.jsonl
    │   ├── smoke_test.md
    │   ├── scored_candidates.jsonl
    │   ├── inversion_rate.{csv,json}
    │   └── run_metadata.json
    ├── exp4/
    │   ├── patterns.jsonl
    │   ├── confusion_matrix.{csv,png}
    │   ├── case_studies.md
    │   └── run_metadata.json
    └── ablations/
        ├── threshold_sensitivity.{csv,png}
        ├── embedding_model.csv
        ├── type2_sensitivity.csv
        └── gameability.csv
```

Every numerical artifact has a JSON or CSV form. Every figure has a PNG. Every
experiment has a `run_metadata.json` with seed, model versions, total wall time,
total Vampire-call cost, and the git commit at run time.
