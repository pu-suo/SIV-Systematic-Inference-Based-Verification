# Step 1: Difficulty Calibration

## Results

| Difficulty Level | Source | Perturbation | Baseline Rate | Band |
|-----------------|--------|-------------|---------------|------|
| **A** | Multi-quantifier FOLIO | compound-3 | **20%** | ✓ IN BAND |
| B | Hand-constructed deep nesting | compound-2 | 70% | Too easy |
| C | Adversarial (surface-plausible) | mixed | 30% | Borderline |

## Decision

**Difficulty A selected**: Multi-quantifier FOLIO premises (≥2 quantifiers) with compound-3 perturbation produces a 20% no-feedback baseline — squarely in the 10-30% target band.

## Why Difficulty A Works

- Multi-quantifier FOLIO premises (308 available) are genuinely hard for GPT-4o
- Compound-3 perturbation (3 layers) further disrupts the structure
- The LLM cannot simply retranslate from NL because the NL→FOL mapping is non-trivial for these cases (nested scopes, complex restrictors)
- At 20% baseline, there is room for diagnostic feedback to provide genuine uplift

## Why Difficulty B Failed

Hand-constructed FOL with only compound-2 perturbation was too easy (70%). The hand-crafted NL sentences are "clean" and unambiguous, making retranslation straightforward even with perturbation. FOLIO's naturally ambiguous/complex NL is harder.

## Source for Main Experiment

- Pool: 308 multi-quantifier FOLIO premises
- Perturbation: compound-3 (3 distinct perturbation layers)
- Expected yield: ~60 verified candidates from this pool (allowing for verification failures)
