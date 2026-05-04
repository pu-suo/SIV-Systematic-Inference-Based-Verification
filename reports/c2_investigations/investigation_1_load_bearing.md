# Investigation 1: Load-bearing Sentence Rate in FOLIO

## Summary

- Stories sampled: 50
- Total sentences tested: 264
- Total load-bearing sentences: 128
- **Fraction with ≥1 load-bearing sentence: 70.0%**
- **Mean load-bearing sentences per premise: 2.56**
- Vacuous-replacement flips: 128

## Per-label Breakdown

| Label | N | Has LB | % | Mean LB |
|-------|---|--------|---|---------|
| entailment | 18 | 18 | 100.0% | 3.17 |
| contradiction | 17 | 17 | 100.0% | 4.18 |
| neutral | 15 | 0 | 0.0% | 0.00 |

## Decision

**FEASIBLE_AT_SCALE**: Bridge 2 is feasible at scale via natural FOLIO sampling. ≥60% threshold met (70.0%), mean ≥1.0 met (2.56).

## Decision Rule (pre-registered)

- ≥60% with LB AND mean ≥1.0 → Bridge 2 feasible at scale
- 30-60% → feasible but needs filtering/oversampling
- <30% → not feasible, fall back to Bridge 1