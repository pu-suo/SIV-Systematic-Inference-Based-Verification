# Step 2: Locked Experimental Design

*This document is pre-registered before any main-run scoring. Do not modify after seeing data.*

## Conditions (5)

1. **No-feedback baseline**: NL + broken FOL + "produce corrected FOL." Anchors floor.
2. **Score-only**: Adds SIV recall score (0-1 scale).
3. **Structured category** (treatment): Score + actual error category labels from SIV probes.
4. **Shuffled category** (control): Score + WRONG category labels (same count, drawn from non-actual categories).
5. **Count-only**: Score + number of error categories detected (no labels).

### Key Design Properties

- All conditions use **identical prompt scaffolding** except the feedback block.
- **No probe formulas appear** in any condition. Category labels only.
- Category definitions are provided in conditions 3 and 4 so the LLM knows what each category means.
- Shuffled condition shows the **same number** of categories as structured, but **all wrong**.

## Category Vocabulary (locked from Step 0)

- argument-order
- quantifier-scope
- restrictor-content
- polarity
- connective-polarity
- content-gap

## Shuffling Protocol

For each candidate with actual categories A:
1. Remove ALL categories in A from the vocabulary
2. Sample |A| categories uniformly without replacement from the remaining vocabulary
3. Present these as the "detected" categories

This is a **strong** control: every category shown is definitively wrong. If structured still beats shuffled, the signal is in the *correctness* of the category labels, not their mere presence.

## Models

| Model | Provider | ID | Temperature |
|-------|----------|-----|-------------|
| GPT-4o | OpenAI | gpt-4o | 0 |
| GPT-4o-mini | OpenAI | gpt-4o-mini | 0 |
| Claude Sonnet | Anthropic | claude-sonnet-4-6 | 0 |

## Seeds

3 seeds per cell: [42, 137, 256]. Seed varies candidate ordering only (temperature = 0).

## Outcome Metrics

1. **Primary**: SIV equivalence = recall of 1.0 on gold-derived test suite (binary: equivalent or not)
2. **Secondary 1**: Vampire bidirectional entailment equivalence to gold FOL
3. **Secondary 2**: FOLIO entailment-label match in full premise context

## Statistical Test

- **Method**: Paired bootstrap on candidate-level binary success (equivalent or not)
- **Resamples**: 10,000
- **Primary comparison**: Structured (cond 3) vs. Shuffled (cond 4)
  - Acceptance: Δ ≥ 0.10 absolute, p < 0.05
- **Secondary comparisons** (Holm-corrected):
  - Structured (3) vs. Score-only (2)
  - Structured (3) vs. Count-only (5)

## Pre-registered Decision Branches

| Outcome | Interpretation | Action |
|---------|---------------|--------|
| Structured > Shuffled, Δ ≥ 0.10, p < 0.05, ≥2 models | Per-aspect claim supported | Headline = Path 1 succeeds |
| Structured > Shuffled, Δ ≥ 0.10, 1 model only | Model-dependent signal | Honest report, weaker claim |
| Structured ≈ Shuffled, Δ < 0.05, all models | Category-level also fails | Path 1 null; pivot to Path 2 |
| Structured > Shuffled, 0.05 ≤ Δ < 0.10 | Ambiguous | Report as suggestive |

## Dishonest Moves (pre-registered exclusions)

The following are NOT permitted after seeing data:
- Filtering candidates post-hoc
- Modifying category vocabulary
- Adjusting shuffled-trace permutation rule
- Changing the acceptance threshold
- Adding "exploratory" comparisons that were not pre-specified

## Sample Size

- n = 80 candidates per cell
- Total LLM calls: 80 × 5 conditions × 3 models × 3 seeds = 3,600
- Power: at Δ = 0.10 with baseline ~40% success, bootstrap power ≈ 0.80 at n=80

## Candidate Pool

- Source: FOLIO train, entailment + contradiction labels only
- Perturbation: compound-3 (3 layers of distinct error patterns)
- Verification: Vampire well-formed, non-equivalent, label-changing, SIV-detectable
- Baseline correction rate: 60% (borderline; documented as "slightly easy")
- Category distribution dominated by polarity (94%) and content-gap (100%)
  - This is structural: most FOLIO formulas trigger polarity probes
  - Implication: the test is primarily "does knowing it's a polarity+content error help vs. being told it's argument-order+quantifier error?"

## Notes on Baseline Rate

The 60% baseline (no-feedback) is at the boundary of "slightly easy" and "too easy." Compound-3 perturbations did not reduce it below compound-2 (60% vs. 62.5%). This suggests the perturbation difficulty has saturated — GPT-4o is reconstructing from NL alone regardless of corruption complexity.

This means: the expected effect size for ANY feedback condition is compressed. If no-feedback already achieves 60%, the ceiling for structured is ≤100%, giving maximum possible Δ of 0.40. Realistic Δ is much smaller. The experiment can still detect a per-aspect signal if it exists, but power is reduced.
