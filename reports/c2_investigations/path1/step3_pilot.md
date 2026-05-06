# Step 3: Pilot Run Results

## Setup: 20 candidates × 5 conditions × GPT-4o

## Results

| Condition | Parseable | Equiv (Vampire) | Equiv (SIV) |
|-----------|-----------|-----------------|-------------|
| no_feedback | 100% | 60% | 60% |
| score_only | 100% | 60% | 60% |
| structured_category | 100% | 55% | 55% |
| shuffled_category | 100% | 50% | 55% |
| count_only | 100% | 60% | 60% |

## Primary Comparison

- Structured: 55.0%
- Shuffled: 55.0%
- **Δ = +0.000**

## Sanity Checks

- No-feedback ≈ baseline: 60.0% ✓
- Score-only ≥ no-feedback: ✓
- All parseable ≥80%: ✓

## Decision

**WEAK_SIGNAL**: Pilot Δ=+0.000 in [0, 0.05). Weak signal. Surface to user: per-aspect channel may not carry signal at category level.