# FOLIO Problem 1208 — Before/After Refactor

## Final Test Suite Health

```
137 passed, 3 warnings in 4.09s
(3 PytestCollectionWarning for TestSuite dataclass — pre-existing, non-fatal)
0 failures, 0 errors
```

## Problem Statement

FOLIO Problem 1208 contains seven premises. P1: all employees who schedule a meeting with customers go to the company building. P2: everyone who has lunch in the company building schedules meetings with customers. P3: employees have lunch either in the company building or at home (exclusive). P4: if an employee has lunch at home, they are working remotely from home. P5: all employees in other countries work remotely from home. P6: no managers work remotely from home. P7: James appears in the company today if and only if he is a manager.

## Pre-Refactor Baseline

Recall baselines derived from code analysis (Fix A not yet applied); precision baselines from test-file annotations (Fix D1+D2 not yet applied).

| Premise | recall_total | recall_passed | precision_total | precision_passed | SIV   |
|---------|-------------|---------------|-----------------|-----------------|-------|
| P1      | 6           | 0             | 0               | 0               | 0.000 |
| P2      | 8           | 0             | 0               | 0               | 0.000 |
| P3      | 4           | 0             | 0               | 0               | 0.000 |
| P4      | 4           | 0             | 0               | 0               | 0.000 |
| P5      | 4           | 0             | 0               | 0               | 0.000 |
| P6      | 1           | 0             | 1               | 0               | 0.000 |
| P7      | 4           | 0             | 1               | 1               | 0.000 |

Notes: P1–P5 precision was 0 because binary facts received no precision tests (only unary predicates got antonym/`Non<Pred>` tests, which trivially passed). P4 had no macro/entailment test because the CONDITIONAL branch only accepted unary facts. P6's precision test was a trivially-passing `NonWorkRemotelyFromHome` synthetic predicate.

## Post-Refactor Results

Collected from `pytest tests/test_regression_1208.py::test_final_state_siv_scores_per_premise` (strict_mode=False, prover_timeout=1s).

| Premise | recall_total | recall_passed | precision_total | precision_passed | SIV   | extraction_invalid |
|---------|-------------|---------------|-----------------|-----------------|-------|--------------------|
| P1      | 4           | 0             | 9               | 9               | 0.000 | False              |
| P2      | 6           | 0             | 12              | 12              | 0.000 | False              |
| P3      | 2           | 0             | 4               | 4               | 0.000 | False              |
| P4      | 5           | 0             | 6               | 6               | 0.000 | False              |
| P5      | 2           | 0             | 6               | 6               | 0.000 | False              |
| P6      | 1           | 0             | 1               | 0               | 0.000 | **True**           |
| P7      | 4           | 0             | 3               | 2               | 0.000 | False              |

Note: recall_passed=0 throughout because Vampire is unavailable in the test environment and the gold FOL predicates (e.g. `AppearIn`, `Schedule`) do not match the extractor's Tenet-1-strict surface forms (e.g. `GoTo`, `Has`). This is expected and intentional: SIV correctly penalizes predicate drift. The SIV score is 0.0 pre- and post-refactor, but the meaning of that 0 is now precise and diagnostic.

## Per-Fix Contribution Analysis

**Fix A** (universal binding tests): Affects P1, P2, P3, P5. Before Fix A, facts with universal-entity arguments generated vocabulary probes (`exists x.(SubjType(x))`) that are mathematically vacuous against a universal-conditional gold. Fix A suppressed those probes and replaced them with universally-quantified binding tests (`all x.(SubjType(x) -> exists y.(ObjType(y) & Pred(x,y)))`). recall_total dropped from 6→4 (P1), 8→6 (P2), 4→2 (P3), 4→2 (P5). No predicates were added or removed — only quantifier wrapping was corrected.

**Fix B1** (prover-unresolved silent credit): No change to numeric scores on this problem because Vampire is unavailable and all predicates are absent from the gold → Tier 1 definitively fails everything before reaching Tier 3. The fix matters on problems where the prover times out mid-run.

**Fix G1** (CONDITIONAL binary-fact macro): Affects P4. Before Fix G1, the CONDITIONAL branch required two unary facts; P4's facts are both binary (`has lunch at`, `working remotely from`), so zero macro tests were emitted. After Fix G1, a universal-conditional entailment test is generated: `all x.(HasLunchAt(x,y) -> WorkingRemotelyFrom(x,y))`. recall_total rose from 4→5.

**Fix G2** (TYPE_A picks first universal entity): Affects P1, P2, P3, P5. Ensures the macro binding test universally quantifies over the entity declared as `UNIVERSAL`, not the entity that happens to appear first in the list. No numeric change visible here (entities happen to be ordered correctly in Problem 1208), but the fix prevents silent misquantification on other problems.

**Fix D1+D2** (structural perturbation precision tests): Affects all premises. Before: P1–P5 had precision_total=0 (binary facts got no tests); P6=1 (trivially-passing synthetic `Non<Pred>`); P7=1. After: binary facts generate argument-swap, polarity-flip, and cross-predicate substitution tests drawn from the same extraction. P1: 0→9, P2: 0→12, P3: 0→4, P4: 0→6, P5: 0→6, P6: unchanged at 1, P7: 1→3. `data/perturbation_map.json` deleted.

**Fix C1** (Neo-Davidsonian validator): Affects P6. Before: the compiler accepted `work remotely from home(e1)` as a valid 1-arg predicate, camelCased it to `WorkRemotelyFromHome`, and emitted a test that the gold never contained — scoring SIV=0 with no explanation. After: the validator rejects any 1-arg predicate whose surface contains a preposition token, sets `extraction_invalid=True`, and attaches a `SchemaViolation(violation_type="prepositional_unary")`. The score is still 0.0 but now carries a machine-readable reason.

**Fix E1** (whitespace normalization in entity registry): Not triggered by Problem 1208 (no double-spaced entity surface forms). The fix prevents `"company building"` and `"company  building"` from registering as different entities across sentences.

## The P6 Exhibit

P6 ("No managers work remotely from home") is a perfectly grammatical English sentence. The LLM extractor welded the prepositional phrase "from home" into the unary predicate: `work remotely from home(e1)`. This violates the Neo-Davidsonian imperative (Tenet 2): the preposition "from" signals a second argument that should have been reified as a separate entity with a binary edge.

**Pre-refactor:** P6 scored SIV=0.000 with precision=1.000 (the precision test was `NonWorkRemotelyFromHome`, a synthetic predicate the gold never contained — trivially "safe") and recall=0.000 (the gold `Work(x,home)` doesn't match the bogus `WorkRemotelyFromHome`). The score was uninformative noise.

**Post-refactor:** P6 scores SIV=0.000 with `extraction_invalid=True` and a concrete `SchemaViolation(violation_type="prepositional_unary", fact_pred="work remotely from home", message="...")`. Zero prover calls are made. The downstream user knows *why* the score is 0 — not that the gold was wrong, but that the extraction itself was non-executable. Under Tenet 4, SIV does not rescue this with a multi-reference test or graceful degradation.

The two outputs share the same numeric score; the post-refactor output is diagnostic.

## Intended Philosophy Demonstrations

- **Tenet 1 (Lexical Faithfulness):** P1's gold uses `Schedule(x,meeting,customers)` (ternary) and `AppearIn(x,company)` while the extractor emits `Schedule`, `With`, `GoTo` as separate binary predicates. The predicate names don't match, and SIV correctly scores recall=0 — no stemming or synonym expansion rescues the drift.
- **Tenet 2 (Neo-Davidsonian Imperative):** P6. The 1-arg predicate `work remotely from home` contains a preposition, proving the argument was not reified. SIV flags it as `extraction_invalid` rather than camelCasing it into a usable-looking predicate.
- **Tenet 3 (Structural Overlap Over Deep Pragmatics):** P3. "Employees have lunch either in the company building *or* at home" contains an exclusive-or structure. SIV flattens it to two conjunctive `HaveLunch` binding tests and does not verify the exclusive-or constraint — that is deliberately out of scope.
- **Tenet 4 (A Standard, Not a Safety Net):** P6. SIV does not add a multi-reference test to rescue the malformed extraction. The extraction violated the contract; the score is 0 with an explanation.

---

## Raw Pytest Output (for reproducibility)

```
$ pytest tests/ -q
........................................................................ [ 52%]
.................................................................        [100%]
=============================== warnings summary ===============================
siv/schema.py:180: PytestCollectionWarning: cannot collect test class 'TestSuite' ...
siv/schema.py:180: PytestCollectionWarning: cannot collect test class 'TestSuite' ...
siv/schema.py:180: PytestCollectionWarning: cannot collect test class 'TestSuite' ...

-- Docs: https://pytest.org/en/stable/how-to/capture-warnings.html
137 passed, 3 warnings in 4.09s
```
