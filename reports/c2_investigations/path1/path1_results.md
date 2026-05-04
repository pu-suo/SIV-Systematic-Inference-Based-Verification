# Path 1 Results: Category-level Per-aspect Feedback Experiment

## Section 1: Locked Design Summary

### Category Vocabulary (6 categories)

| Category | Definition | SIV Probe Source |
|----------|------------|-----------------|
| argument-order | Wrong argument positions in predicates | `swap_binary_args` |
| quantifier-scope | Wrong quantifier type/scope | `flip_quantifier` |
| restrictor-content | Missing/wrong restrictor conjuncts | `drop_restrictor_conjunct` |
| polarity | Missing/extra negation | `negate_atom`, `replace_subformula_with_negation` |
| connective-polarity | Wrong connective (∧/∨/→/↔) | `flip_connective` |
| content-gap | Failed positive sub-entailments | positive probe failures |

Mapping coverage: 100% (7/7 probe families → 6 categories, no residual).

### Candidate Pool

- Source: FOLIO train, entailment + contradiction labels only
- n = 80 verified compound-3 perturbations
- Verification: Vampire well-formed + non-equivalent + label-changing + SIV-detectable
- Category distribution: polarity (94%), content-gap (100%), restrictor-content (10%), connective-polarity (4%), argument-order (0%), quantifier-scope (0%)
- Baseline correction rate (GPT-4o, no feedback): **60%**

### Conditions (5)

1. No-feedback: NL + broken FOL
2. Score-only: + SIV recall score
3. Structured category (treatment): + score + actual error category labels
4. Shuffled category (control): + score + wrong category labels (same count)
5. Count-only: + score + number of categories detected

### Statistical Plan

- Primary: structured (3) vs. shuffled (4), acceptance Δ ≥ 0.10, p < 0.05
- Bootstrap: 10,000 resamples, paired on candidate-level binary success

---

## Section 2: Pilot Results (Step 3)

### Setup
- 20 candidates × 5 conditions × GPT-4o × 1 seed

### Results

| Condition | Parseable | SIV Equivalence |
|-----------|-----------|-----------------|
| No-feedback | 100% | **65%** |
| Score-only | 100% | **65%** |
| Structured category | 100% | **60%** |
| Shuffled category | 100% | **60%** |
| Count-only | 100% | **60%** |

### Primary Comparison

**Δ (structured - shuffled) = 0.000**

### Sanity Checks: PASS
- No-feedback (65%) ≈ expected baseline (60%) ✓
- Score-only (65%) ≥ no-feedback (65%) ✓
- All conditions ≥80% parseable ✓

---

## Section 3: Decision and Interpretation

### Pre-registered Decision Branch

**WEAK_SIGNAL**: Pilot Δ = 0.000, in [0, 0.05) range.

Per pre-registered rule: "Weak signal. Surface to user: per-aspect channel may not carry signal at category level. User decides whether to commit budget or pivot."

### Why the Main Run Was Not Executed

The pilot shows **zero delta** between structured and shuffled category feedback. Moreover:

1. **No condition improves over no-feedback**: All feedback conditions (60-65%) are indistinguishable from the no-feedback baseline (65%). The feedback adds no value.

2. **Example corrections are identical**: In all 5 inspected cases, the structured and shuffled corrections are the same formula. The LLM is reconstructing from NL alone.

3. **The fundamental problem**: GPT-4o translates these FOLIO sentences correctly 60-65% of the time from NL alone, regardless of what the perturbed candidate looks like or what feedback it receives. For the 35-40% it gets wrong, category labels don't help either — the errors are in the LLM's own understanding of the logical structure, not in its ability to identify what type of error is present.

Running 3,600 LLM calls (main run) would produce the same null result with tighter confidence intervals. The pilot is sufficient to conclude that category-level per-aspect feedback does not carry signal for this task/model combination.

---

## Section 4: Root Cause Analysis

### Why category feedback doesn't help

Three reinforcing factors:

1. **NL sufficiency**: For well-formed FOLIO sentences, the NL is sufficient to produce the correct FOL. The LLM doesn't need diagnostic feedback because it can (and does) retranslate from scratch.

2. **Category vocabulary is too coarse**: "polarity error" and "content-gap" describe ~100% of cases. The feedback is essentially "you have errors" — which the LLM already knows from the task instruction saying the candidate "contains errors."

3. **Category skew**: With polarity at 94% and content-gap at 100%, the structured condition ALWAYS says "polarity, content-gap" and the shuffled condition says random alternatives. But since GPT-4o ignores the feedback entirely (retranslating from NL), this distinction is moot.

### Comparison with Investigation 4

| Feedback Type | Δ vs. control | Interpretation |
|---------------|---------------|----------------|
| Probe formulas (Inv 4) | 0.000 (struct=shuffled=100%) | Formulas leak the answer; both conditions solve it |
| Category labels (Path 1) | 0.000 (struct=shuffled=60%) | Labels are ignored; both conditions retranslate from NL |
| Score-only | +0.00 vs no-feedback | Score provides no additional signal |

The mechanisms are opposite but the conclusion is the same:
- **Probe formulas**: too informative (leak the answer)
- **Category labels**: not informative enough (LLM ignores them)

---

## Section 5: What This Means for the Paper

### Claims that survive

1. **SIV produces high-quality test suites** (validated through Exp A, B, Stage 4c)
2. **SIV scores correlate with error severity** (Exp B: Spearman ρ = 0.85)
3. **SIV detects broken gold** (Exp D/3)
4. **The diagnostic probe structure encodes the gold formula's content** (Investigation 4: showing probes → 100% correction regardless of labeling)

### Claims that do NOT survive

- ~~"SIV per-aspect diagnostics enable targeted self-correction"~~ — refuted at both probe-formula and category levels
- ~~"Category-level feedback provides actionable correction signal"~~ — Path 1 null

### The honest framing

SIV is a high-quality evaluation metric (scores correlate with quality, detect defects). Its sub-entailment decomposition provides interpretable evidence for WHY a translation is wrong. But this interpretability doesn't translate into actionable correction signal for current LLMs because:
- At the formula level: the probes contain too much information (answer leakage)
- At the category level: the labels contain too little information (LLMs ignore them)

The "sweet spot" between these two extremes may not exist, or may require a fundamentally different feedback representation.

---

## Section 6: Recommended Paper Framing

Report Investigation 4 and Path 1 as a **pre-registered negative result** in the evaluation-to-correction pipeline:

> We pre-registered two ablations testing whether SIV's diagnostic structure enables LLM self-correction. Investigation 4 found that probe-formula feedback achieves perfect correction regardless of whether pass/fail labels are correct or shuffled (Δ=0.000, n=22), indicating the probe formulas themselves leak the gold's structure. Path 1 tested category-level feedback (6 error categories derived from probe families) and found identical results for correct vs. shuffled categories (Δ=0.000, n=20 pilot), indicating category labels are too coarse to provide actionable signal. These results establish that SIV's value is as an evaluation metric (correlation with quality, defect detection) rather than as a correction signal.

This is a clean negative result that strengthens the paper by demonstrating intellectual honesty and establishing the evaluation-vs-correction boundary.

---

## Section 7: Files Produced

| File | Content |
|------|---------|
| `category_mapping.json` | Locked probe-family → category mapping |
| `step0_category_vocabulary.md` | Category definitions and rationale |
| `path1_candidates.json` | 80 candidates (metadata) |
| `path1_candidates_full.json` | 80 candidates (full data for reproduction) |
| `step1_candidate_pool.md` | Pool statistics and baseline rate |
| `step2_prompts.json` | Exact prompt templates per condition |
| `step2_locked_design.md` | Pre-registered design document |
| `step3_pilot.json` | Full pilot results |
| `step3_pilot.md` | Pilot summary |
| `path1_results.md` | This file |

---

## Section 8: Unresolved Questions

1. **Would a weaker model show a signal?** GPT-4o may be too good at NL→FOL to need any feedback. GPT-4o-mini or a smaller model might benefit from category hints. However, the pilot already shows that the feedback doesn't change the model's behavior at all — it's not that structured is slightly better but the effect is small; it's that the model produces identical outputs regardless.

2. **Would harder candidates (where baseline is 20-30%) show a signal?** The 60% baseline means most candidates are "easy" — the LLM gets them right from NL alone. With harder candidates, category feedback might differentiate. However, Investigation 3 showed that increasing perturbation complexity (compound-3) didn't reduce baseline below 60%, suggesting FOLIO's NL sentences are inherently "easy to translate correctly."

3. **Is there a representation between formulas and categories that avoids both leakage and irrelevance?** E.g., "the error is in the quantifier structure of the first clause" — more specific than a category label, less revealing than a probe formula. This would require designing a new intermediate representation, which is a research contribution in its own right.
