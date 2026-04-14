# SIV v2 Development Spec

## Preamble

This document refactors SIV from its v1 state to the v2 architecture via seven sequential phases. Each phase below is a single prompt block to be copy-pasted verbatim into a Claude Code session. The document is self-contained: the coding agent receives only this file plus `docs/SIV_Philosophy.md`, `docs/SIV_Master_Document.md`, and `docs/SIV_Refactor_Plan.md` (hereafter "the three architecture documents"), and the v1 codebase.

### Ground rules (lifted from `docs/SIV_Refactor_Plan.md` "Ground rules" and `docs/SIV_Philosophy.md §9`)

1. Every change references a specific section of `SIV_Master_Document.md` or `SIV_Philosophy.md`. Changes that do not trace to either document are out of scope.
2. One phase, one commit, one review gate. A phase does not merge until its gate is green.
3. Pydantic models are the source of truth for all schemas. The JSON Schema passed to the LLM is derived from the Pydantic model. Hand-rolled JSON Schemas are forbidden.
4. Forbidden concepts stay forbidden. `SIV_Philosophy.md §9` is the canonical negative list. No phase introduces anything on it.
5. Rename cleanly, never alias. If a symbol is renamed, every call site is updated in the same commit. No `X = Y` backward-compatibility aliases.
6. Failing tests are information. Do not loosen assertions to pass tests; fix the underlying issue or escalate.
7. The `Formula` type is the complete grammar. FOL's grammar is closed — Frege's five constructs are atomic predications, boolean connectives (AND, OR, NOT, IMPLIES, IFF), quantifiers (∀, ∃), variables, and constants, and nothing else. The `Formula` type represents exactly this closed grammar via four cases (`atomic`, `quantification`, `negation`, `connective`); variables and constants are carried in `Entity`/`Constant` declarations and referenced by atom args. No fifth `Formula` case is ever added. If a sentence appears to require one, it is either expressible in the four existing cases or outside FOL and therefore outside SIV.

### How to use the three architecture documents

At the start of each phase, read the specific sections cited in that phase's prompt — not the whole document. Cite sections when justifying implementation choices. Never contradict the architecture documents; if the prompt and a document appear to conflict, stop and surface the conflict.

### Escalation rule (applies to every phase)

If anything in a phase prompt contradicts the architecture documents, or a required implementation choice is ambiguous, or an exact token (enum value, field name, file path, function name) cannot be confirmed against the source documents or v1 codebase — **stop and surface the contradiction or ambiguity to the user before proceeding.** Do not guess. Do not loosen requirements to get unstuck. This was the primary failure mode of the previous refactor.

Each phase commits once and gates once. Do not merge a phase until its gate passes. Do not merge two phases into one commit. Do not invent phases, forbidden concepts, or cleanup steps not listed in `docs/SIV_Refactor_Plan.md`.

---

## Contracts

The following contracts are the shared interface reference across all phases. A contract specifies a load-bearing component's signature, preconditions, postconditions, error modes, and invariants. Phase prompts reference these by name.

### C0. `UnitTest` and `TestSuite`

```python
class UnitTest(BaseModel):
    fol: str                       # NLTK-compatible ASCII FOL
    kind: Literal["positive", "contrastive"]
    mutation_kind: Optional[str] = None   # set iff kind == "contrastive";
                                          # one of the six operator names in C7

class TestSuite(BaseModel):
    extraction: SentenceExtraction
    positives: List[UnitTest] = []
    contrastives: List[UnitTest] = []
```

- **Invariant:** `UnitTest.mutation_kind` is non-`None` iff `UnitTest.kind == "contrastive"`. Positive tests never carry a `mutation_kind`.
- **Invariant:** every `UnitTest.fol` string is NLTK-compatible ASCII FOL, emitted by `compile_canonical_fol` or `compile_sentence_test_suite`.
- **Declared in `siv/schema.py`** alongside the other models in C1 and C2. Declared in Phase 1.

### C1. `Formula`

```python
class Formula(BaseModel):
    atomic: Optional[AtomicFormula] = None
    quantification: Optional[TripartiteQuantification] = None
    negation: Optional["Formula"] = None
    connective: Optional[Literal["and", "or", "implies", "iff"]] = None
    operands: Optional[List["Formula"]] = None
```

- **Invariant (exclusivity):** exactly one of `atomic`, `quantification`, `negation`, or `(connective, operands)` is populated per instance. `connective` and `operands` are populated together as a single case.
- **Invariant (recursion):** `negation`, `operands` elements, and `TripartiteQuantification.nucleus` are themselves `Formula` instances; nesting depth is unbounded.
- **Validator behavior:** raises `SchemaViolation` on: zero cases populated; two or more cases populated; `connective` without `operands`; `operands` without `connective`; `implies`/`iff` with `len(operands) != 2`; `and`/`or` with `len(operands) < 2`.
- **No fifth case.** The four cases are exhaustive per `SIV_Master_Document.md §4.2.2` and `SIV_Philosophy.md §9`.

### C2. `SentenceExtraction`

```python
class SentenceExtraction(BaseModel):
    nl: str
    predicates: List[PredicateDecl] = []
    entities: List[Entity] = []
    constants: List[Constant] = []
    formula: Formula
```

- **Required fields:** `nl` (source sentence) and `formula` (root of the logical content).
- **Predicate-atom invariant:** every `AtomicFormula.pred` appearing anywhere in the `formula` tree must match the `name` of some `PredicateDecl` in `predicates`, and its `args` length must equal that `PredicateDecl.arity`.
- **Argument-resolution invariant:** every string in an `AtomicFormula.args` list must resolve to either (a) a declared `Entity.id` or `Constant.id`, or (b) a variable bound by an enclosing `TripartiteQuantification` or `InnerQuantification`.
- **Per `SIV_Master_Document.md §4.2.1`.** No `is_fol_expressible`, `rejection_reason`, or `rejection_note` field.

### C3. `validate_extraction`

```python
def validate_extraction(extraction: SentenceExtraction) -> None: ...
```

- **Input:** a parsed `SentenceExtraction`.
- **Returns:** `None` on success.
- **Raises:** `SchemaViolation` on any violation enumerated in `docs/SIV_Refactor_Plan.md §1.2` (Formula exclusivity, connective/operand arity, predicate resolution, arity mismatch, unresolved argument, degenerate quantification).
- **Deterministic:** same input yields same result; no randomness, no LLM calls, no network.

### C4. `compute_required_features`

```python
def compute_required_features(sentence: str) -> RequiredFeatures: ...

@dataclass(frozen=True)
class RequiredFeatures:
    requires_restrictor: bool
    requires_negation: bool
```

- **Input:** a natural language sentence string.
- **Output:** a frozen `RequiredFeatures` with exactly two `bool` fields and no others.
- **Deterministic:** same sentence yields same result. No LLM call. No network call.
- **Per `SIV_Master_Document.md §4.1`.** Detection rules are fixed in `docs/SIV_Refactor_Plan.md §2.1`.
- **Forbidden fields:** no modal, temporal, proportional, collective, or ontological-type flags.

### C5. `extract_sentence`

```python
def extract_sentence(sentence: str, client) -> SentenceExtraction: ...
```

- **Input:** a sentence and a frozen LLM client.
- **Output:** a validated `SentenceExtraction` that satisfies C2 and C3 and passes both tripwires.
- **Retry behavior:** at most one retry on `SchemaViolation` from either `validate_extraction` or tripwire enforcement; the violation message is appended to the prompt on retry. No second retry.
- **Error modes:** raises `SchemaViolation` to the caller if the retry also fails. Never returns a silently-broken extraction. No infinite retry loop.
- **Tripwires per `SIV_Master_Document.md §4.3`:** if `requires_restrictor`, the formula tree must contain at least one `TripartiteQuantification` with a non-empty `restrictor`; if `requires_negation`, the formula tree must contain at least one negation occurrence (a `Formula.negation` node or an `AtomicFormula` with `negated=True`, anywhere in the tree including inside connectives).

### C6. `compile_sentence_test_suite` and `compile_canonical_fol`

```python
def compile_sentence_test_suite(extraction: SentenceExtraction) -> TestSuite: ...
def compile_canonical_fol(extraction: SentenceExtraction) -> str: ...
```

- **Structurally distinct code paths:** different traversal order, different variable-naming scheme, different string-assembly. A bug in one must not silently propagate to the other. Per `SIV_Master_Document.md §4.4`.
- **Recursion:** both recurse over the four `Formula` cases using the rules in `SIV_Master_Document.md §4.4` and `docs/SIV_Refactor_Plan.md §1.4`.
- **Output format:** NLTK-compatible ASCII FOL — `all x.(P(x) -> Q(x))`, `exists x.(P(x) & Q(x))`, `-P(x)`, `(A & B)`, `(A | B)`, `(A -> B)`, `(A <-> B)`.
- **Bidirectional entailment invariant:** for every extraction, the conjunction of `compile_sentence_test_suite`'s positive tests must be bidirectionally entailing with `compile_canonical_fol`'s output under Vampire. Enforced by C9.
- **`compile_sentence_test_suite`** emits the full canonical FOL as one positive test plus a sub-entailment test for each non-trivial sub-formula node. A **non-trivial sub-formula** is any `Formula` node in the tree that is *not* a bare `AtomicFormula` leaf already present as an argument to a parent connective or quantification — i.e. every `quantification`, `negation`, and `connective` node, plus every atomic node reachable as a top-level conjunct of a restrictor or as the top-level nucleus atom. The purpose is to make each compound claim independently checkable without flooding the suite with redundant leaf-atom tests.

### C7. `generate_contrastives`

```python
def generate_contrastives(
    extraction: SentenceExtraction,
    timeout_s: int = 5,
) -> tuple[list[UnitTest], TelemetryDict]: ...
```

- **Input:** a validated `SentenceExtraction` and a per-mutant Vampire timeout.
- **Output:** a list of accepted contrastive `UnitTest`s plus a telemetry dict with keys `generated`, `accepted`, `dropped_neutral`, `dropped_unknown`, `unknown_rate`, `per_operator`.
- **Operators (exactly six, per `SIV_Master_Document.md §4.5`):** `negate_atom`, `swap_binary_args`, `flip_quantifier`, `drop_restrictor_conjunct`, `flip_connective`, `replace_subformula_with_negation`. Each is a tree-walker emitting mutants at every applicable node.
- **Acceptance rule:** a mutant is accepted iff Vampire proves `(original ∧ mutant)` is `unsat`.
- **Drop rule:** any mutant whose Vampire result is `sat`, `timeout`, or `unknown` is dropped.
- **Every accepted contrastive is provably inconsistent with the original.** Not merely different.

### C8. `score`

```python
def score(test_suite: TestSuite, candidate_fol: str) -> ScoreReport: ...

@dataclass
class ScoreReport:
    recall: float
    precision: float
    f1: float
    positives_entailed: int
    positives_total: int
    contrastives_rejected: int
    contrastives_total: int
    per_test_results: list
```

- **Computation per `SIV_Master_Document.md §4.6`:** `recall = positives_entailed / positives_total`; `precision = contrastives_rejected / contrastives_total`; `f1 = 2·recall·precision / (recall + precision)`.
- **Does not return a coverage fraction.** No scope-adjustment term. Per `SIV_Philosophy.md §9`.
- **Uses Vampire** to check each positive (should entail) and each contrastive (should not entail).

### C9. Soundness invariants

Two CI-level functions, both per `SIV_Master_Document.md §4.7`.

#### C9a. `check_entailment_monotonicity`

```python
def check_entailment_monotonicity(
    extraction: SentenceExtraction,
    test_suite: TestSuite,
) -> tuple[bool, Optional[str]]: ...
```

- **Semantics:** with `P` = conjunction of `test_suite`'s positive tests and `Q` = `compile_canonical_fol(extraction)`, Vampire-check both `P ⊨ Q` and `Q ⊨ P`.
- **Returns `(True, None)`** iff both directions are proved.
- **Returns `(False, reason)`** if either direction fails, times out, or returns unknown. Timeout is a failure, not a skip.

#### C9b. `check_contrastive_soundness`

```python
def check_contrastive_soundness(
    test_suite: TestSuite,
) -> tuple[bool, Optional[str]]: ...
```

- **Semantics:** with `P` = conjunction of positives, for each contrastive `C` in the suite, Vampire-check that `(P ∧ C)` is `unsat`.
- **Returns `(True, None)`** iff every contrastive is unsat against the positives.
- **Returns `(False, reason)`** on the first `C` that is `sat`, `timeout`, or `unknown`. Timeout is a failure, not a skip.

---

## Phase 0 prompt

```
You are executing Phase 0 of the SIV v2 refactor.

Before doing anything, read the following in full:
- docs/SIV_Refactor_Plan.md — "Ground rules" section and the "Phase 0 — Revert and capture" section.
- docs/SIV_Philosophy.md §9 (the forbidden concepts list).

Goal: Return the repository to the last clean v1 state, with the new architecture documents in place as the specification for everything that follows.

Files touched:
- Create branch: v2-from-clean.
- Create tag: v1-final.
- Create: docs/SIV_Philosophy.md, docs/SIV_Master_Document.md, docs/SIV_Refactor_Plan.md.
- Move (if they exist from the archived v2 branch): baseline_audit.csv, baseline_audit_summary.json, drift_audit.md, compiler_state_audit.md → reports/archive/.
- Move (if exists): the v1 master document → docs/archive/v1_master_document.md.
- Delete from repo root: any v2-era plan files whose filenames contain "Phase", "Refactor", or similar, and that are not one of the three documents named above.

What to do:
1. Identify the last git commit where v1 was clean, before any v2 refactor work began. Tag that commit v1-final.
2. Create branch v2-from-clean from v1-final. All subsequent phases commit to this branch. Archive, do not delete, the existing partially-migrated v2 branch.
3. Copy the three architecture documents into docs/ on the new branch:
   - docs/SIV_Philosophy.md
   - docs/SIV_Master_Document.md
   - docs/SIV_Refactor_Plan.md
4. If a v1 master document exists in the repo, move it to docs/archive/v1_master_document.md. Do not delete it.
5. Move the following audit files from the archived v2 branch into reports/archive/ on v2-from-clean: baseline_audit.csv, baseline_audit_summary.json, drift_audit.md, compiler_state_audit.md. Preserve them as measurements of v1 behavior.
6. Delete any stale v2-era plan files from the repo root. Only the three documents in docs/ are allowed to describe v2.

Forbidden moves:
- Do not modify any code in siv/ or tests/ during this phase. Phase 0 is revert plus docs only.
- Do not introduce any files outside those listed above.
- Do not add anything from the SIV_Philosophy.md §9 forbidden list to any file in the repo.

Tests required: no new tests. The existing v1 test suite must continue to pass unmodified.

Gate:
- The repo is at v1-final plus three documentation files (and any moved audit files under reports/archive/).
- Running the existing v1 test suite passes.
- `git log --oneline` shows only v1 history plus the documentation commit.

If anything in this prompt contradicts the architecture documents, stop and surface the contradiction. If a required implementation choice is ambiguous, stop and ask. Do not guess and do not loosen requirements to get unstuck.
```

---

## Phase 1 prompt

```
You are executing Phase 1 of the SIV v2 refactor. The codebase is at the state Phase 0 left it in: v1-final plus docs/.

Before writing any code, read the following in full:
- docs/SIV_Master_Document.md §4.2 (Schema), §4.4 (Compiler), §4.7 (Soundness invariants — for context on the two-path requirement).
- docs/SIV_Refactor_Plan.md "Phase 1 — Schema and compiler" section in full.
- docs/SIV_Philosophy.md §9 (forbidden concepts).

Also consult Contracts C0, C1, C2, C3, and C6 in SIV_v2_Development_Spec.md.

Goal: Implement the Formula-based schema (§4.2) and the recursive two-path compiler (§4.4). This is the foundational change; everything else builds on it.

Files touched:
- siv/schema.py — full rewrite.
- siv/compiler.py — full rewrite.
- siv/json_schema.py — NEW file; derives API-level JSON Schema from the Pydantic model.
- tests/test_schema.py — full rewrite.
- tests/test_compiler.py — full rewrite.
- Everything else in siv/ — LEFT ALONE. Modules in siv/ that import the old schema or compiler WILL BREAK after this commit. This is expected. Those modules (pre_analyzer, extractor, contrastive_generator, scorer, invariants, frozen_client) are fixed in Phases 2, 3, and 4. Do not patch them here.

What to implement:

1.1 — The Formula type and related models, exactly as follows (do not rename, do not add fields, do not reorder semantics):

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

Forward references require model_rebuild() calls at module bottom.

Also declare UnitTest and TestSuite in siv/schema.py per Contract C0:

class UnitTest(BaseModel):
    fol: str
    kind: Literal["positive", "contrastive"]
    mutation_kind: Optional[str] = None

class TestSuite(BaseModel):
    extraction: SentenceExtraction
    positives: List[UnitTest] = []
    contrastives: List[UnitTest] = []

Enforce the C0 invariant that UnitTest.mutation_kind is non-None iff UnitTest.kind == "contrastive" via a Pydantic model_validator on UnitTest.

1.2 — Validation. Implement validate_extraction(extraction: SentenceExtraction) -> None raising SchemaViolation for any of:
- A Formula with zero or more than one of its four cases populated.
- A Formula with connective populated but operands empty, missing, or of arity not matching the connective (implies/iff are binary; and/or are n-ary with at least two operands).
- A Formula with operands populated but connective absent.
- An AtomicFormula whose pred does not match a declared PredicateDecl.name.
- An AtomicFormula whose args length differs from the referenced predicate's arity.
- An AtomicFormula whose arg references a variable or constant not in scope (variables in scope within the quantification that binds them; constants in scope globally).
- A TripartiteQuantification with an empty restrictor AND whose nucleus consists of a single atom over the bound variable.

1.3 — JSON Schema derivation. Implement siv/json_schema.py::derive_extraction_schema() -> dict returning the OpenAI-compatible JSON Schema derived from SentenceExtraction.model_json_schema(). The derivation must:
- Inline all $ref / $defs (OpenAI strict mode requirement).
- Set additionalProperties: false on every object.
- Mark every property as required (express null via union types).
- Strip title, description, default.

This function is the single API-level schema. No hand-rolled JSON Schema is permitted anywhere in the codebase.

1.4 — Recursive compiler. Two entry points in siv/compiler.py:

- compile_sentence_test_suite(extraction) -> TestSuite emits positive tests. The full canonical FOL is one positive test; each non-trivial sub-formula also emits its own entailment test.
- compile_canonical_fol(extraction) -> str emits a single canonical FOL formula.

Both are recursive over Formula with the following skeleton:

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

Compilation rules per docs/SIV_Master_Document.md §4.4:
- Atomic → Pred(args...) or -Pred(args...) if negated.
- Negation → -(<compiled operand>).
- Connective and → operands joined with &.
- Connective or → operands joined with |.
- Connective implies → (A -> B) where implies/iff are binary.
- Connective iff → (A <-> B).
- Quantification universal → all x.(⋀restrictor -> compile(nucleus)).
- Quantification existential → exists x.(⋀restrictor & compile(nucleus)).

Inner quantifications on a TripartiteQuantification (§4.2.3 of the master document):
- Each InnerQuantification declared on the enclosing TripartiteQuantification introduces a variable bound inside the restrictor's scope. Emit each InnerQuantification as a quantifier wrapping the restrictor conjunction, in declaration order, innermost-last. For an InnerQuantification with quantifier="existential", variable=y, on a universal quantification over x with restrictor R and nucleus N, emit:
    all x.(exists y.(⋀R) -> compile(N))
  For an InnerQuantification with quantifier="universal", emit:
    all x.((all y.(⋀R)) -> compile(N))
  (Similarly for an outer existential: exists x.(exists y.(⋀R) & compile(N)).)
- If multiple InnerQuantifications are declared, nest them left-to-right in declaration order: the first declared is the outermost of the inner block, the last declared is innermost adjacent to the restrictor conjunction.
- Restrictor atoms may reference any of the inner variables or the outer bound variable; validation (§1.2) already enforces that every atom arg resolves in scope, where inner-quantification variables are in scope within the restrictor.
- If the InnerQuantification semantics for a given sentence appear to require a different scoping than above — for instance, an inner quantifier whose scope must extend into the nucleus rather than stay inside the restrictor — stop and surface the ambiguity rather than guessing; the master document specifies inner quantifications as scoped inside the restrictor only, and the nucleus handles its own quantifications via its full Formula structure.

The two entry points must be structurally distinct code paths: different traversal order, different variable-naming scheme, different string-assembly. A bug in one must not silently propagate to the other.

NLTK-compatible ASCII output only: all x.(P(x) -> Q(x)), exists x.(P(x) & Q(x)), -P(x), (A & B), (A | B), (A -> B), (A <-> B).

Forbidden moves (from SIV_Philosophy.md §9 and SIV_Master_Document.md Appendix):
- Do not add an is_fol_expressible field.
- Do not add a rejection_reason, rejection_note, or FOLRejectionReason enum.
- Do not add a coverage_fraction field.
- Do not add is_collective, detected_modal, detected_temporal, or detected_proportional fields.
- Do not add ontological type values (person, animal, place) to Entity.type or Constant.type; type is grammatical.
- Do not hand-roll any JSON Schema; all schemas derive from the Pydantic model.
- Do not introduce backward-compatibility aliases for renamed symbols from v1.
- Do not add a fifth Formula case under any name.

Tests required:

Validation tests in tests/test_schema.py:
- Every validator has positive and negative cases.
- Every SchemaViolation case enumerated in 1.2 has a dedicated test.
- A test that JSON Schema derivation is deterministic across runs (same input yields byte-identical output).

Compilation tests in tests/test_compiler.py — exactly these nine cases:
- Atomic: "Miroslav Venhoda was a Czech choral conductor" → CzechChoralConductor(miroslav).
- Quantification (the employees-meetings bug-killer): "All employees who schedule meetings attend the company building" → all x.(Employee(x) & exists y.(Meeting(y) & Schedule(x, y)) -> exists z.(CompanyBuilding(z) & Attend(x, z))) or semantic equivalent with populated restrictor on the left of the implication.
- Negation: "Smith is not a Czech conductor" → -CzechConductor(smith).
- Connective-and: "Alice is tall and Bob is short" → (Tall(alice) & Short(bob)).
- Connective-or: "The L-2021 monitor is either used in the library or has a type-c port" → (UsedIn(monitor, library) | HasTypeC(monitor)) (with appropriate atomic decomposition).
- Connective-implies: "If it rains, then the ground is wet" → (Rains() -> Wet(ground)).
- Connective-iff: "Archie can walk if and only if he has functional brainstems" → (CanWalk(archie) <-> HasFunctionalBrainstems(archie)).
- Nested case: "If a legislator is found guilty, they will be suspended" → all x.(Legislator(x) -> (exists y.(Theft(y) & FoundGuilty(x, y)) -> Suspended(x))) or semantic equivalent.
- Quantifier in connective: "If the forecast calls for rain, then all employees work from home" — top-level connective=implies whose antecedent is an atomic formula and whose consequent is a quantification. Expected FOL semantic shape: (ForecastRain() -> all x.(Employee(x) -> WorkFromHome(x))) or semantic equivalent.

Two-path equivalence test: for each of the above, call both compile_sentence_test_suite and compile_canonical_fol on the same extraction, then use Vampire to verify bidirectional entailment of their outputs. This is the live exercise of the §4.7 soundness invariant within Phase 1 tests.

Gate:
- All schema and compiler tests pass.
- All nine Formula-case tests produce correct FOL.
- Vampire-based bidirectional-entailment test passes on every test case.
- Line count of siv/compiler.py is under 400 lines.

Explicit non-goals:
- No extractor, no pre-analyzer, no contrastive generator, no scorer. Later phases.
- No few-shot examples file. Phase 2.

If anything in this prompt contradicts the architecture documents, stop and surface the contradiction. If a required implementation choice is ambiguous, stop and ask. Do not guess and do not loosen requirements to get unstuck.
```

---

## Phase 2 prompt

```
You are executing Phase 2 of the SIV v2 refactor. The codebase is at the state Phase 1 left it in: new schema and compiler in place; pre_analyzer, extractor, frozen_client, contrastive_generator, scorer, and invariants are broken because they import the old schema.

Before writing any code, read:
- docs/SIV_Master_Document.md §4.1 (Pre-analyzer) and §4.3 (Extractor).
- docs/SIV_Refactor_Plan.md "Phase 2 — Pre-analyzer and extractor" section in full.
- docs/SIV_Philosophy.md §9 (forbidden concepts).

Also consult Contracts C4 and C5 in SIV_v2_Development_Spec.md.

Goal: Implement the deterministic pre-analyzer (§4.1) and the extractor with JSON-schema binding and tripwire enforcement (§4.3).

Files touched:
- siv/pre_analyzer.py — rewrite.
- siv/extractor.py — rewrite.
- siv/frozen_client.py — update the response_format binding to use derive_extraction_schema() from Phase 1.
- prompts/extraction_system.txt — rewrite.
- prompts/extraction_examples.json — rewrite.
- tests/test_pre_analyzer.py, tests/test_extractor.py, tests/test_extraction_roundtrip.py — rewrite or create.
- Other broken modules (contrastive_generator.py, scorer.py, invariants.py) — LEFT ALONE. Fixed in Phases 3 and 4.

What to implement:

2.1 — Pre-analyzer. Implement compute_required_features(sentence: str) -> RequiredFeatures where RequiredFeatures is a frozen dataclass with exactly two fields:

@dataclass(frozen=True)
class RequiredFeatures:
    requires_restrictor: bool
    requires_negation: bool

No other fields. No modal, temporal, proportional, collective, or ontological-type detection. The forbidden list in SIV_Philosophy.md §9 is authoritative.

Detection rules:
- requires_restrictor: any subject-NP token has dep_ == "relcl", OR the sentence matches the regex ^(all|every|each|no|any)\s+\w+\s+(who|that|which)\b (case-insensitive).
- requires_negation: lemma no|none|never|neither appears, OR neg dependency on the main verb.

Deterministic. No LLM call. No network call.

2.2 — Extractor. Implement extract_sentence(sentence, client) -> SentenceExtraction:

- Call the frozen LLM with the system prompt, few-shot examples, and the sentence. Pass the JSON Schema from derive_extraction_schema() as response_format.
- Parse the response into a SentenceExtraction via Pydantic.
- Run validate_extraction from Phase 1.
- Compute RequiredFeatures via compute_required_features and enforce tripwires:
  - If requires_restrictor is True, walk the formula tree looking for at least one TripartiteQuantification with a populated (non-empty) restrictor. If none exists, raise SchemaViolation("restrictor required but missing").
  - If requires_negation is True, walk the formula tree looking for at least one negation occurrence: a Formula.negation node, or an AtomicFormula with negated=True, anywhere in the tree including inside connectives and inside quantification nuclei/restrictors. If none exists, raise SchemaViolation("negation required but missing").
- On any SchemaViolation, retry ONCE with the violation message appended to the system prompt.
- If the retry also fails, raise to caller. No second retry. No infinite loop.

The tripwire tree-walk is recursive, mirroring the compiler's recursion over Formula. Implement a helper _walk_formula(f: Formula, visitor) and use it for both tripwires.

2.3 — System prompt. prompts/extraction_system.txt:
- Under 1000 tokens.
- Describes the schema neutrally.
- No reasoning steps, no soft hedges, no commentary on design rationale.
- Points to the examples as the authoritative pattern.
- Explicitly describes the four Formula cases (atomic, quantification, negation, connective). A schema fragment plus one-sentence descriptions of each case suffices; the examples carry the detailed pattern-matching burden.

2.4 — Few-shot examples. prompts/extraction_examples.json: exactly fourteen examples covering the four Formula cases and their common combinations. These are the fourteen cases:

1. Atomic — "Miroslav Venhoda was a Czech choral conductor."
2. Atomic with binary relation — "Alice taught Bob."
3. Simple universal — "All dogs are mammals." (top-level quantification)
4. Restricted universal (the bug-killer) — "All employees who schedule meetings attend the company building." (top-level quantification with populated restrictor)
5. Existential — "Some student read a book." (top-level quantification, existential)
6. Nested universal — "Every student who takes a class that is taught by a professor passes."
7. "No X is Y" — "No dog is a cat." (universal with single negated atom in nucleus)
8. "Only X are Y" — "Only managers attend the meeting."
9. Connective-and — "Alice is tall and Bob is short." (top-level connective=and)
10. Connective-or — "The L-2021 monitor is either used in the library or has a type-c port." (top-level connective=or)
11. Connective-implies — "If it rains, the ground is wet." (top-level connective=implies)
12. Connective-iff — "Archie can walk if and only if he has functional brainstems." (top-level connective=iff)
13. Sentential conditional with quantifier consequent — "If the forecast calls for rain, then all employees work from home." (top-level connective=implies, consequent is quantification)
14. Negation of a compound — "It is not the case that Alice is tall and Bob is short." (top-level negation containing a connective=and)

All examples use "type": "entity" uniformly. No "person", "animal", or "place" values.

Forbidden moves:
- Do not add any field to RequiredFeatures beyond the two bools named above.
- Do not add any modal, temporal, proportional, or collective detection flags in the pre-analyzer.
- Do not add ontological type values in the examples.
- Do not add an is_fol_expressible, rejection_reason, rejection_note, or FOLRejectionReason enum anywhere.
- Do not add scope classification or out-of-scope handling to the extractor. If the LLM returns an extraction for a modal sentence, the extraction is processed like any other. SIV does not classify scope (SIV_Philosophy.md §2).
- Do not add a second retry, a third retry, or an infinite retry loop.
- Do not hand-roll a JSON Schema; use derive_extraction_schema() from Phase 1.
- Do not introduce backward-compatibility aliases for v1 symbols.

Tests required:

tests/test_pre_analyzer.py:
- At least two positive and two negative cases for each of the two flags (requires_restrictor, requires_negation).

tests/test_extractor.py (mocked LLM):
- Validation failure triggers one retry.
- Tripwire failure (missing restrictor, missing negation) triggers one retry.
- Both retries failing raises SchemaViolation to the caller.
- One test per Formula case confirming the tripwire correctly walks the tree: specifically, a negation buried inside a connective must satisfy requires_negation.

tests/test_extraction_roundtrip.py (live LLM, marked @pytest.mark.requires_llm):
- Parametrized over all fourteen examples above.
- Each example's extraction from the live LLM must be semantically equivalent to the gold extraction: same predicates modulo renaming, same Formula tree structure modulo commutativity of and/or.

Gate:
- All mocked tests pass.
- Live round-trip test passes at least 12/14 examples when run with OPENAI_API_KEY set. If it drops below 12/14, iterate on the prompt or examples before proceeding; do not loosen the equivalence check.
- Manual smoke test: `python -m siv extract "All employees who schedule meetings attend the company building."` returns an extraction whose formula contains a TripartiteQuantification with a populated restrictor containing the Schedule atom.

Explicit non-goals:
- No out-of-scope handling.
- No contrastive generator. No scorer. No invariants. Later phases.

If anything in this prompt contradicts the architecture documents, stop and surface the contradiction. If a required implementation choice is ambiguous, stop and ask. Do not guess and do not loosen requirements to get unstuck.
```

---

## Phase 3 prompt

```
You are executing Phase 3 of the SIV v2 refactor. The codebase is at the state Phase 2 left it in: schema, compiler, pre-analyzer, and extractor are live. contrastive_generator.py, scorer.py, and invariants.py are still broken or stale.

Before writing any code, read:
- docs/SIV_Master_Document.md §4.5 (Contrastive generator) and §4.6 (Scorer).
- docs/SIV_Refactor_Plan.md "Phase 3 — Contrastive generator and scorer" section in full.
- docs/SIV_Philosophy.md §9 (forbidden concepts).

Also consult Contracts C7 and C8 in SIV_v2_Development_Spec.md.

Goal: Implement the mutation-based contrastive generator (§4.5) with Vampire filtering, and the scorer that produces the F1 metric (§4.6).

Files touched:
- siv/contrastive_generator.py — new file (replacing any v1 stub).
- siv/scorer.py — new file (replacing any v1 stub).
- siv/vampire_interface.py — already exists from v1; confirm or update its contract to: (fol_a: str, fol_b: str, check: Literal["unsat", "entails"]) -> Literal["sat", "unsat", "timeout", "unknown"].
- tests/test_contrastive_generator.py — new.
- tests/test_scorer.py — new.
- siv/invariants.py — LEFT ALONE. Fixed in Phase 4.

What to implement:

3.1 — Mutation operators. Six operators in siv/contrastive_generator.py. Each is a tree-walker over Formula — it recurses over the formula structure and emits mutants at every applicable node.

1. negate_atom: for each AtomicFormula encountered in the tree, produce a mutant with that atom's negated flag flipped.
2. swap_binary_args: for each binary atomic formula, produce the arg-swapped variant.
3. flip_quantifier: for each TripartiteQuantification node, produce a mutant with its quantifier flipped between universal and existential.
4. drop_restrictor_conjunct: for each TripartiteQuantification with a non-empty restrictor, produce mutants each removing one restrictor atom.
5. flip_connective: for each connective node, produce the following mutants depending on the original connective:
   - and → or (one mutant: same operands, connective replaced).
   - or → and (one mutant: same operands, connective replaced).
   - implies → iff (one mutant: same operand order, connective replaced).
   - implies → implies with operands reversed (one mutant: swap antecedent and consequent, connective unchanged; this is the "asymmetric flip" — implies is non-commutative so the reversed-operand variant is a distinct candidate mutation).
   - iff → implies (one mutant: same operand order, connective replaced; operand order does not matter semantically for iff so no reversed variant is emitted for this direction).
   For each connective node the operator emits exactly the mutants listed above for that connective's type; no other variants.
6. replace_subformula_with_negation: for each non-root non-atomic sub-formula, produce a mutant wrapping that sub-formula in Formula.negation.

Each operator produces a list of SentenceExtraction mutants, each carrying a mutation_kind: str field for telemetry. The mutation_kind string is the operator name (e.g. "flip_connective").

Note on flip_connective and Vampire filtering (expected behavior, not a telemetry problem): the implies → iff mutation is entailment-neutral whenever the biconditional and the conditional happen to coincide in the relevant interpretation, and in many concrete cases Vampire will return sat and the mutant will be dropped. Likewise, iff → implies drops the ↔ direction and is unsat only when that direction is actually asserted. These drops are expected and correct per the §4.5 acceptance rule. They contribute to dropped_neutral in telemetry; they are not evidence of a permissive operator and do not by themselves indicate a telemetry threshold failure.

3.2 — Vampire-filtered acceptance. Implement:

def generate_contrastives(
    extraction: SentenceExtraction,
    timeout_s: int = 5,
) -> tuple[list[UnitTest], TelemetryDict]: ...

For each mutant:
1. Compile the mutant via compile_canonical_fol.
2. Compile the original via compile_canonical_fol.
3. Ask Vampire whether (original ∧ mutant) is unsat.
4. Accept only on unsat. Drop on sat, timeout, or unknown.

TelemetryDict keys: generated, accepted, dropped_neutral, dropped_unknown, unknown_rate, per_operator (breakdown by operator name).

Wire generate_contrastives into compile_sentence_test_suite from Phase 1 so the returned TestSuite has a populated negatives list.

3.3 — Scorer. siv/scorer.py::score(test_suite, candidate_fol) -> ScoreReport:

- For each positive test: Vampire-check whether candidate entails it.
- For each contrastive test: Vampire-check whether candidate entails it (should not).
- Compute recall = positives_entailed / positives_total.
- Compute precision = contrastives_rejected / contrastives_total.
- Compute f1 = 2 * recall * precision / (recall + precision).
- No coverage fraction. No adjustment.

Return ScoreReport with fields: recall, precision, f1, positives_entailed, positives_total, contrastives_rejected, contrastives_total, per_test_results.

Forbidden moves:
- Do not add a coverage fraction or coverage_fraction field to ScoreReport.
- Do not adjust the score for "sentence scope" — the F1 is returned as-is regardless of input.
- Do not add scope-aware scoring or any escape hatch for modal/proportional/collective sentences.
- Do not add a seventh mutation operator. The six listed are exhaustive per §4.5.
- Do not silently drop operators if mutant counts get large. If a per-sentence cap is needed for compute, implement it as an explicit numeric cap (e.g., 50) and log the cap hit; do not restrict the tree walk.
- Do not accept sat, timeout, or unknown mutants. Only unsat mutants become contrastives.
- Do not introduce backward-compatibility aliases.

Tests required:

tests/test_contrastive_generator.py:
- One test per mutation operator, confirming its output is structurally as specified. Tree-walking semantics matter: applying replace_subformula_with_negation to (A and B) should produce three mutants (negate A, negate B, negate the whole conjunction), not just one.
- swap_binary_args on a symmetric predicate (e.g., a sibling relation) produces a mutant Vampire correctly rejects as neutral (sat).
- swap_binary_args on an asymmetric predicate (e.g., Schedule(person, event)) produces a mutant Vampire accepts as contrastive (unsat).
- flip_connective on a disjunction produces a conjunction that Vampire confirms as inconsistent with the original in at least one evaluated context.
- generate_contrastives for each of the fourteen Phase 2 examples produces a non-empty, all-unsat-verified negative set. This is fourteen tests, one per example.

tests/test_scorer.py:
- Perfect candidate gives F1 = 1.0.
- Candidate missing a positive gives the expected recall drop.
- Candidate entailing a contrastive gives the expected precision drop.

Gate:
- All tests pass.
- Telemetry on the fourteen Phase 2 examples shows unknown_rate < 0.2 and accepted / generated > 0.3. If either fails, investigate before proceeding.
- The employees-meetings test suite has both populated positives and populated contrastives, and the canonical FOL scores 1.0 on its own test suite.

Explicit non-goals:
- No CI invariant harness. Phase 4.
- No FOLIO-scale evaluation. Phase 5.

If anything in this prompt contradicts the architecture documents, stop and surface the contradiction. If a required implementation choice is ambiguous, stop and ask. Do not guess and do not loosen requirements to get unstuck.
```

---

## Phase 4 prompt

```
You are executing Phase 4 of the SIV v2 refactor. The codebase is at the state Phase 3 left it in: schema, compiler, pre-analyzer, extractor, contrastive generator, and scorer are all live.

Before writing any code, read:
- docs/SIV_Master_Document.md §4.7 (Soundness invariants).
- docs/SIV_Refactor_Plan.md "Phase 4 — Soundness invariants in CI" section in full.
- docs/SIV_Philosophy.md §9 (forbidden concepts).

Also consult Contracts C9a and C9b in SIV_v2_Development_Spec.md.

Goal: Enforce soundness mechanically on every build (§4.7).

Files touched:
- siv/invariants.py — add two functions (full rewrite if v1 stub present).
- tests/test_soundness_invariants.py — new file.
- tests/data/invariant_corpus.json — new file, curated sentences.
- CI configuration — ensure the invariant tests run on every PR.

What to implement:

4.1 — Invariants.

Function 1: check_entailment_monotonicity(extraction, test_suite) -> tuple[bool, Optional[str]]:
- Let P = conjunction of test_suite's positive tests.
- Let Q = compile_canonical_fol(extraction).
- Use Vampire to check both P ⊨ Q and Q ⊨ P.
- Return (False, reason) if either direction fails, times out, or returns unknown. Timeout is a failure, not a skip.
- Return (True, None) iff both directions are proved.

Function 2: check_contrastive_soundness(test_suite) -> tuple[bool, Optional[str]]:
- Let P = conjunction of positives.
- For each contrastive C: check (P ∧ C) is unsat via Vampire.
- Return (False, reason) on the first failure (sat, timeout, or unknown). Timeout is a failure, not a skip.
- Return (True, None) iff every contrastive is unsat against P.

4.2 — Invariant corpus. tests/data/invariant_corpus.json contains the fourteen examples from Phase 2 plus at least eight additional hand-curated in-scope sentences that exercise patterns the examples don't cover. Required additional patterns (each must be present at least once):

- Nested quantification with both universal and existential at different scopes.
- Connective containing a quantification that itself contains a connective. Example: "If it rains, then every employee who is remote and every employee who is in-person works from home."
- Disjunction with three operands.
- Deeply nested negations (triple-negation or negation-of-implication).
- A biconditional between two quantified statements.
- A ground fact expressed as an atomic formula with two constants.
- A universal whose nucleus is a disjunction.
- A universal whose restrictor draws from an inner existential that itself contains a connective.

Corpus total: at least 22 sentences (14 + ≥8).

4.3 — Tests required. tests/test_soundness_invariants.py:

- Both invariants pass on every entry in the invariant corpus.
- A deliberately-broken test: modify the compiler in a test-only way to produce a subtly-wrong positive (e.g., an off-by-one universe), confirm the monotonicity invariant catches it, and restore the compiler afterward. This test proves the invariant is load-bearing, not trivially satisfied.

4.4 — CI wiring. Update the CI configuration (e.g., .github/workflows/*.yml or equivalent) so the soundness invariant tests run on every PR and a failure fails the build.

Forbidden moves:
- Do not mark a timeout as a pass, a skip, or a "warning." Timeout is a failure.
- Do not mark an unknown result as a pass. Unknown is a failure.
- Do not reduce the corpus below 22 sentences or skip any of the required additional patterns listed in 4.2.
- Do not modify the compiler to make the deliberately-broken test unnecessary; the test must exercise a real bug and confirm the invariant catches it.
- Do not add a "soundness bypass" flag or environment variable.

Gate:
- All invariant tests green on the full 22-sentence corpus.
- CI configured and verified to fail the build on invariant violation. Verify by pushing a throwaway branch containing an intentional bug and confirming the CI run fails.

If anything in this prompt contradicts the architecture documents, stop and surface the contradiction. If a required implementation choice is ambiguous, stop and ask. Do not guess and do not loosen requirements to get unstuck.
```

---

## Phase 5 prompt

```
You are executing Phase 5 of the SIV v2 refactor. The codebase is at the state Phase 4 left it in: full pipeline live, invariants enforced in CI.

Before writing any code, read:
- docs/SIV_Master_Document.md §7 (Coverage claim) and §8.1 (Evaluator mode).
- docs/SIV_Refactor_Plan.md "Phase 5 — FOLIO validation" section in full.
- docs/SIV_Philosophy.md §2 (what SIV is not) and §9 (forbidden concepts).

Goal: Measure how well the system handles real FOLIO premises. This is the empirical validation that underwrites the paper's claims.

Files touched:
- scripts/run_folio_evaluation.py — new.
- reports/folio_agreement.json — new output file (written by the script).

What to implement:

1. Load the public FOLIO dataset (premises only; this phase does not evaluate conclusions).
2. For each premise, run the SIV pipeline end-to-end: extract (Phase 2), compile (Phase 1), generate contrastives (Phase 3), score (Phase 3) against FOLIO's gold FOL as the candidate.
3. Aggregate:
   - Mean F1 across all premises.
   - Distribution of F1 (e.g., histogram bins).
   - Per-Formula-case breakdown: F1 restricted to premises whose top-level Formula case is atomic, quantification, connective, or negation respectively.
   - Premises where F1 < 0.5 (manual review list).
   - Premises where extraction failed (manual review list).
4. Write reports/folio_agreement.json with the aggregates.

Forbidden moves (from SIV_Philosophy.md §9 and the explicit non-goals in the refactor plan):
- Do not report a coverage fraction. The score is the score.
- Do not make any claim about sentences outside the FOL-translatable class. If a premise is genuinely modal or proportional, the F1 reported is whatever it is, with no commentary categorizing it as "out of scope."
- Do not add an is_fol_expressible filter to skip premises.
- Do not adjust F1 with any scope-aware term.
- Do not add a "scope rejection" taxonomy when classifying extraction failures. Failures are categorized only as "user-scope issue" (a real sentence SIV cannot handle) or "actionable bug" — this binary categorization is for manual review and does not affect the reported F1 numbers.
- Do not modify the pipeline (extractor, compiler, generator, scorer) in this phase. Phase 5 is measurement only. If measurement reveals a bug, stop and surface it rather than patching silently.

Tests required: none mandated by the refactor plan for Phase 5 beyond the existing test suite remaining green. The script itself is the deliverable and the numbers are the validation.

Gate:
- Script runs to completion on the full FOLIO dataset (300 premises).
- Mean F1 on the employees-meetings class of sentences (universal-with-restrictive-relative) is ≥ 0.85. This is the headline empirical claim: the system correctly handles the v1 bug class.
- Mean F1 on atomic (ground) predications is ≥ 0.90.
- Mean F1 on connective-only sentences is ≥ 0.80.
- Extraction failure rate is documented. Failures are manually reviewed and categorized as either real sentences SIV cannot handle (user-scope issue) or bugs to fix (actionable). The categorization is recorded in reports/folio_agreement.json.

If a gate threshold is missed, stop and surface the result with a diagnosis (which Formula case underperformed, which premises failed). Do not loosen the threshold and do not move on to Phase 6.

If anything in this prompt contradicts the architecture documents, stop and surface the contradiction. If a required implementation choice is ambiguous, stop and ask. Do not guess and do not loosen requirements to get unstuck.
```

---

## Phase 6 prompt

```
You are executing Phase 6 of the SIV v2 refactor. The codebase is at the state Phase 5 left it in: full pipeline validated on FOLIO; reports/folio_agreement.json written.

Before writing any code, read:
- docs/SIV_Master_Document.md §6 (Dependencies) and the Appendix "What is not in SIV".
- docs/SIV_Refactor_Plan.md "Phase 6 — Cleanup and release" section in full.
- docs/SIV_Philosophy.md §9 (forbidden concepts).

Goal: Remove any v1 remnants, finalize documentation, tag the release.

Files touched:
- Anything in siv/ not on the dependency list in SIV_Master_Document.md §6 — delete.
- README.md — rewrite.
- CHANGELOG.md — add v2.0.0 entry.
- Release tag: v2.0.0.

What to do:

1. Run `git grep` for each of the following forbidden or obsolete terms. Any match outside docs/archive/ must be deleted (the match, and usually the containing symbol, field, or file):

   - MacroTemplate
   - macro_template
   - universal_affirmative
   - Fact
   - is_fol_expressible
   - rejection_reason
   - FOLRejectionReason
   - rejection_note
   - coverage_fraction
   - is_collective
   - detected_modal
   - detected_temporal
   - detected_proportional
   - proportional_quantifier
   - PROPORTIONAL_QUANTIFIER
   - plural_non_distributive

2. Rewrite README.md with a new quick-start reflecting the seven-component architecture from SIV_Master_Document.md §4. Include a minimal working example that exercises all four Formula cases (atomic, quantification, negation, connective).

3. Write a CHANGELOG.md entry for v2.0.0: a concise list of what changed, what was removed, and the headline empirical result from Phase 5 (mean F1 on the employees-meetings class).

4. Tag the release v2.0.0.

Forbidden moves:
- Do not reintroduce any forbidden term while "cleaning up." If a grep match is ambiguous, surface it rather than edit-in-place.
- Do not add bonus cleanup steps beyond those listed above. If you spot additional lint-level issues, note them for a separate future change; Phase 6 is scoped to the refactor plan.
- Do not skip the grep check. Zero matches outside docs/archive/ is the gate.
- Do not omit the CHANGELOG or README rewrite to save time. They are gate items.
- Do not add a Phase 7. The refactor ends at Phase 6.

Tests required: the full test suite, including slow invariant tests, must be green.

Gate:
- `git grep` on the forbidden-term list returns zero matches outside docs/archive/.
- README quick-start copy-pastes and runs end to end.
- Full test suite green, including slow invariant tests.
- Tag v2.0.0 applied to the final commit on v2-from-clean.

If anything in this prompt contradicts the architecture documents, stop and surface the contradiction. If a required implementation choice is ambiguous, stop and ask. Do not guess and do not loosen requirements to get unstuck.
```

---

## Post-refactor verification

```
You are running the post-refactor verification pass. All seven phases (0 through 6) have completed and v2.0.0 has been tagged. Do not make code changes during this pass except where a check explicitly requires one; if any check fails, stop and surface the failure.

Before starting, read:
- docs/SIV_Master_Document.md end to end.
- docs/SIV_Philosophy.md §9.
- SIV_v2_Development_Spec.md Contracts section (C0 through C9b).

Perform the following checks in order:

1. Contract verification. For each contract C0 through C9b in SIV_v2_Development_Spec.md, inspect the corresponding implementation and confirm the contract holds: type signature, preconditions, postconditions, error modes, invariants. Report one line per contract: PASS or FAIL with reason.

2. Forbidden-term grep. Run `git grep` for each term in the Phase 6 forbidden list:
   - MacroTemplate, macro_template, universal_affirmative, Fact, is_fol_expressible, rejection_reason, FOLRejectionReason, rejection_note, coverage_fraction, is_collective, detected_modal, detected_temporal, detected_proportional, proportional_quantifier, PROPORTIONAL_QUANTIFIER, plural_non_distributive.
   Confirm zero matches outside docs/archive/. Report any matches found.

3. Full test suite. Run the full pytest suite including slow invariant tests. Confirm green. Report the pass count and any failures.

4. FOLIO validation replay. Re-run scripts/run_folio_evaluation.py and confirm the headline numbers in reports/folio_agreement.json match what Phase 5's gate required:
   - Mean F1 on employees-meetings class ≥ 0.85.
   - Mean F1 on atomic (ground) predications ≥ 0.90.
   - Mean F1 on connective-only sentences ≥ 0.80.
   Report the actual numbers.

5. CHANGELOG summary. Produce a one-page summary of what changed between v1 and v2, suitable for the CHANGELOG.md entry. Structure: (a) what was removed, (b) what was rewritten, (c) what is new, (d) headline empirical result from Phase 5. No prose beyond one page.

If any check fails, stop after reporting the failure. Do not attempt fixes during verification; fixes are a separate, scoped change. If anything in this prompt contradicts the architecture documents, stop and surface the contradiction.
```
