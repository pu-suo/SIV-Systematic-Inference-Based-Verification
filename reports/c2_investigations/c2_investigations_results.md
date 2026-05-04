# C2 Design Investigations: Summary and Locked Design

## Investigation 1: Load-bearing Sentence Rate

**Question**: What fraction of FOLIO premise sentences are load-bearing?

**Results**:
- 50 stories sampled (18 entailment, 17 contradiction, 15 neutral)
- **70% of premises have ≥1 load-bearing sentence** (mean: 2.56 per premise)
- Per-label:
  - Entailment: 100% have LB (mean 3.17)
  - Contradiction: 100% have LB (mean 4.18)
  - Neutral: 0% have LB (mean 0.00)
- Vacuous-replacement flips match removal flips exactly (128 = 128)

**Decision**: **FEASIBLE_AT_SCALE** — Bridge 2 (natural FOLIO sampling) works for entailment/contradiction labels. Neutral premises have no load-bearing sentences by construction (removing a sentence from "insufficient evidence" doesn't create sufficient evidence).

**Implication**: Restrict candidate pool to entailment + contradiction examples only.

---

## Investigation 2: Outcome-metric Sensitivity

**Question**: Does entailment-label respond gradedly to correction quality?

**Results** (n=15 cases, all with verified gold sanity):
- Gold produces correct label: 15/15 (100%) ✓
- Corrupted produces wrong label: 14/15 (93.3%) ✓
- **Partial repair produces correct label: 2/15 (13.3%)**
- Full repair produces correct label: 12/15 (80.0%)
- SIV scores: gold=1.0, corrupted=0.07, partial=0.07, full=0.82
- SIV-label agreement: 93.3%

**Decision**: **BINARY_COLLAPSE** — The entailment label is extremely sensitive; even small errors flip it. It cannot distinguish "good correction" from "perfect correction." 

**Primary outcome locked**: SIV score (recall against gold-derived suite).  
**Secondary outcome**: Entailment-label match (binary signal only).

---

## Investigation 3: Hand-perturbation Feasibility

**Question**: Can we construct reliable perturbations for candidates?

**Results**:
- 20 perturbations constructed across 8 error patterns
- **Verification pass rate: 75% (15/20)**
  - 0 parse failures, 1 equivalent-to-gold, 4 label-unchanged
- **Baseline GPT-4o correction rate: 86.7% (13/15)** 

**Decision**: 
- Construction: **NEEDS_REVIEW** — 75% pass rate means verification step is mandatory
- Severity: **TOO_EASY** — Single-pattern perturbations are trivially correctable by GPT-4o

**Implication**: Must use compound perturbations (2+ errors per candidate) for main experiment.

---

## Investigation 4: Effect-size Estimate

**Question**: What is the effect of structured trace vs. shuffled trace at locked design?

**Design used**:
- Compound perturbations (2 errors per candidate)
- SIV score as primary outcome
- GPT-4o, temperature 0, 22 candidates

**Results**:

| Condition | Mean SIV | Equiv Rate |
|-----------|----------|-----------|
| Score-only | 0.6932 | 54.5% (12/22) |
| Structured | 1.0000 | 90.9% (20/22) |
| Shuffled | 1.0000 | 90.9% (20/22) |

**Δ (structured - shuffled) = 0.0000**  
Bootstrap 95% CI: [0.0000, 0.0000]

**Decision**: **LEAKAGE_SUPPORTED** — The probe-formula gain is entirely answer-leakage. Showing ANY probe formulas (regardless of pass/fail labeling) gives GPT-4o enough information to reconstruct the gold. The structured-vs-shuffled ablation shows zero difference.

---

## Critical Finding: The Per-aspect-actionability Claim Collapses

The core C2 hypothesis was: "structured SIV probe feedback enables better LLM self-correction than unstructured feedback." Investigation 4 definitively refutes this:

1. **Score-only → 69% SIV**: Without seeing probe formulas, GPT-4o achieves moderate correction.
2. **Any probes shown → 100% SIV**: The moment you show probe formulas (structured OR shuffled), GPT-4o achieves perfect correction.
3. **Structured = Shuffled**: The pass/fail structure carries no additional signal.

**Why this happens**: SIV probe formulas are sub-entailments and contrastive formulas derived FROM the gold FOL. They encode so much of the gold's structure that an LLM can reverse-engineer the gold from the probes alone. This is not a bug in the shuffling — it's a fundamental property of the probe-formula representation.

---

## What C2 Cannot Claim

- ~~"Structured diagnostic feedback enables targeted self-correction"~~ — refuted
- ~~"Per-aspect probe results guide LLMs to fix specific errors"~~ — the formulas themselves contain the answer
- ~~"SIV provides actionable correction signals at the sub-entailment level"~~ — the signal is answer-leakage

## What C2 CAN Claim (revised framing)

1. **Score-only feedback has genuine value**: Score-only achieves 54.5% equiv (vs. ~25-45% no-feedback baseline from C2 pilots). This is a real, non-leaking signal.
2. **Probe-category feedback** (without formulas): From C2 Pilot 2, category-level feedback (e.g., "polarity error detected") produced 0% gain over no-feedback. This is a genuine null result.
3. **The information hierarchy**: no-feedback < score-only < (probe formulas ≈ answer). The middle step (score-only) is the actionable frontier.

## Recommended Path Forward

### Option A: Pivot C2 to score-only depth study
- **Conditions**: no-feedback vs. score-only vs. score + error-count vs. score + category (no formulas)
- **Hypothesis**: graded score information enables correction without leaking the answer
- **Advantage**: preserves the self-correction narrative; score is non-leaking

### Option B: Reframe as an information-theoretic finding
- **Claim**: "SIV probes encode sufficient information for LLM reconstruction of gold, demonstrating that the sub-entailment decomposition is informationally complete"
- **This is actually interesting**: it validates that SIV suites capture the full logical content of the gold formula
- **Disadvantage**: no longer a self-correction story

### Option C: Use category-level only (no formulas) with harder perturbations
- **Conditions**: no-feedback vs. score-only vs. score + mutation-kind labels
- **Hypothesis**: knowing which TYPE of error is present helps, even without seeing the formulas
- **Challenge**: Pilot 2 already showed 0% gain for category-level; would need much harder candidates to see an effect

---

## Locked Numbers

| Metric | Value | Source |
|--------|-------|--------|
| Load-bearing rate (ent+contra) | 100% | Inv 1 |
| Mean LB sentences/premise | 2.56 | Inv 1 |
| Label metric sensitivity | Binary (13% partial) | Inv 2 |
| SIV-label agreement | 93.3% | Inv 2 |
| Perturbation verification rate | 75% | Inv 3 |
| Single-pert correction rate | 86.7% (too easy) | Inv 3 |
| Compound-pert score-only correction | 54.5% equiv | Inv 4 |
| Probe-formula leakage | 90.9% equiv (both conditions) | Inv 4 |
| Structured - shuffled Δ | 0.0000 | Inv 4 |

---

## Unresolved Questions

1. **Would probe-category (without formulas) help with harder candidates?** Pilot 2 says no, but those were single-perturbation candidates. Compound perturbations might reveal a category-level signal.

2. **Is the leakage result model-specific?** GPT-4o may be unusually good at reverse-engineering from sub-entailments. Testing with weaker models (GPT-4o-mini) could show a genuine structured > shuffled gap.

3. **Can we design non-leaking probe representations?** E.g., abstract probe descriptions ("a universal generalization of your formula fails") rather than actual formulas.

4. **Does the score-only signal scale with perturbation complexity?** At compound-2, score-only achieves 54.5%. At compound-3 or natural LLM errors, does score-only still help?
