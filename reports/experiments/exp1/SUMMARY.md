# Experiment 1 — Binary Correctness (Parity Demonstration)

## Setup

368 premises from FOLIO train pass the aligned-subset filter (Jaccard >= 0.5,
full predicate alignment, quantifier-skeleton match, gold parses, no free
variables in gold). 46 of these have >= 2 applicable Tier-B perturbation
operators; these constitute the scored subset. Each premise is perturbed via
B_arg_swap, B_negation_drop, B_scope_flip, B_restrictor_drop, and D_random_predicates,
applied to the FOLIO gold FOL. Each perturbation is scored with 8 metrics:
BLEU, BERTScore, MALLS-LE (raw/aligned), Brunello-LT (raw/aligned), SIV-strict,
and SIV-soft. 510 total scored candidate rows.

## Results

Detection rate = fraction of perturbations scoring below threshold
(0.8 for continuous metrics, 1.0 for binary equivalence metrics):

| Operator | n | BLEU | BERTScore | MALLS-LE-aligned | Brunello-LT-aligned | SIV-soft (recall) |
|---|---|---|---|---|---|---|
| B_arg_swap | 42 | 100% | 0% | 100% | 100% | 100% |
| B_negation_drop | 23 | 65.2% | 0% | 100% | 100% | 65.2% |
| B_scope_flip | 1 | 100% | 0% | 100% | 100% | 0% |
| B_restrictor_drop | 30 | 100% | 0% | 100% | 100% | 16.7% |
| D_random | 46 | 100% | 0% | 100% | 100% | 100% |

## Honest interpretation

- **BERTScore detection is 0% on all operators.** BERTScore is unsuitable for
  FOL-string evaluation. All perturbations score >= 0.8 because BERTScore's
  contextual embeddings treat FOL symbols as natural-language tokens and find
  high similarity regardless of logical content. This is a finding about
  BERTScore, not about SIV.

- **BLEU achieves high detection via token-level sensitivity** to short-string
  perturbations. A single argument swap changes multiple bigrams in a short
  FOL string. This is mechanical token-overlap response, not logical
  understanding. The Exp 1 setup happens to favor BLEU because perturbations
  of short FOL strings are highly visible at the token level.

- **MALLS-LE and Brunello-LT achieve 100% by construction.** Any perturbation
  of gold produces a non-equivalent formula, which Vampire/Z3 flag against
  the gold reference. They use gold as ground truth that SIV does not have
  access to.

- **SIV achieves 100% on B_arg_swap and D_random, 65% on B_negation_drop,
  and 17% on B_restrictor_drop** (the 17% is entirely from alignment failures
  scoring 0.0, not real detection). SIV does this WITHOUT seeing gold — it
  scores via the test suite derived from the NL premise.

## What this experiment demonstrates

SIV is competitive with reference-based metrics on argument and identifier
perturbations, while being reference-free. The B_restrictor_drop result is an
architectural property: overweak perturbations preserve all positive
sub-entailments, so recall stays at 1.0; contrastive probes test for
overstrength, not underspecification, so precision stays at 1.0. This gap is
by design and is exactly what Experiment 2 demonstrates SIV can address via
finer-grained probes on richer premises.

## What this experiment does NOT demonstrate

- **Superiority over MALLS-LE / Brunello-LT.** The reference-based design has
  structural advantages on this task. Superiority is demonstrated in
  Experiments 2 and 3.
- **Logical understanding by BLEU.** BLEU's high numbers are token-mechanics.
- **General-corpus performance.** The aligned-subset filter excludes ~75% of
  FOLIO premises where extraction style diverges from gold's annotation style.
  SIV's applicability boundary is part of the limitations section.

## Numbers for the paper to cite

- Aligned-subset size: 368 premises
- Premises with >= 2 applicable Tier-B operators: 46
- Smoke test pass rate: 28/30 = 93.3%
- Per-operator detection rates: see per_operator.json
- Scoring timeout: 10s per Vampire call
- Seed: 42 (locked for D_random_predicates)
