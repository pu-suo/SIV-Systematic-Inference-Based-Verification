# Step 3: Locked Experimental Design (Path 1-Hard)

*Identical to Path 1 design except candidate source. Pre-registered before any scoring.*

## What changed from Path 1

| Aspect | Path 1 | Path 1-Hard |
|--------|--------|-------------|
| Candidate source | All FOLIO (simple + complex) | Multi-quantifier FOLIO only |
| Perturbation | compound-3 | compound-3 |
| No-feedback baseline | 60% | 26.7% |
| Pool size | 80 | 60 |
| Hypothesis | Per-aspect helps at any difficulty | Per-aspect helps when LLM can't zero-shot |

## Everything else is identical to Path 1

- Same 5 conditions (no-feedback, score-only, structured-category, shuffled-category, count-only)
- Same category vocabulary (locked from Step 0)
- Same shuffling protocol (replace actual with non-actual, same count)
- Same prompt templates (from path1/step2_prompts.json)
- Same models (GPT-4o, GPT-4o-mini, Claude Sonnet), temperature 0, 3 seeds
- Same outcome metrics (primary: SIV equiv; secondary: Vampire equiv, label match)
- Same statistical test (paired bootstrap, 10,000 resamples)
- Same acceptance threshold (Δ ≥ 0.10, p < 0.05)
- Same decision branches

## The Scientific Hypothesis

At Path 1's difficulty (baseline 60%), GPT-4o retranslates from NL alone. Category feedback is ignored because it's not needed.

At Path 1-Hard's difficulty (baseline 27%), GPT-4o CANNOT retranslate from NL alone — it fails 73% of the time without help. Under this condition, if category feedback provides genuine diagnostic signal, we should see structured > shuffled because:
- Structured tells the LLM WHICH aspects are wrong → targeted fix
- Shuffled tells the LLM WRONG aspects → no useful signal, no better than score-only

If structured ≈ shuffled even here, the per-aspect channel is fundamentally non-actionable regardless of difficulty.
