# Investigation 3: Hand-perturbation Feasibility and Quality

## Error Pattern Catalog

| Pattern | Description | Source |
|---------|-------------|--------|
| arg_swap | Swap arguments of a binary predicate (e.g., Near(a,b) → Near(b,a)) | Exp A B_arg_swap, common LLM error with asymmetric relations |
| negation_flip | Add or remove negation on a predicate (e.g., P(x) → ¬P(x)) | Exp A B_negation_drop, LLM polarity errors |
| quantifier_swap | Change ∀ to ∃ or vice versa (scope confusion) | Exp A B_scope_flip, LLM quantifier confusion |
| conjunct_drop | Drop a conjunct from a conjunction (information loss) | Exp B overweak candidates that omit conditions |
| disjunction_for_conjunction | Replace ∧ with ∨ (weakening error) | Exp B overweak: P ∧ Q → P ∨ Q |
| implication_flip | Reverse implication direction (A→B becomes B→A) | Exp B gibberish candidates with reversed conditionals |
| constant_swap | Swap two constants (entity confusion) | Exp B partial candidates with wrong entity attribution |
| restrictor_drop | Drop restrictor from universal (∀x.(P(x)→Q(x)) → ∀x.Q(x)) | Exp A B_restrictor_drop, LLM over-generalization |

## Verification Results

- Perturbations constructed: 20
- **Pass all checks: 15/20 (75.0%)**
- Failures: parse=0, equivalent=1, label_unchanged=4

## Baseline Correction (GPT-4o, no feedback)

- Attempted: 15
- **Equivalent to gold: 13/15 (86.7%)**
- Restores label: 13/15 (86.7%)

## Decisions

- **Construction**: NEEDS_REVIEW — Hand-perturbation works but needs review process. 75.0% pass (60-85%). Build in verification step; reject candidates that fail.
- **Severity**: TOO_EASY — Correction rate 86.7% too high (>55%). Increase severity.