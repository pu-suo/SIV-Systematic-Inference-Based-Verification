# SIV Refactor Plan

*The exact sequence of changes needed to bring the codebase into alignment with `SIV_Philosophy.md` and `SIV_Master_Document.md`.*

This plan assumes the decision has been made to revert to the last clean v1 commit and rebuild from there, rather than continuing to patch the half-migrated v2 state. The rationale for that decision is in the project discussion history; this document is purely the execution plan.

---

## Ground rules

1. **Every change references a specific section of `SIV_Master_Document.md` or `SIV_Philosophy.md`.** Changes that do not trace to either document are out of scope.
2. **One phase, one commit, one review gate.** A phase does not merge until its gate is green.
3. **Pydantic models are the source of truth for all schemas.** The JSON Schema passed to the LLM is derived from the Pydantic model. Hand-rolled JSON Schemas are forbidden.
4. **Forbidden concepts stay forbidden.** The list in `SIV_Philosophy.md §9` is the canonical negative-list. No phase introduces anything on it.
5. **Rename cleanly, never alias.** If a symbol is renamed, every call site is updated in the same commit. No `X = Y` backward-compatibility aliases.
6. **Failing tests are information.** If a test fails during a phase, that is the phase doing its job. Do not loosen assertions to pass tests; fix the underlying issue or escalate.
7. **The `Formula` type is the complete grammar.** It has four cases (atomic, quantification, negation, connective). No fifth case is ever added. If a sentence appears to need a fifth case, it is either outside FOL (out of scope) or representable via composition of the existing four.

---

## Phase 0 — Revert and capture

**Goal:** Return the repository to the last clean v1 state, with the new architecture documents in place as the specification for everything that follows.

**Steps:**

1. Identify the last git commit where v1 was clean (before v2 refactor work began). Tag it `v1-final`.
2. Create a new branch `v2-from-clean` from that tag. All subsequent work happens here. The existing partially-migrated v2 branch is archived, not deleted — it is reference history.
3. Copy the following documents into `docs/` on the new branch, in this order:
   - `docs/SIV_Philosophy.md`
   - `docs/SIV_Master_Document.md` (replacing any v1 master document)
   - `docs/SIV_Refactor_Plan.md` (this file)
4. Move the old v1 master document, if it exists, to `docs/archive/v1_master_document.md`. Do not delete it; it is useful historical reference.
5. Move the following from the archived v2 branch into `reports/archive/`: `baseline_audit.csv`, `baseline_audit_summary.json`, `drift_audit.md`, `compiler_state_audit.md`. These are valid measurements of v1 behavior and should be preserved.
6. Delete any stale `v2`-era plan files from the repo root. Anything with `Phase`, `Refactor`, or similar in the filename that is not one of the three documents above goes.

**Gate:** The repo is at `v1-final` + three documentation files. Running the existing v1 test suite passes. `git log --oneline` shows only v1 history plus the documentation commit.

---

## Phase 1 — Schema and compiler

**Goal:** Implement the `Formula`-based schema (`SIV_Master_Document.md §4.2`) and the recursive two-path compiler (`§4.4`). This is the foundational change; everything else builds on it.

**Scope (files touched):**

- `siv/schema.py` — full rewrite.
- `siv/compiler.py` — full rewrite.
- `siv/json_schema.py` — new file; derives API-level JSON Schema from the Pydantic model.
- `tests/test_schema.py` — full rewrite.
- `tests/test_compiler.py` — full rewrite.
- Everything else in `siv/` — left alone. It will break after this commit; that is expected and fixed in later phases.

**What to implement:**

### 1.1 The Formula type and related models

Pydantic models exactly as sketched in `SIV_Master_Document.md §4.2`:

```python
class PredicateDecl(BaseModel):
    name: str
    arity: Literal[1, 2]
    arg_types: List[str]  # length == arity

class Entity(BaseModel):
    id: str
    surface: str
    type: str

class Constant(BaseModel):
    id: str
    surface: str
    type: str

class AtomicFormula(BaseModel):
    pred: str               # must reference a declared PredicateDecl.name
    args: List[str]         # length == pred.arity
    negated: bool = False

class InnerQuantification(BaseModel):
    quantifier: Literal["universal", "existential"]
    variable: str
    var_type: str

class TripartiteQuantification(BaseModel):
    quantifier: Literal["universal", "existential"]
    variable: str
    var_type: str
    restrictor: List[AtomicFormula]
    nucleus: "Formula"
    inner_quantifications: List[InnerQuantification] = []

class Formula(BaseModel):
    # Exactly one of the four cases is populated.
    atomic: Optional[AtomicFormula] = None
    quantification: Optional[TripartiteQuantification] = None
    negation: Optional["Formula"] = None
    connective: Optional[Literal["and", "or", "implies", "iff"]] = None
    operands: Optional[List["Formula"]] = None

class SentenceExtraction(BaseModel):
    nl: str
    predicates: List[PredicateDecl] = []
    entities: List[Entity] = []
    constants: List[Constant] = []
    formula: Formula
```

Forward references need `model_rebuild()` calls at module bottom.

### 1.2 Validation

`validate_extraction(extraction: SentenceExtraction) -> None` raises `SchemaViolation` for any of:

- A `Formula` with zero or more than one of its four cases populated.
- A `Formula` with `connective` populated but `operands` empty, missing, or of an arity not matching the connective (implies/iff are binary; and/or are n-ary with at least two operands).
- A `Formula` with `operands` populated but `connective` absent.
- An `AtomicFormula` whose `pred` does not match a declared `PredicateDecl.name`.
- An `AtomicFormula` whose `args` length differs from the referenced predicate's arity.
- An `AtomicFormula` whose arg references a variable or constant not in scope (variables are in scope within the quantification that binds them; constants are in scope globally).
- A `TripartiteQuantification` with an empty `restrictor` AND whose nucleus consists of a single atom over the bound variable. (Guards against degenerate "quantifications" that are really bare atoms.)

**Forbidden:** No `is_fol_expressible` field. No `rejection_reason` field. No `rejection_note` field. No `FOLRejectionReason` enum. These are on the forbidden list in `SIV_Philosophy.md §9`.

### 1.3 JSON Schema derivation

`siv/json_schema.py::derive_extraction_schema() -> dict` returns the OpenAI-compatible JSON Schema derived from `SentenceExtraction.model_json_schema()`. The derivation:

- Inlines all `$ref`/`$defs` (OpenAI strict mode requirement).
- Sets `additionalProperties: false` on every object.
- Marks every property as `required` (null values expressed via union types).
- Strips `title`, `description`, `default`.

This function is the single API-level schema. Hand-rolled schemas are forbidden.

### 1.4 Recursive compiler

Two entry points in `siv/compiler.py`:

- `compile_sentence_test_suite(extraction) -> TestSuite` — emits positive tests. The full canonical FOL is one positive test; each non-trivial sub-formula also emits its own entailment test, so atomic claims are independently checkable.
- `compile_canonical_fol(extraction) -> str` — emits a single canonical FOL formula.

Both are recursive over `Formula`:

```python
def _compile_formula(f: Formula, ctx) -> str:
    if f.atomic is not None:
        return _compile_atom(f.atomic)
    if f.quantification is not None:
        return _compile_quantification(f.quantification, ctx)
    if f.negation is not None:
        return f"-({_compile_formula(f.negation, ctx)})"
    if f.connective is not None:
        return _compile_connective(f.connective, f.operands, ctx)
    raise SchemaViolation("empty Formula")
```

Compilation rules are exactly those in `SIV_Master_Document.md §4.4`. The two entry points are structurally distinct — different traversal order, different variable-naming scheme, different string-assembly — so that a bug in one does not silently propagate to the other.

NLTK-compatible ASCII output: `all x.(P(x) -> Q(x))`, `exists x.(P(x) & Q(x))`, `-P(x)`, `(A & B)`, `(A | B)`, `(A -> B)`, `(A <-> B)`.

### 1.5 Tests required

**Validation tests:**

- Every validator has positive and negative cases.
- Every `SchemaViolation` case has a dedicated test.
- A test that JSON Schema derivation is stable across runs (determinism check).

**Compilation tests — covering all four Formula cases:**

- **Atomic case**: "Miroslav Venhoda was a Czech choral conductor" → `CzechChoralConductor(miroslav)`.
- **Quantification case**: the employees-meetings bug-killer → `all x.(Employee(x) & exists y.(Meeting(y) & Schedule(x, y)) -> exists z.(CompanyBuilding(z) & Attend(x, z)))` or semantic equivalent with populated restrictor on the left of the implication.
- **Negation case**: "Smith is not a Czech conductor" → `-CzechConductor(smith)`.
- **Connective-and case**: "Alice is tall and Bob is short" → `(Tall(alice) & Short(bob))`.
- **Connective-or case**: "The L-2021 monitor is either used in the library or has a type-c port" → `(UsedIn(monitor, library) | HasTypeC(monitor))` (with appropriate atomic decomposition).
- **Connective-implies case**: "If it rains, then the ground is wet" → `(Rains() -> Wet(ground))`.
- **Connective-iff case**: "Archie can walk if and only if he has functional brainstems" → `(CanWalk(archie) <-> HasFunctionalBrainstems(archie))`.
- **Nested case**: "If a legislator is found guilty, they will be suspended" → `all x.(Legislator(x) -> (exists y.(Theft(y) & FoundGuilty(x, y)) -> Suspended(x)))` or semantic equivalent.
- **Quantifier in connective case**: "Amy spends the most time on sports, or Amy is an Olympic gold medal winner" — top-level `or` over two atomic propositions.

**Two-path equivalence test:** For each of the above, call both `compile_sentence_test_suite` and `compile_canonical_fol` on the same extraction, then use Vampire to verify bidirectional entailment of their outputs. This is the live exercise of the §4.7 soundness invariant.

**Gate:**

- All schema and compiler tests pass.
- All nine Formula-case tests produce correct FOL.
- Vampire-based bidirectional-entailment test passes on every test case.
- Line count of `compiler.py` is under 400 lines. (Slightly higher ceiling than the quantifier-only version because of the additional Formula cases; recursion keeps the growth modest.)

**Explicit non-goals for Phase 1:**

- No extractor, no pre-analyzer, no contrastive generator, no scorer. Those are later phases.
- No few-shot examples file. That comes in Phase 2.

---

## Phase 2 — Pre-analyzer and extractor

**Goal:** Implement the deterministic pre-analyzer (`§4.1`) and the extractor with JSON-schema binding and tripwire enforcement (`§4.3`).

**Scope:**

- `siv/pre_analyzer.py` — rewrite.
- `siv/extractor.py` — rewrite.
- `siv/frozen_client.py` — update the `response_format` binding to use the derived JSON Schema from Phase 1.
- `prompts/extraction_system.txt` — rewrite.
- `prompts/extraction_examples.json` — rewrite.
- `tests/test_pre_analyzer.py`, `tests/test_extractor.py`, `tests/test_extraction_roundtrip.py` — rewrite or create.

**What to implement:**

### 2.1 Pre-analyzer

`compute_required_features(sentence: str) -> RequiredFeatures` where `RequiredFeatures` is a frozen dataclass with exactly two fields: `requires_restrictor: bool` and `requires_negation: bool`. No other fields. No modal/temporal/proportional detection. The forbidden list is authoritative.

- `requires_restrictor` detection: any subject-NP token has `dep_ == "relcl"`, OR the sentence matches the regex `^(all|every|each|no|any)\s+\w+\s+(who|that|which)\b` (case-insensitive).
- `requires_negation` detection: lemma `no|none|never|neither` appears, OR `neg` dependency on the main verb.

### 2.2 Extractor

`extract_sentence(sentence, client) -> SentenceExtraction`:

- Call the frozen LLM with the system prompt, few-shot examples, and the sentence. JSON Schema from Phase 1 is passed as `response_format`.
- Parse the response into a `SentenceExtraction` via Pydantic.
- Run `validate_extraction` from Phase 1.
- Compute `RequiredFeatures` and enforce tripwires:
  - If `requires_restrictor=True`, walk the formula tree looking for at least one `TripartiteQuantification` with a populated restrictor. If none exists, raise `SchemaViolation("restrictor required but missing")`.
  - If `requires_negation=True`, walk the formula tree looking for at least one negation (any of: `Formula.negation` node, `AtomicFormula.negated=True`, a `connective="not"` case — wait, there is no "not" connective; `negation` is its own case). If none exists, raise `SchemaViolation("negation required but missing")`.
- On any `SchemaViolation`, retry once with the violation message appended to the system prompt.
- After one retry, if still failing, raise to caller. No infinite loop.

The tripwire tree-walk is recursive, mirroring the compiler's recursion over `Formula`. A helper `_walk_formula(f: Formula, visitor)` handles this; both tripwires use it.

### 2.3 System prompt

`prompts/extraction_system.txt`: under 1000 tokens. Describes the schema neutrally. No reasoning steps. No soft hedges. No commentary on design rationale. Points to examples as the authoritative pattern.

The prompt must explicitly describe the four `Formula` cases, since the LLM has to choose between them correctly. Keep this part terse — a schema fragment and one-sentence descriptions suffice; examples carry the detailed pattern-matching burden.

### 2.4 Few-shot examples

`prompts/extraction_examples.json`: exactly fourteen examples covering all four Formula cases and their common combinations:

1. **Atomic** — "Miroslav Venhoda was a Czech choral conductor." (bare atomic at top level)
2. **Atomic with binary relation** — "Alice taught Bob."
3. **Simple universal** — "All dogs are mammals." (top-level `quantification`)
4. **Restricted universal (the bug-killer)** — "All employees who schedule meetings attend the company building." (top-level `quantification` with populated restrictor)
5. **Existential** — "Some student read a book." (top-level `quantification`, existential)
6. **Nested universal** — "Every student who takes a class that is taught by a professor passes."
7. **"No X is Y"** — "No dog is a cat." (universal with single negated atom in nucleus)
8. **"Only X are Y"** — "Only managers attend the meeting."
9. **Connective-and** — "Alice is tall and Bob is short." (top-level `connective=and`)
10. **Connective-or** — "The L-2021 monitor is either used in the library or has a type-c port." (top-level `connective=or`)
11. **Connective-implies** — "If it rains, the ground is wet." (top-level `connective=implies`)
12. **Connective-iff** — "Archie can walk if and only if he has functional brainstems." (top-level `connective=iff`)
13. **Sentential conditional with quantifier consequent** — "If the forecast calls for rain, then all employees work from home." (top-level `connective=implies`, consequent is `quantification`)
14. **Negation of a compound** — "It is not the case that Alice is tall and Bob is short." (top-level `negation` containing a `connective=and`)

All examples use `"type": "entity"` uniformly. No `"person"`, `"animal"`, `"place"`. Types are grammatical, not ontological.

### 2.5 Tests required

- `test_pre_analyzer.py`: at least two positive and two negative cases for each of the two flags.
- `test_extractor.py`: mocked-LLM tests for validation failure with retry, tripwire failure with retry, both retries failing raises to caller. One mocked test per Formula case confirming the tripwire correctly walks the tree (a negation buried inside a connective should satisfy `requires_negation`).
- `test_extraction_roundtrip.py`: live LLM test, parametrized over all fourteen examples, marked `@pytest.mark.requires_llm`. Every example must round-trip — its extraction from the live LLM must be semantically equivalent to the gold extraction, judged by: same predicates modulo renaming, same `Formula` tree structure modulo commutativity of `and`/`or`.

**Gate:**

- All mocked tests pass.
- Live round-trip test passes 14/14 examples when run with `OPENAI_API_KEY` set. If this drops below 12/14, iterate on the prompt or examples before proceeding; do not loosen the equivalence check.
- Manual smoke test: `python -m siv extract "All employees who schedule meetings attend the company building."` returns an extraction with a populated restrictor containing the Schedule atom.

**Explicit non-goals for Phase 2:**

- No out-of-scope handling. If the LLM returns an extraction for a modal sentence, the extraction is processed like any other; SIV does not classify scope.
- No contrastive generator. No scorer. No invariants.

---

## Phase 3 — Contrastive generator and scorer

**Goal:** Implement the mutation-based contrastive generator (`§4.5`) with Vampire filtering, and the scorer that produces the F1 metric (`§4.6`).

**Scope:**

- `siv/contrastive_generator.py` — new file.
- `siv/scorer.py` — new file.
- `siv/vampire_interface.py` — already exists from v1; confirm or update its contract to `(fol_a: str, fol_b: str, check: Literal["unsat", "entails"]) -> Literal["sat", "unsat", "timeout", "unknown"]`.
- `tests/test_contrastive_generator.py`, `tests/test_scorer.py` — new.

**What to implement:**

### 3.1 Mutation operators

Six operators in `contrastive_generator.py`. Each is a tree-walker over `Formula` — it recurses over the formula structure and emits mutants at every applicable node.

1. **`negate_atom`**: for each atomic formula encountered in the tree, produce a mutant with that atom's `negated` flag flipped.
2. **`swap_binary_args`**: for each binary atomic formula, produce the arg-swapped variant.
3. **`flip_quantifier`**: for each quantification node, produce a mutant with its quantifier flipped.
4. **`drop_restrictor_conjunct`**: for each quantification with a non-empty restrictor, produce mutants each removing one restrictor atom.
5. **`flip_connective`**: for each connective node, produce mutants with `and ↔ or`, `implies → iff`, `iff → implies` (swapping implies operands for the asymmetric case).
6. **`replace_subformula_with_negation`**: for each non-root non-atomic sub-formula, produce a mutant wrapping that sub-formula in `Formula.negation`.

Each operator produces a list of `SentenceExtraction` mutants, each carrying a `mutation_kind: str` field for telemetry.

### 3.2 Vampire-filtered acceptance

`generate_contrastives(extraction, timeout_s=5) -> tuple[list[UnitTest], TelemetryDict]`. For each mutant:

1. Compile the mutant via `compile_canonical_fol`.
2. Compile the original via `compile_canonical_fol`.
3. Ask Vampire whether `(original ∧ mutant)` is unsat.
4. Accept only on `unsat`. Drop on `sat`, `timeout`, or `unknown`.

Telemetry dict: `generated`, `accepted`, `dropped_neutral`, `dropped_unknown`, `unknown_rate`, `per_operator` breakdown.

Wire `generate_contrastives` into `compile_sentence_test_suite` from Phase 1 so the returned `TestSuite` has a populated negatives list.

### 3.3 Scorer

`scorer.py::score(test_suite, candidate_fol) -> ScoreReport`:

- For each positive test: Vampire-check whether candidate entails it.
- For each contrastive test: Vampire-check whether candidate entails it (it should not).
- Compute recall, precision, F1.
- No coverage fraction. No adjustment.
- Return a `ScoreReport` dataclass with `recall`, `precision`, `f1`, `positives_entailed`, `positives_total`, `contrastives_rejected`, `contrastives_total`, `per_test_results`.

### 3.4 Tests required

- For each mutation operator: a test that confirms its output is structurally as specified. The tree-walking semantics matter: a negation operator applied to `(A and B)` should produce three mutants (negate A, negate B, or negate the whole conjunction), not just one.
- A test that `swap_binary_args` on a symmetric predicate (e.g., a `sibling` relation) produces a mutant that Vampire correctly rejects as neutral.
- A test that `swap_binary_args` on an asymmetric predicate (e.g., `Schedule(person, event)`) produces a mutant Vampire accepts as contrastive.
- A test that `flip_connective` on a disjunction produces a conjunction that Vampire confirms as inconsistent with the original in at least one evaluated model context.
- A test that `generate_contrastives` for each of the fourteen Phase 2 examples produces a non-empty, all-unsat-verified negative set. This is fourteen tests, one per example.
- Scorer tests: perfect candidate gives F1=1.0; candidate missing a positive gives the expected recall drop; candidate entailing a contrastive gives the expected precision drop.

**Gate:**

- All tests pass.
- Telemetry on the fourteen Phase 2 examples shows `unknown_rate < 0.2` and `accepted / generated > 0.3`. If either fails, investigate before proceeding — this indicates either Vampire issues or overly-permissive operators.
- The employees-meetings test suite has both populated positives and populated contrastives, and the canonical FOL scores 1.0 on its own test suite.

**Explicit non-goals for Phase 3:**

- No CI invariant harness. That's Phase 4.
- No FOLIO-scale evaluation. That's Phase 5.

---

## Phase 4 — Soundness invariants in CI

**Goal:** Enforce soundness mechanically on every build (`§4.7`).

**Scope:**

- `siv/invariants.py` — add two functions.
- `tests/test_soundness_invariants.py` — new file.
- `tests/data/invariant_corpus.json` — new file, curated sentences.
- CI configuration — ensure the invariant tests run on every PR.

**What to implement:**

### 4.1 Invariants

1. `check_entailment_monotonicity(extraction, test_suite) -> tuple[bool, Optional[str]]`:
   - Let `P` = conjunction of positive tests.
   - Let `Q` = `compile_canonical_fol(extraction)`.
   - Use Vampire to check both `P ⊨ Q` and `Q ⊨ P`.
   - Return `(False, reason)` if either direction fails or times out.

2. `check_contrastive_soundness(test_suite) -> tuple[bool, Optional[str]]`:
   - Let `P` = conjunction of positives.
   - For each contrastive `C`: check `(P ∧ C)` is unsat via Vampire.
   - Return `(False, reason)` on the first failure.

### 4.2 Invariant corpus

`tests/data/invariant_corpus.json`: the fourteen examples from Phase 2 plus at least eight additional hand-curated in-scope sentences that exercise patterns the examples don't cover. Required additional patterns:

- Nested quantification with both universal and existential at different scopes.
- Connective containing a quantification that itself contains a connective. ("If it rains, then every employee who is remote and every employee who is in-person works from home.")
- Disjunction with three operands.
- Deeply nested negations (triple-negation or negation-of-implication).
- A biconditional between two quantified statements.
- A ground fact expressed as an atomic formula with two constants.
- A universal whose nucleus is a disjunction.
- A universal whose restrictor draws from an inner existential that itself contains a connective.

The corpus is the authoritative test of "does the whole pipeline handle all of Frege's grammar." If any of these cases fails, a Formula case or a compiler rule is broken.

### 4.3 Tests required

- All invariant tests pass on the curated corpus.
- A deliberately-broken test: modify the compiler in a test-only way to produce a subtly-wrong positive (e.g., off-by-one universe) and confirm the monotonicity invariant catches it. Restore afterward. This proves the invariant is actually load-bearing, not trivially satisfied.

**Gate:**

- All invariant tests green on the full twenty-two-sentence corpus.
- CI configured and verified to fail the build on invariant violation (test with a throwaway branch containing an intentional bug).

---

## Phase 5 — FOLIO validation

**Goal:** Measure how well the system handles real FOLIO premises. This is the empirical validation that underwrites the paper's claims.

**Scope:**

- `scripts/run_folio_evaluation.py` — new.
- `reports/folio_agreement.json` — new output.

**What to implement:**

1. Load the public FOLIO dataset.
2. For each premise, run the SIV pipeline end-to-end: extract, compile, generate contrastives, score against FOLIO's gold FOL as the candidate.
3. Aggregate: mean F1 across all premises, distribution of F1, per-Formula-case breakdown (how does F1 differ between atomic, quantification, connective, and negation cases?), premises where F1 < 0.5 (manual review list), premises where extraction failed (manual review list).
4. Write `reports/folio_agreement.json` with the aggregates.

**Gate:**

- Script runs to completion on the full FOLIO dataset (300 premises).
- Mean F1 on the employees-meetings class of sentences (universal-with-restrictive-relative) is ≥ 0.85. This is the headline empirical claim: the system correctly handles the v1 bug class.
- Mean F1 on atomic (ground) predications is ≥ 0.90. This class is trivially easy in principle; if it's below 0.90, something is wrong with the atomic code path.
- Mean F1 on connective-only sentences is ≥ 0.80. These should be straightforward for a recursive compiler; below 0.80 means the LLM extraction isn't handling booleans well and the few-shot needs more connective coverage.
- Extraction failure rate is documented and manually reviewed; failures are categorized as either real sentences SIV cannot handle (user-scope issue) or bugs to fix (actionable).

**Explicit non-goals for Phase 5:**

- No coverage fraction reporting. The score is the score.
- No claim about sentences outside the FOL-translatable class. If a premise is genuinely modal or proportional, the F1 reported is whatever it is, with no commentary.

---

## Phase 6 — Cleanup and release

**Goal:** Remove any v1 remnants, finalize documentation, tag the release.

**Scope:**

- Anything in `siv/` that isn't on the dependency list from `SIV_Master_Document.md §6`.
- `README.md` — rewrite to match the new architecture.
- `CHANGELOG.md` — write the v2.0.0 entry.

**What to do:**

1. `git grep` for forbidden or obsolete terms: `MacroTemplate`, `macro_template`, `universal_affirmative`, `Fact`, `is_fol_expressible`, `rejection_reason`, `FOLRejectionReason`, `rejection_note`, `coverage_fraction`, `is_collective`, `detected_modal`, `detected_temporal`, `detected_proportional`. If any match is not in `docs/archive/`, delete it.
2. Rewrite `README.md` with a new quick-start reflecting the seven-component architecture. Include a minimal working example covering all four Formula cases.
3. Write `CHANGELOG.md` entry for v2.0.0: a concise list of what changed, what was removed, and the empirical result from Phase 5.
4. Tag the release `v2.0.0`.

**Gate:**

- `git grep` on the forbidden terms returns zero matches outside `docs/archive/`.
- README quick-start copy-pastes and runs end to end.
- Full test suite green, including slow invariant tests.

---

## Summary table

| Phase | Implements | Touches | Gate |
|-------|-----------|---------|------|
| 0 | Revert + docs | `docs/`, `reports/archive/` | Repo at v1-final + three docs |
| 1 | Schema (`Formula` + tripartite) + recursive compiler | `schema.py`, `compiler.py`, `json_schema.py` | 9 Formula-case tests pass; two-path equivalence via Vampire |
| 2 | Pre-analyzer + extractor + prompts | `pre_analyzer.py`, `extractor.py`, `prompts/` | Live round-trip ≥ 12/14 |
| 3 | Contrastive + scorer | `contrastive_generator.py`, `scorer.py` | Telemetry thresholds met on 14 examples |
| 4 | Invariants in CI | `invariants.py`, CI config | Invariants green on 22-sentence corpus; deliberate-bug test catches it |
| 5 | FOLIO validation | `scripts/run_folio_evaluation.py` | F1 ≥ 0.85 on target class; per-Formula-case breakdown reported |
| 6 | Cleanup + release | README, CHANGELOG | Forbidden grep returns zero |

Each phase is reviewable in isolation. Each gate is an objective check, not a judgment call. Do not skip phases, and do not merge a phase until its gate passes.

---

## If something goes wrong mid-refactor

**A phase's gate fails.** Stop. Do not merge. Diagnose. The gate is there because passing it is the minimum bar for the phase's correctness; missing it means the phase is not ready, and proceeding compounds the issue.

**A new drift issue surfaces.** Audit before patching. The pattern of drift is always "two components disagree about a concept and nothing checks that they agree." The fix is always "make one of them the source of truth and derive or verify the other from it." Do not resolve drift case-by-case.

**A forbidden concept feels necessary.** It isn't. If you genuinely believe it is, update `SIV_Philosophy.md §9` first (with a written rationale) and only then adjust the plan. The forbidden list is load-bearing; working around it by "just this once" is how scope creep re-enters.

**A sentence appears to need a fifth Formula case.** It doesn't. Frege's grammar is closed. The sentence is either expressible in the four existing cases (atomic, quantification, negation, connective) or it is outside FOL. If the expression requires creativity — e.g., "only X are Y" as `∀x.(Y(x) → X(x))` rather than as a new "only" construct — that creativity is the extractor's job, not the schema's.

**A phase turns out larger than anticipated.** Split it. A phase should be one reviewable commit. If it isn't, the phase is actually two phases and you should update this document and review the new split before proceeding.

**The `Formula` recursion is producing too many contrastive mutants.** That is expected for deeply nested sentences and is the right behavior — every sub-formula is a legitimate mutation target. If compute becomes a concern, cap the generator at a fixed number of mutants per sentence (e.g., 50) and log the cap hit; do not silently drop operators or restrict the tree walk.
