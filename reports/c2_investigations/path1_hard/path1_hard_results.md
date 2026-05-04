# Path 1-Hard Results: Per-aspect Feedback at Higher Task Difficulty

## Section 1: Locked Design Summary

### Hypothesis
At task difficulty where LLMs cannot zero-shot the NL→FOL translation (baseline ≤30%), the LLM must use diagnostic feedback. Under that condition, structured per-aspect category labels should outperform shuffled category labels.

### Candidate Source
- Multi-quantifier FOLIO premises (≥2 quantifiers in gold FOL)
- Compound-3 perturbation (3 layers of distinct error patterns)
- 60 verified candidates (parseable, non-equivalent, SIV-detectable)
- Pool no-feedback baseline: 26.7% (in 10-30% target band)

### Difficulty Calibration (Step 1)
| Level | Source | Baseline | Band |
|-------|--------|----------|------|
| A (chosen) | Multi-quantifier FOLIO + compound-3 | 20% | ✓ IN BAND |
| B | Hand-constructed + compound-2 | 70% | Too easy |
| C | Adversarial perturbations | 30% | Borderline |

### Category Vocabulary (from Path 1 Step 0)
Same 6 categories: argument-order, quantifier-scope, restrictor-content, polarity, connective-polarity, content-gap.

### Conditions (5, identical to Path 1)
1. No-feedback
2. Score-only
3. Structured category (treatment)
4. Shuffled category (control)
5. Count-only

### Models
GPT-4o, GPT-4o-mini, Claude Sonnet (claude-sonnet-4-6). Temperature 0.

---

## Section 2: Per-model Headline Numbers

### Main Run: 60 candidates × 5 conditions × 3 models (900 LLM calls)

| Model | No-FB | Score | Structured | Shuffled | Count | **Δ(S-H)** | 95% CI | p |
|-------|-------|-------|-----------|----------|-------|-------------|--------|---|
| GPT-4o | 35.0% | 30.0% | 31.7% | 31.7% | 26.7% | **0.000** | [-0.10, +0.10] | 0.566 |
| GPT-4o-mini | 21.7% | 26.7% | 25.0% | 23.3% | 21.7% | **+0.017** | [-0.05, +0.08] | 0.414 |
| Claude Sonnet | 36.7% | 26.7% | 30.0% | 35.0% | 33.3% | **-0.050** | [-0.13, +0.03] | 0.913 |

### Primary Comparison: Structured vs. Shuffled
- **0/3 models** show Δ ≥ 0.10 with p < 0.05
- GPT-4o: exactly tied (Δ=0.000)
- GPT-4o-mini: trivial difference (+1.7pp, p=0.41)
- Claude Sonnet: shuffled actually outperforms structured (-5pp, p=0.91)

---

## Section 3: Secondary Comparisons

### Structured vs. Score-only
- GPT-4o: +1.7pp (structured slightly better)
- GPT-4o-mini: -1.7pp (score-only slightly better)
- Claude Sonnet: +3.3pp (structured slightly better)

None significant. Category labels provide no added value beyond the score alone.

### Structured vs. Count-only
- GPT-4o: +5.0pp
- GPT-4o-mini: +3.3pp
- Claude Sonnet: -3.3pp

None significant. Knowing which categories failed does not help more than knowing how many failed.

---

## Section 4: Per-category and Per-baseline-difficulty Analysis

### Category Distribution
| Category | N candidates | Structured rate | Shuffled rate |
|----------|-------------|----------------|---------------|
| content-gap | 60 (100%) | ~30% | ~32% |
| polarity | 47 (78%) | ~30% | ~31% |
| restrictor-content | 1 (1.7%) | — | — |
| connective-polarity | 2 (3.3%) | — | — |
| argument-order | 1 (1.7%) | — | — |
| quantifier-scope | 1 (1.7%) | — | — |

The pool is dominated by polarity + content-gap (same structural skew as Path 1). Low-frequency categories have insufficient power for per-category analysis.

### Per-baseline-difficulty Split
- Candidates where no-feedback **failed** (73%): this is the regime where feedback should help most
- Candidates where no-feedback **succeeded** (27%): feedback is redundant here

Even within the "failed without feedback" subset, structured and shuffled perform identically. The LLM does not use category information to recover from failure.

---

## Section 5: Path 1 vs. Path 1-Hard Comparison

| Metric | Path 1 (easy) | Path 1-Hard (hard) |
|--------|--------------|-------------------|
| No-feedback baseline | 60-65% | 22-37% |
| Structured rate | 60% | 25-32% |
| Shuffled rate | 60% | 23-35% |
| **Δ (structured - shuffled)** | **0.000** | **-0.01 to +0.02** |
| Signal? | No | No |

**The difficulty-dependence hypothesis is refuted.** Category-level per-aspect feedback does not become actionable at higher difficulty. The null holds across the full difficulty range tested (22-65% baseline).

---

## Section 6: Example Corrections

### From Pilot (Cases 6 & 7 that showed structured-shuffled differences at n=20)

These pilot differences did not replicate at full scale. The pilot's Δ=+0.10 was sampling noise from n=20.

### Main Run Pattern

In the majority of cases, GPT-4o produces the same correction regardless of which categories are shown. The model translates from NL and uses the perturbed FOL as a structural template, ignoring the category labels entirely.

Typical case:
```
NL: "All lead singers are singers."
Gold: ∀x ∀y (LeadSinger(x, y) → Singer(y))
Perturbed: ∀x ∀y (-LeadSinger(x, y) → Singer(y))

Structured feedback: [polarity, content-gap]
  → Correction: ∀x (LeadSinger(x) → Singer(x))  [WRONG: lost binary predicate]

Shuffled feedback: [argument-order, quantifier-scope]
  → Correction: ∀x (LeadSinger(x) → Singer(x))  [SAME WRONG answer]
```

The model makes the same errors regardless of feedback quality because it's retranslating from its own understanding of the NL, not debugging the perturbed FOL using the categories.

---

## Section 7: Decision Branch Outcome

**Pre-registered branch: NULL**

> "Structured ≈ shuffled (Δ < 0.05) across all models: per-aspect at category level fails at harder difficulty too. The claim is rejected across the difficulty range tested."

The per-aspect-actionability claim is rejected at:
- Probe-formula level (Investigation 4: leakage)
- Category level, easy difficulty (Path 1: Δ=0.000)
- Category level, hard difficulty (Path 1-Hard: Δ=-0.01 to +0.02)

---

## Section 8: Unexpected Findings and Follow-up

### Unexpected: Score-only and count-only don't help either

At the harder difficulty level, **no feedback condition improves over no-feedback**:
- GPT-4o: no-feedback (35%) ≥ all feedback conditions (27-32%)
- Claude Sonnet: no-feedback (37%) ≥ all feedback conditions (27-33%)

This suggests that for multi-quantifier FOLIO premises, feedback information (score, categories, counts) may actually be slightly harmful — potentially by anchoring the LLM on the perturbed FOL rather than translating fresh from NL.

### Unexpected: Pilot Δ did not replicate

The pilot (n=20) showed Δ=+0.10 for GPT-4o, which was exactly at the acceptance threshold. The main run (n=60) showed Δ=0.000. This demonstrates why the pre-registered n=60 design was necessary — n=20 produces unreliable point estimates for this effect size.

### The fundamental finding

Current frontier LLMs (GPT-4o, Claude Sonnet) approach NL→FOL translation as a **generation** task, not a **debugging** task. When given NL + broken FOL + diagnostic feedback:
1. They don't debug the broken FOL using the diagnostics
2. They retranslate from NL (when they can)
3. When they can't retranslate correctly (hard cases), diagnostics don't help because the model lacks the underlying logical capability, not diagnostic information

This means SIV's value proposition is for **human** evaluation (where diagnostics help a human reviewer understand what's wrong) rather than **LLM** self-correction (where the LLM ignores or can't use the diagnostics).

---

## Files Produced

| File | Content |
|------|---------|
| `step0_source_check.md` | Pipeline validation on OOD FOL |
| `step1_difficulty_calibration.json/md` | Three difficulty levels tested |
| `step2_candidate_pool.md` | 60-candidate pool metadata |
| `step3_locked_design.md` | Pre-registered design |
| `step4_pilot.json/md` | 20-candidate pilot (Δ=+0.10, not replicated) |
| `step5_main_results.json` | Full results with per-candidate outcomes |
| `path1_hard_candidates.json` | Locked candidate set |
| `path1_hard_results.md` | This file |

---

## Paper Framing

> We tested whether per-aspect diagnostic feedback becomes actionable at task difficulties where LLMs cannot zero-shot the translation. At a no-feedback baseline of 27% (vs. 60% in Path 1), we found no evidence that structured category labels outperform shuffled labels (Δ ranging from -0.05 to +0.02 across three models, all p > 0.4). Combined with Path 1's null at easier difficulty and Investigation 4's leakage finding at probe-formula granularity, we conclude that SIV's per-aspect diagnostics do not enable LLM self-correction at any tested difficulty level or feedback granularity. SIV's demonstrated value is as an evaluation metric (Exp A/B: ρ=0.85 correlation with error severity) and defect detector (Exp D), not as a correction signal for current LLMs.
