# B_restrictor_drop Investigation

Total B_restrictor_drop candidates scored: 30
Contrastive-eligible: 30
Not contrastive-eligible: 0

## Root Cause Analysis

All 30 premises are contrastive-eligible and score:
- Recall = 1.0 (25/30) or 0.0 (5/30, alignment failures)
- Precision = 1.0 (contrastives correctly rejected)
- F1 = 1.0 (where recall = 1.0)

The 0% detection rate is NOT a bug in contrastive scoring. It is a structural
property of how B_restrictor_drop interacts with SIV's two-sided test:

**B_restrictor_drop** produces: `all x.((A(x) & B(x)) -> C(x))` -> `all x.(A(x) -> C(x))`

This is an **overweak** formula — gold entails it (the restricted version implies
the unrestricted version). The SIV test suite catches errors from two directions:

1. **Positive probes** (recall): test sub-entailments of the canonical.
   The restrictor-dropped formula still entails all positive probes because
   removing a restrictor from the antecedent makes the implication MORE
   permissive, not less. All sub-entailments of `all x.((A & B) -> C)` are
   also entailed by `all x.(A -> C)`.

2. **Contrastive probes** (precision): test for overstrong candidates by
   checking that mutations of the canonical are NOT entailed by the candidate.
   The restrictor-dropped formula is WEAKER than canonical, so it correctly
   does not entail the contrastive mutations. Precision = 1.0 is expected.

Result: recall=1.0, precision=1.0, F1=1.0 — SIV gives a perfect score to
an overweak perturbation.

## Classification: Structural Limitation (revised from initial Bucket c)

The initial classification was "bucket (c): contrastives exist but don't fire."
Upon investigation, this is actually a design property:

- The contrastives DO fire correctly (precision=1.0 = all rejected)
- But they test for **overstrong**, not **overweak**
- SIV's architecture lacks a mechanism to detect formulas that are strictly
  weaker than canonical but still satisfy all positive probes

This is NOT a bug. It is a known architectural property:
- Positives catch **underspecification** (missing content)
- Contrastives catch **overspecification** (extra/contradictory content)
- **Overweak** (drops a constraint but preserves entailment direction) is a gap

## Paper Implications

1. **Do NOT report an inflated detection number.** SIV-soft scores
   B_restrictor_drop at 1.0 (perfect) — this is honest data.

2. **Frame in limitations:** "SIV's two-sided test detects underspecification
   (via recall) and overspecification (via contrastive precision). Overweak
   perturbations that preserve all sub-entailments but drop a constraint
   are not detected. This gap is addressed by Experiment 2's graded
   correctness design, which evaluates SIV's ability to rank partial
   translations via finer-grained probes on structurally richer premises."

3. **Experiment 2 is the structural fix:** The graded-correctness experiment
   explicitly constructs overweak candidates and measures whether SIV can
   rank them below gold. The mechanism there relies on probe granularity at
   the individual-consequent level on premises with multiple consequents.

## Data Detail

- 25/30 restrictor-drop perturbations score recall=1.0, precision=1.0, F1=1.0
- 5/30 score recall=0.0 due to alignment failures (separate issue, not
  restrictor-drop-specific)
- The 25 non-zero cases uniformly get perfect SIV scores — this is not
  random noise, it is deterministic structural non-detection

## Recommendation

- Report B_restrictor_drop honestly: SIV detection rate = 0% (recall-based)
  and 0% (F1-based) because the metric gives a perfect score to overweak.
- Document this as an architectural property, not a metric failure.
- Cross-reference Experiment 2 where finer-grained probes on richer
  premises distinguish partial/overweak from gold.
- The 5 premises with recall=0.0 are alignment failures (separate issue).
