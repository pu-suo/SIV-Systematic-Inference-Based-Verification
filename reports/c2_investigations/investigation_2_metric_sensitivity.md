# Investigation 2: Outcome-metric Sensitivity to Correction Quality

## Summary

- Cases tested: 15
- Gold produces correct label: 15/15 (100.0%)
- Corrupted produces wrong label: 14/15 (93.3%)
- **Partial repair produces correct label: 2/15 (13.3%)**
- Full repair produces correct label: 12/15 (80.0% if applicable)

## Decision

**BINARY_COLLAPSE**: Outcome collapses to binary. Partial repairs only 13.3% correct (<30%). Only essentially-equivalent corrections produce right label. Use SIV-equivalence as primary outcome.

## Per-case Detail

| # | Story | Label | Corruption | Gold✓ | Corrupt✓ | Partial✓ | Full✓ | SIV-gold | SIV-corrupt | SIV-partial |
|---|-------|-------|-----------|-------|----------|----------|-------|----------|-------------|-------------|
| 1 | 374 | contradiction | negate_consequent | ✓ | ✗ | ✗ | ✗ | 1.000 | 0.000 | 0.000 |
| 2 | 134 | contradiction | drop_conjunct | ✓ | ✗ | ✓ | ✓ | 1.000 | 0.333 | 0.333 |
| 3 | 317 | contradiction | flip_quantifier | ✓ | ✗ | ✗ | ✓ | 1.000 | 0.000 | 0.000 |
| 4 | 22 | entailment | arg_swap | ✓ | ✗ | ✗ | ✓ | 1.000 | 0.000 | 0.000 |
| 5 | 125 | entailment | arg_swap | ✓ | ✗ | ✗ | ✓ | 1.000 | 0.000 | 0.000 |
| 6 | 27 | entailment | arg_swap | ✓ | ✓ | ✓ | ✗ | 1.000 | 0.667 | 0.667 |
| 7 | 438 | contradiction | flip_quantifier | ✓ | ✗ | ✗ | ✓ | 1.000 | 0.000 | 0.000 |
| 8 | 309 | contradiction | flip_quantifier | ✓ | ✗ | ✗ | ✓ | 1.000 | 0.000 | 0.000 |
| 9 | 309 | contradiction | flip_quantifier | ✓ | ✗ | ✗ | ✓ | 1.000 | 0.000 | 0.000 |
| 10 | 314 | entailment | negate_consequent | ✓ | ✗ | ✗ | ✓ | 1.000 | 0.000 | 0.000 |
| 11 | 22 | entailment | arg_swap | ✓ | ✗ | ✗ | ✓ | 1.000 | 0.000 | 0.000 |
| 12 | 317 | contradiction | flip_quantifier | ✓ | ✗ | ✗ | ✓ | 1.000 | 0.000 | 0.000 |
| 13 | 314 | entailment | negate_consequent | ✓ | ✗ | ✗ | ✓ | 1.000 | 0.000 | 0.000 |
| 14 | 374 | contradiction | flip_quantifier | ✓ | ✗ | ✗ | ✗ | 1.000 | 0.000 | 0.000 |
| 15 | 125 | entailment | negate_consequent | ✓ | ✗ | ✗ | ✓ | 1.000 | 0.000 | 0.000 |

## Decision Rule (pre-registered)

- 50-70% partial correct → metric is graded, use entailment-label as primary
- >85% → saturates, use SIV-equivalence as primary
- <30% → collapses to binary, use SIV-equivalence as primary