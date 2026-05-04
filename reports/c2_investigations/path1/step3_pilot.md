# Step 3: Pilot Run Results

## Setup: 20 candidates × 5 conditions × GPT-4o

## Results

| Condition | Parseable | Equiv (Vampire) | Equiv (SIV) |
|-----------|-----------|-----------------|-------------|
| no_feedback | 100% | 60% | 65% |
| score_only | 100% | 65% | 65% |
| structured_category | 100% | 55% | 60% |
| shuffled_category | 100% | 55% | 60% |
| count_only | 100% | 60% | 60% |

## Primary Comparison

- Structured: 60.0%
- Shuffled: 60.0%
- **Δ = +0.000**

## Sanity Checks

- No-feedback ≈ baseline: 65.0% ✓
- Score-only ≥ no-feedback: ✓
- All parseable ≥80%: ✓

## Decision

**WEAK_SIGNAL**: Pilot Δ=+0.000 in [0, 0.05). Weak signal. Surface to user: per-aspect channel may not carry signal at category level.