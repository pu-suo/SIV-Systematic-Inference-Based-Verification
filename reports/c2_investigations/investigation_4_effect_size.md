# Investigation 4: Effect-size Estimate at Locked Design

## Design

- Primary outcome: SIV score (per Investigation 2)
- Perturbation: compound 2-error (per Investigation 3)
- Model: GPT-4o, temperature 0
- 3 conditions: score-only, structured-probe, shuffled-trace

## Results

| Condition | Mean SIV | Equiv Rate |
|-----------|----------|-----------|
| Score-only | 0.6932 | 12/22 |
| Structured | 1.0000 | 20/22 |
| Shuffled | 1.0000 | 20/22 |

**Δ (structured - shuffled): +0.0000**
**Δ (structured - score_only): +0.3068**

Bootstrap CI: insufficient data

## Decision

**LEAKAGE_SUPPORTED**: No effect: Δ=+0.0000 < 0.05. Probe-formula gain was likely answer-leakage. Per-aspect-actionability claim collapses. STOP and rethink before main run.

## Decision Rule (pre-registered)

- Δ ≥ 0.15: strong effect, n=80 sufficient
- 0.05 ≤ Δ < 0.15: moderate, n=100
- Δ < 0.05: leakage, rethink