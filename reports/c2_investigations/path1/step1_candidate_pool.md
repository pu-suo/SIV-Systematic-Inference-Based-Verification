# Step 1: Candidate Pool

## Summary

- Target: 80 candidates
- Achieved: 80
- Examples checked: 36
- Rejections: parse_fail=10, label_mismatch=15, perturb_fail=0, equiv=0, no_label_change=27, no_cat_fail=0

## Category Distribution

| Category | Count | % of candidates |
|----------|-------|-----------------|
| argument-order | 0 | 0.0% |
| quantifier-scope | 0 | 0.0% |
| restrictor-content | 8 | 10.0% |
| polarity | 75 | 93.8% |
| connective-polarity | 3 | 3.8% |
| content-gap | 80 | 100.0% |

## Baseline Correction Rate (GPT-4o, no feedback)

**48/80 (60.0%)**

Decision: **SLIGHTLY_EASY** — Baseline rate 60.0% slightly easy (45-60%). Proceed but expect smaller effects.

## Decision Rule (pre-registered)

- 30-45%: in band, proceed
- 45-60%: slightly easy, proceed with note
- >60%: too easy, STOP
- 20-30%: borderline, proceed with flag
- <20%: too hard, STOP