# SIV — Canonical Specification

*The single source of truth for SIV. Replaces SIV_Philosophy.md, SIV_Master_Document.md, SIV_Refactor_Plan.md, and SIV_v2_Development_Spec.md. Every claim about SIV — what it is, what it is not, how it is built, what order it is built in, how each phase is verified — lives here. No other document has authority.*

---

## Table of contents

1. What SIV is
2. What SIV is not
3. The three principles
4. Scope contract
5. Forbidden concepts
6. Architecture — the seven components
7. Contracts
8. Soundness invariants
9. Dependencies
10. Modes of operation
11. Phase plan — how to execute this refactor
12. Phase 0 prompt
13. Phase 1 prompt
14. Phase 2 prompt
15. Phase 3 prompt
16. Phase 4 prompt
17. Phase 5 prompt
18. Phase 6 prompt
19. Post-refactor verification prompt
20. Deferred decisions
21. References

---

## 1. What SIV is

SIV is a metric for one task: **given a natural language sentence and a candidate first-order logic translation of it, score how faithfully the candidate captures the atomic logical content of the source.**

The score decomposes into two parts:

- **Recall.** Does the candidate entail the atomic facts the source asserts?
- **Precision.** Does the candidate reject mutations that would contradict the source?

The headline number is the F1 of these two rates. That is the whole metric.

### The problem SIV solves

Current metrics for NL-to-FOL translation all fail in ways that make them unusable as research tools. Exact match rewards only translations that exactly reproduce a specific human annotator's style. Denotation accuracy treats all paths to the right answer as equivalent, including paths that go through hallucinated premises. N-gram and embedding metrics (BLEU, BERTScore) cannot see the difference between a sentence and its logical negation, because the surface forms differ by a single token.

What is needed is a metric that checks whether a candidate FOL translation captures the atomic logical content of the source sentence — each quantifier, each predicate, each argument binding, each connective — independently and mechanically. That metric is SIV.

### The bug SIV was built to kill

Version 1 of SIV had a single load-bearing failure: on sentences of the form *"All X who V₁ do V₂"*, it produced the FOL *"All X do V₂"* — collapsing the restrictive clause into nothing. The canonical example is:

> "All employees who schedule meetings attend the company building."

V1 produced the FOL equivalent of *"All employees attend the company building"* — dropping the *"who schedule meetings"* clause entirely. This is not a scope problem; the sentence is perfectly FOL-translatable. It is a faithfulness problem: the translation lost the condition that restricts which employees the universal applies to.

Every design decision that follows exists to make this collapse structurally impossible.

---

## 2. What SIV is not

SIV is not a filter, a classifier, or a gatekeeper. It does not decide whether a sentence belongs in first-order logic. It does not refuse to score sentences it finds difficult. It does not maintain a taxonomy of reasons for rejection. It does not report a coverage fraction alongside its score.

SIV assumes the user is sending it sentences that have faithful FOL translations. If the user sends something else — a modal attitude report, a proportional quantifier, a genuinely ambiguous sentence — SIV will still produce output, but that output carries no correctness guarantee. **The scope boundary lives with the user, not with the metric.**

This is deliberate. Every attempt to push scope enforcement into SIV itself has failed: rejection taxonomies drifted, pre-analyzer heuristics misclassified edge cases, coverage fractions became levers for gaming the score. The metric is stronger when it does one thing well than when it tries to be its own user.

---

## 3. The three principles

**Principle 1 — Lexical exactness.** SIV does not stem, lemmatize, or paraphrase. "Schedule" and "scheduled" are different predicates; a translation that conflates them has lost information. In formal logic "close enough" is a category error.

**Principle 2 — Binary decomposition.** Every predicate has arity one or two. Ternary and higher-arity predicates (*Schedule(person, meeting, customer)*) are not representable in the schema. Multi-participant events decompose into atomic binary relations (*Schedule(person, meeting)* and *With(meeting, customer)*). This is Neo-Davidsonian atomic decomposition applied at the schema level; it is non-negotiable because it is what makes SIV's output usable by downstream symbolic systems.

**Principle 3 — Atomic entailment.** A correct conclusion does not redeem a hallucinated premise. SIV tests every atomic fact independently and uses a theorem prover to verify each test. The metric proves the translation path, not the endpoint. Denotation accuracy — checking whether the final boolean matches — is exactly the failure mode SIV refuses to repeat.

---

## 4. Scope contract

SIV targets the class of sentence that has a faithful first-order logic translation. In practice this is the class where a competent human translator would produce an FOL formula without caveat.

The positive characterization is finite and closed. First-order logic's grammar has **five constructs and no others**: atomic predications, boolean connectives (AND, OR, NOT, IMPLIES, IFF), quantifiers (∀, ∃), variables, and constants. Any sentence expressible as a finite combination of these five constructs is in SIV's scope. This is the grammar fixed by Frege (1879) and reproduced in every logic textbook since; SIV's schema represents exactly this grammar, and nothing outside it. The grammar is closed — there is no sixth construct waiting to appear.

Sentences SIV does not handle — modal attitudes, proportional quantifiers, lexically collective predicates, scope-ambiguous sentences where the reading cannot be recovered from syntax — are sentences whose logical form exceeds FOL. They require modal logic, generalized quantifier theory, or plural logic respectively. If the user sends SIV one of these, SIV makes no claim about the result. **This is a contract, not a capability.**

### What the user gets

A user sends SIV a sentence and a candidate FOL translation. SIV returns a score in `[0, 1]` and a test-by-test report showing which atomic facts the candidate captured and which mutations it correctly rejected. No coverage fraction. No rejection reason. No diagnostic about whether the sentence was "in scope." Just the metric.

### The contract, restated

> SIV takes a sentence and a candidate FOL translation. It returns an F1 score measuring recall and precision of atomic logical content. It assumes the sentence is FOL-translatable — expressible in Frege's closed grammar of atoms, connectives, and quantifiers. It does not classify, reject, or adjust for sentences outside that class. The user owns the scope.

---

## 5. Forbidden concepts

The following are explicitly not part of SIV and must not be added without revising this document. Each is on this list because an earlier version tried to include it and the inclusion created drift or scope creep that had to be unwound. **The negative list is as load-bearing as the positive one.**

- No rejection taxonomy or `FOLRejectionReason` enum.
- No `is_fol_expressible` flag or equivalent.
- No `rejection_reason` or `rejection_note` field.
- No coverage fraction or scope-aware scoring. No `coverage_fraction` field.
- No ontological type vocabulary beyond grammatical category (`entity`, `constant`, `predicate name`). No `person`, `animal`, `place` type values.
- No detection of modal, temporal, or proportional sentence features. No `detected_modal`, `detected_temporal`, `detected_proportional`, `proportional_quantifier`, `PROPORTIONAL_QUANTIFIER`, or `plural_non_distributive` fields or enums.
- No handling of collective predication. No `is_collective` field.
- No handling of scope ambiguity.
- No hand-rolled JSON schemas; all schemas derive from Pydantic models.
- No backward-compatibility aliases for renamed symbols.
- No grammatical constructs beyond Frege's five. The `Formula` type in §6.2 is the complete grammar; no fifth `Formula` case is ever added.

### Historical v1/v2-era identifiers to purge

In addition to the forbidden concepts above, the following v1/v2-era identifiers must be removed from the codebase during cleanup (Phase 6):

`MacroTemplate`, `macro_template`, `universal_affirmative`, `Fact`.

---

## 6. Architecture — the seven components

SIV is seven components and six dependencies. Anything not on this list is not part of SIV.

### 6.1 Pre-analyzer

Given a natural language sentence, the pre-analyzer uses spaCy's dependency parse to compute two flags:

- `requires_restrictor`: true if the sentence contains a restrictive relative clause on the subject (detected by the `relcl` dependency), or if the sentence matches the regex `^(all|every|each|no|any)\s+\w+\s+(who|that|which)\b` (case-insensitive).
- `requires_negation`: true if the sentence contains the lemma `no`, `none`, `never`, or `neither`, or if there is a `neg` dependency on the main verb.

**No LLM call. No network call. No other flags. No other outputs.** This component exists solely to catch the v1 bug: when the sentence structurally requires a restrictor, something downstream must check that the extraction has one.

### 6.2 Schema

The schema defines the data structure that extraction produces and compilation consumes. Every component that manipulates logical structure reads and writes this schema.

The schema represents exactly the grammar of FOL as fixed by Frege (1879): atomic predications, boolean connectives, and quantifiers. It has no other constructs. The closure of this grammar is what makes SIV's scope bounded: any sentence outside this grammar is outside FOL and therefore outside SIV.

#### 6.2.1 Top-level structure

A `SentenceExtraction` contains:

- `nl`: the source sentence.
- `predicates`: declared predicates, each with a name, arity (1 or 2), and per-position argument types.
- `entities`: variable-bound individuals referenced in the sentence.
- `constants`: named individuals (proper nouns).
- `formula`: a single `Formula` representing the full logical content of the sentence.

The `formula` field is the whole payload. It is a recursive structure that can represent any FOL formula — a bare atomic predication, a quantified statement, a boolean combination of sub-formulas, or any nesting of these.

#### 6.2.2 The Formula type

`Formula` is a sum type with **exactly four cases**. Every valid FOL formula is exactly one of these:

```python
class Formula(BaseModel):
    atomic: Optional[AtomicFormula] = None
    quantification: Optional[TripartiteQuantification] = None
    negation: Optional["Formula"] = None
    connective: Optional[Literal["and", "or", "implies", "iff"]] = None
    operands: Optional[List["Formula"]] = None
```

- **Atomic case** (`atomic` populated): a single predication like `CzechConductor(miroslav)` or `Schedule(x, y)`. Leaf of the formula tree.
- **Quantification case** (`quantification` populated): a universal or existential over a domain, with its own internal tripartite structure (§6.2.3).
- **Negation case** (`negation` populated): `¬φ` for some sub-formula `φ`. Negation is unary; there is one operand, expressed as a nested `Formula`.
- **Connective case** (`connective` and `operands` populated together as a single case): binary or n-ary boolean combinations — `φ ∧ ψ`, `φ ∨ ψ`, `φ → ψ`, `φ ↔ ψ`.

A validator enforces that exactly one of the four cases is active per `Formula` instance. `connective` and `operands` are populated together as a single case.

Recursion handles all nesting for free. *"Miroslav Venhoda was a Czech choral conductor"* becomes a bare atomic. *"All employees who schedule meetings attend the company building"* becomes a bare quantification. *"The L-2021 monitor is either used in the library or has a type-c port"* becomes a connective-or over two atomic formulas. *"If the forecast calls for rain, then all employees work from home"* becomes a connective-implies over an atomic antecedent and a quantification consequent.

#### 6.2.3 TripartiteQuantification

Quantifications have their own internal structure, the **tripartite form** of Barwise & Cooper (1981), Heim (1982), and Kamp (1981):

```python
class TripartiteQuantification(BaseModel):
    quantifier: Literal["universal", "existential"]
    variable: str
    var_type: str
    restrictor: List[AtomicFormula]          # conjuncts that bound the domain
    nucleus: Formula                          # what is asserted of the bounded domain
    inner_quantifications: List[InnerQuantification] = []
```

The **restrictor** is a conjunctive list of atoms — these are the clauses that define which individuals the quantifier ranges over (*"employees who schedule meetings"*). The **nucleus** is a full `Formula`, not a list of atoms — this is critical, because it means the nucleus can be any FOL formula, including a boolean combination or another quantification. This supports sentences like *"Every student reads a book or watches a movie"* (nucleus is a disjunction).

The tripartite form is what forces the distinction between *which individuals the quantifier ranges over* and *what is claimed of them* — the exact distinction v1 could not make and that the employees-meetings bug turned on.

**Inner quantifications.** Restrictor atoms may contain free variables bound by inner quantifiers. These are declared in the parallel `inner_quantifications` list, one per variable introduced in the restrictor beyond the bound variable itself. Inner quantifiers scope **inside the restrictor only**; the nucleus handles its own quantifications via its own `Formula` structure (no separate field needed).

```python
class InnerQuantification(BaseModel):
    quantifier: Literal["universal", "existential"]
    variable: str
    var_type: str
```

#### 6.2.4 Atomic formulas

```python
class AtomicFormula(BaseModel):
    pred: str                   # must reference a declared PredicateDecl
    args: List[str]             # variable names or constant IDs; length == pred.arity
    negated: bool = False       # convenience flag; equivalent to Formula.negation on this atom
```

The `negated` flag is a convenience: it allows compact representation of common patterns like *"No X is Y"* (a universal with a single negated atom in the nucleus) without wrapping every such atom in a `Formula.negation`. The compiler treats both representations as equivalent. The validator enforces that atom arities and argument types match their declared `PredicateDecl`.

Types in this schema are **grammatical, not ontological**. A `type` field distinguishes entities from constants from predicate names, to prevent ill-formed FOL like `Employee(Schedule)`. It does not classify entities as `person` versus `animal`; that level of typing is not the metric's job.

#### 6.2.5 Supporting models

```python
class PredicateDecl(BaseModel):
    name: str
    arity: Literal[1, 2]
    arg_types: List[str]  # length == arity

class Entity(BaseModel):
    id: str
    surface: str
    type: str             # grammatical, not ontological

class Constant(BaseModel):
    id: str
    surface: str
    type: str             # grammatical, not ontological

class SentenceExtraction(BaseModel):
    nl: str
    predicates: List[PredicateDecl] = []
    entities: List[Entity] = []
    constants: List[Constant] = []
    formula: Formula
```

#### 6.2.6 Test suite models

```python
class UnitTest(BaseModel):
    fol: str                                          # NLTK-compatible ASCII FOL
    kind: Literal["positive", "contrastive"]
    mutation_kind: Optional[str] = None               # set iff kind == "contrastive";
                                                      # one of the six operator names in §6.5

class TestSuite(BaseModel):
    extraction: SentenceExtraction
    positives: List[UnitTest] = []
    contrastives: List[UnitTest] = []
```

Invariant: `UnitTest.mutation_kind` is non-`None` iff `UnitTest.kind == "contrastive"`. Enforced by a Pydantic `model_validator` on `UnitTest`.

#### 6.2.7 JSON Schema derivation

The JSON Schema passed to the LLM as `response_format` is **derived mechanically** from the Pydantic `SentenceExtraction` model. Hand-rolled JSON Schemas are forbidden. This guarantees the Pydantic model and the API-level constraint cannot drift — a class of bug that cost two phases of the previous refactor.

The derivation:

- Inlines all non-recursive `$ref` / `$defs`.
- Retains `$defs` entries only for recursive types (`Formula`, `TripartiteQuantification`) with `$ref` at recursion points. OpenAI strict mode supports this pattern. Full inlining is impossible for self-referential types.
- Sets `additionalProperties: false` on every object.
- Marks every property as `required` (null values expressed via union types).
- Strips `title`, `description`, `default`.

### 6.3 Extractor

The extractor takes a sentence and returns a validated `SentenceExtraction`. It calls a frozen LLM (GPT-4 snapshot, temperature 0, pinned seed), passing the system prompt, a small set of few-shot examples, and the sentence.

The LLM's output is constrained by the Pydantic-derived JSON Schema, so it cannot return something syntactically malformed. After the response arrives, two checks run:

1. **Schema validation**: every atom's predicate is declared; arities match; every argument references a declared entity or constant or bound variable; every `Formula` has exactly one of its four cases populated.
2. **Tripwire enforcement**: if the pre-analyzer said `requires_restrictor`, the extraction's formula tree must contain at least one `TripartiteQuantification` with a populated restrictor. If `requires_negation` was set, at least one negation must appear somewhere in the formula tree (a `Formula.negation` node or an `AtomicFormula` with `negated=True`, anywhere in the tree including inside connectives and quantification restrictors/nuclei).

If either check fails, the extractor retries **once** with the violation appended to the prompt. If the retry also fails, the extractor raises. There is no silent acceptance and no second retry — infinite retries hide systemic prompt failures.

### 6.4 Compiler

The compiler turns a validated `SentenceExtraction` into FOL formulas. It has two entry points, and it is recursive over the `Formula` structure. **The compiler does not consume `nl`.** Both entry points must be pure functions of the `SentenceExtraction` alone; the §8.1 bidirectional-entailment invariant requires this.

- `compile_sentence_test_suite(extraction) -> TestSuite` emits the positive tests. The full canonical FOL is one positive test. Each non-trivial sub-formula also emits its own entailment test, so every atomic claim the source makes is independently checkable.
- `compile_canonical_fol(extraction) -> str` emits the full canonical FOL for the sentence as a single string.

A **non-trivial sub-formula** is: every `quantification` node, every `negation` node, every `connective` node, plus every atomic node that appears as a top-level restrictor conjunct or as the top-level nucleus atom. Leaf atoms already present as arguments of a parent connective or quantification do not generate their own sub-entailment test.

#### Sub-entailment test construction

For each non-trivial sub-formula node S, the sub-entailment test is the universal closure of S over its free variables, emitted as a positive `UnitTest` only if the canonical FOL freestanding entails that closure under Vampire.

The load-bearing constraint is canonical entailment (C9a), not monotone-position preservation. These are different logical facts; on arbitrary `Formula` structure the canonical does NOT entail every monotone-positive sub-formula (for example, `(A -> B)` does not entail `B`). Emitting a sub-test the canonical cannot prove would break C9a on every conditional.

Practical consequence: sub-tests are emitted from exactly these positions:

- (a) **AND conjuncts.** An `AtomicFormula` or sub-`Formula` that is a direct operand of a `Formula` with `connective="and"` IS a non-trivial sub-formula. Conjunct-elimination `(A & B) ⊨ A` is a valid entailment, so these sub-tests are sound. This is the only case where atoms as direct connective operands generate sub-tests; §6.4's general atom-exclusion rule applies to `or`/`implies`/`iff`/quantifier operands.
- (b) **Inner-existential restrictor atoms.** For a `TripartiteQuantification` with `quantifier="existential"` and `inner_quantifications` declared, restrictor atoms are asserted conjunctively with the nucleus; their existential closure is entailed by the canonical. Emit each as `exists x.(S)` (using the nearest enclosing binding variable), wrapped by any outer quantifier chain so no free variables remain.
- (c) **Existential nucleus sub-formulas.** For a `TripartiteQuantification` with `quantifier="existential"`, the nucleus is conjunctively asserted; its recursive AND-conjunct sub-formulas (per (a)) are emitted with `exists x.` closure.

Positions that do NOT emit sub-tests:

- Any sub-formula under a `Formula.negation` wrapper.
- Operands of `connective="or"`, `"implies"`, `"iff"` (other than AND-conjuncts nested inside them).
- The antecedent of an `implies`.
- Either operand of an `iff` (iff interiors are blocked entirely).
- The restrictor of a universal `TripartiteQuantification` (restrictor is the antecedent of the implication).
- The nucleus of a universal `TripartiteQuantification`, except for AND-conjuncts nested inside it — those emit with `all x.(⋀R -> conjunct)` closure, which is sound because `all x.(P -> (A & B)) ⊨ all x.(P -> A)`.
- Any atom with `negated=True`.

This specification is deliberately conservative. Missing sub-tests cost granular reporting, not soundness. Granular per-atom signal is supplied by the contrastive generator (§6.5) via `negate_atom` and `swap_binary_args`; the positives list carries the overall translation.

Free variables in sub-tests are always closed by the nearest enclosing quantifier on the path from the root to S. Sub-tests never contain free variables.

#### Compilation rules

Per `Formula` case:

- **Atomic** → emit `Pred(args...)` or `-Pred(args...)` if `negated`.
- **Negation** → emit `-(` + compile(operand) + `)`.
- **Connective `and`** → join compiled operands with `&`.
- **Connective `or`** → join compiled operands with `|`.
- **Connective `implies`** → emit `(` + compile(op1) + `->` + compile(op2) + `)`. Binary.
- **Connective `iff`** → emit `(` + compile(op1) + `<->` + compile(op2) + `)`. Binary.
- **Quantification, universal** → emit `all x.(⋀restrictor -> compile(nucleus))`.
- **Quantification, existential** → emit `exists x.(⋀restrictor & compile(nucleus))`.

**Inner quantifications** on a `TripartiteQuantification` (per §6.2.3) wrap the restrictor conjunction, in declaration order, innermost-last. For an outer universal over `x` with restrictor `R`, nucleus `N`, and a single existential `InnerQuantification` on `y`, emit:

```
all x.(exists y.(⋀R) -> compile(N))
```

For an outer existential:

```
exists x.(exists y.(⋀R) & compile(N))
```

Multiple inner quantifications nest left-to-right in declaration order; the first declared is the outermost of the inner block, the last declared is innermost adjacent to the restrictor conjunction. Inner quantifiers scope inside the restrictor only; the nucleus handles its own quantifications via its own `Formula` structure.

If a sentence appears to require a different scoping — for instance, an inner quantifier whose scope must extend into the nucleus — **stop and surface the ambiguity** rather than guessing. The nucleus is a full `Formula`; quantifications that belong in the nucleus are expressed there.

#### Two structurally distinct paths

The two entry points are **deliberately separate code paths**: different traversal order, different variable-naming scheme, different string-assembly. Their independent outputs must be bidirectionally entailing — a property checked by the soundness invariants (§8). If both paths had the same bug, the check would not catch it; by making them structurally distinct, we reduce that risk to negligible.

Output format is **NLTK-compatible ASCII FOL**: `all x.(P(x) -> Q(x))`, `exists x.(P(x) & Q(x))`, `-P(x)`, `(A & B)`, `(A | B)`, `(A -> B)`, `(A <-> B)`.

### 6.5 Contrastive generator

For each `SentenceExtraction`, the generator produces candidate negative tests by mutating the extraction, then filters them through Vampire.

**Six mutation operators**, each a tree-walker over `Formula`:

1. **`negate_atom`** — for each `AtomicFormula` encountered in the tree, emit a mutant with that atom's `negated` flag flipped.
2. **`swap_binary_args`** — for each binary atomic formula, emit a mutant with its two arguments swapped.
3. **`flip_quantifier`** — for each `TripartiteQuantification` node, emit a mutant with its quantifier flipped between universal and existential.
4. **`drop_restrictor_conjunct`** — for each quantification with a non-empty restrictor, emit mutants each removing one restrictor atom.
5. **`flip_connective`** — for each connective node, emit the following mutants based on the original connective:
    - `and → or` (same operands, connective replaced).
    - `or → and` (same operands, connective replaced).
    - `implies → iff` (same operand order, connective replaced).
    - `implies → implies` with operands reversed (asymmetric flip; implies is non-commutative so the reversed-operand variant is a distinct candidate).
    - `iff → implies` (same operand order; iff is commutative so no reversed variant is emitted).
   For each connective node the operator emits exactly the mutants listed for that connective's type.
6. **`replace_subformula_with_negation`** — for each non-root non-atomic sub-formula, emit a mutant wrapping that sub-formula in `Formula.negation`.

Each mutant is compiled via `compile_canonical_fol`. Vampire checks whether `(original ∧ mutant)` is unsat.

**Witness axioms.** Before each `(original ∧ mutant)` unsat check, Vampire's axiom set is augmented with witness axioms derived from the extraction's predicate declarations. For each `PredicateDecl` with arity 1 and name `P`, add `exists x.P(x)`. For each `PredicateDecl` with arity 2 and name `R`, add `exists x.exists y.R(x, y)`. These are derived mechanically from `extraction.predicates`; no hand-rolling.

This formalizes the existential import that natural-language restrictor domains carry (Barwise & Cooper 1981). Without it, universal conditionals like *"All dogs are mammals"* are compatible with empty-domain models, and structural mutations (`flip_quantifier`, `drop_restrictor_conjunct`, `negate_atom` in a restrictor) remain `sat` under free-domain semantics even though they are natural-language contradictions of the source.

Witness axioms are applied uniformly to every unsat check in the generator (§6.5) and scorer (§6.6) and invariants (§8). They are **not** applied during the two-path compile equivalence check (C9a / §8 monotonicity invariant), because that check is purely about compiler-path agreement and should not depend on domain assumptions.

**Accept only on `unsat`.** Drop on `sat`, `timeout`, or `unknown`. Every accepted contrastive is provably inconsistent with the original (under the witness axioms) — not merely different.

**Note on `flip_connective` and Vampire filtering.** The `implies → iff` and `iff → implies` mutations are often entailment-neutral in concrete interpretations; Vampire will return `sat` and the mutants will be dropped. This is expected and correct per the acceptance rule; it contributes to `dropped_neutral` in telemetry and is not by itself evidence of a permissive operator.

### 6.6 Scorer

Given a test suite (positives + contrastives) and a candidate FOL translation, the scorer calls Vampire to check:

- For each positive test `P`: does the candidate entail `P`?
- For each contrastive test `C`: does the candidate entail `C`? (It should not.)

```
recall    = (positives entailed) / (total positives)
precision = (contrastives not entailed) / (total contrastives)
SIV       = 2 · recall · precision / (recall + precision)
```

**No coverage fraction. No adjustment. Just F1.**

The scorer applies the same witness axioms as §6.5 when checking entailment and contrastive rejection, so scoring is consistent with generation.

### 6.7 Soundness invariants

Two CI-level checks. See §8 for full specification.

### Architecture diagram

```
                        ┌───────────────────────┐
                        │     NL sentence       │
                        └───────────┬───────────┘
                                    │
                                    ▼
                        ┌───────────────────────┐
                        │   6.1 Pre-analyzer    │
                        │   (spaCy)             │
                        │ requires_restrictor   │
                        │ requires_negation     │
                        └───────────┬───────────┘
                                    │
                                    ▼
                        ┌───────────────────────┐
                        │   6.3 Extractor       │
                        │   (frozen LLM)        │
                        │ JSON-schema bound     │
                        │ tripwire + retry      │
                        └───────────┬───────────┘
                                    │
                                    ▼
                        ┌───────────────────────┐
                        │   6.2 Schema          │
                        │   SentenceExtraction  │
                        │   + Formula (4 cases) │
                        └──┬─────────────────┬──┘
                           │                 │
                ┌──────────┘                 └──────────┐
                ▼                                       ▼
    ┌───────────────────────┐               ┌───────────────────────┐
    │   6.4 Compiler        │               │  6.5 Contrastive      │
    │   (two paths)         │               │      generator        │
    │ compile_sentence_     │               │ mutate + Vampire      │
    │   test_suite          │               │ accept only unsat     │
    │ compile_canonical_fol │               │                       │
    └──────────┬────────────┘               └───────────┬───────────┘
               │                                        │
               └────────────────┬───────────────────────┘
                                ▼
                        ┌───────────────────────┐
                        │      TestSuite        │
                        │ positives + contrasts │
                        └───────────┬───────────┘
                                    │
    ┌───────────────────────┐       │
    │    Candidate FOL      │──────►│
    └───────────────────────┘       │
                                    ▼
                        ┌───────────────────────┐
                        │   6.6 Scorer          │
                        │   (Vampire)           │
                        │   F1(recall,          │
                        │      precision)       │
                        └───────────────────────┘


    ┌───────────────────────┐
    │   6.7 Soundness       │  ◄┄┄┄┄┄┄┄┄ reads from Compiler (§6.4)
    │      invariants       │  ◄┄┄┄┄┄┄┄┄ reads from Generator (§6.5)
    │   CI-enforced;        │
    │   breaks build on     │
    │   violation           │
    └───────────────────────┘
```

---

## 7. Contracts

Precise interface specifications for every load-bearing component. Phase prompts reference these by name.

### C0. `UnitTest` and `TestSuite`

Defined in §6.2.6. Declared in `siv/schema.py` in Phase 1. Pydantic `model_validator` on `UnitTest` enforces `mutation_kind` non-`None` iff `kind == "contrastive"`.

### C1. `Formula`

Defined in §6.2.2.

- **Invariant (exclusivity):** exactly one of `atomic`, `quantification`, `negation`, or `(connective, operands)` is populated per instance.
- **Invariant (recursion):** `negation`, `operands` elements, and `TripartiteQuantification.nucleus` are themselves `Formula` instances; nesting depth is unbounded.
- **Validator raises `SchemaViolation` on:** zero cases populated; two or more cases populated; `connective` without `operands`; `operands` without `connective`; `implies`/`iff` with `len(operands) != 2`; `and`/`or` with `len(operands) < 2`.
- **No fifth case.** Frege's grammar is closed.

### C2. `SentenceExtraction`

Defined in §6.2.5.

- **Required fields:** `nl` and `formula`.
- **Predicate-atom invariant:** every `AtomicFormula.pred` anywhere in the `formula` tree matches the `name` of some `PredicateDecl` in `predicates`; `args` length equals that predicate's arity.
- **Argument-resolution invariant:** every `AtomicFormula.args` string resolves to (a) a declared `Entity.id` or `Constant.id`, or (b) a variable bound by an enclosing `TripartiteQuantification` or `InnerQuantification`.

### C3. `validate_extraction`

```python
def validate_extraction(extraction: SentenceExtraction) -> None: ...
```

- **Returns:** `None` on success.
- **Raises `SchemaViolation`** on: Formula exclusivity violations (C1); connective/operand arity violations (C1); predicate-atom violations (C2); argument-resolution violations (C2); a `TripartiteQuantification` with empty `restrictor` whose nucleus is a single atom over the bound variable.
- **Deterministic.** No LLM call. No network call. No randomness.

### C4. `compute_required_features`

```python
@dataclass(frozen=True)
class RequiredFeatures:
    requires_restrictor: bool
    requires_negation: bool

def compute_required_features(sentence: str) -> RequiredFeatures: ...
```

- **Input:** a sentence string.
- **Output:** a frozen `RequiredFeatures` with exactly two `bool` fields and no others.
- **Deterministic.** No LLM call. No network call.
- **Detection rules:** per §6.1.
- **Forbidden:** no modal, temporal, proportional, collective, or ontological-type flags.

### C5. `extract_sentence`

```python
def extract_sentence(sentence: str, client) -> SentenceExtraction: ...
```

- **Input:** a sentence and a frozen LLM client.
- **Output:** a validated `SentenceExtraction` satisfying C2 and C3 and passing both tripwires.
- **Retry:** at most **one** retry on `SchemaViolation` from validation or tripwire enforcement; the violation message is appended to the prompt on retry.
- **Error modes:** raises `SchemaViolation` to the caller if the retry also fails. Never returns a silently-broken extraction. No infinite loop.
- **Tripwires per §6.3.**

### C6. `compile_sentence_test_suite` and `compile_canonical_fol`

```python
def compile_sentence_test_suite(extraction: SentenceExtraction) -> TestSuite: ...
def compile_canonical_fol(extraction: SentenceExtraction) -> str: ...
```

- **Pure functions of `extraction`.** Neither consumes `nl` as input beyond what is carried inside `extraction`; the `nl` field is preserved for reporting but is not a compiler input.
- **Structurally distinct code paths** — different traversal order, different variable-naming, different string assembly. A bug in one must not propagate silently to the other.
- **Recursion** over the four `Formula` cases per §6.4.
- **Output:** NLTK-compatible ASCII FOL.
- **Bidirectional entailment invariant:** for every extraction, the conjunction of `compile_sentence_test_suite`'s positives must be bidirectionally entailing with `compile_canonical_fol`'s output under Vampire. Enforced by C9a.
- **`compile_sentence_test_suite`** emits the full canonical FOL as one positive plus a sub-entailment test for each non-trivial sub-formula (§6.4 definition).

### C7. `generate_contrastives`

```python
def generate_contrastives(
    extraction: SentenceExtraction,
    timeout_s: int = 5,
) -> tuple[list[UnitTest], TelemetryDict]: ...
```

- **Output:** list of accepted contrastive `UnitTest`s plus telemetry dict with keys `generated`, `accepted`, `dropped_neutral`, `dropped_unknown`, `unknown_rate`, `per_operator`.
- **Operators:** exactly the six in §6.5.
- **Acceptance rule:** a mutant is accepted iff Vampire proves `(original ∧ mutant ∧ witness_axioms)` is `unsat`, where `witness_axioms` is the set of `exists`-closures over `extraction.predicates` per §6.5.
- **Drop rule:** mutants whose Vampire result is `sat`, `timeout`, or `unknown` are dropped.
- **Every accepted contrastive is provably inconsistent with the original.**

### C8. `score`

```python
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

def score(test_suite: TestSuite, candidate_fol: str) -> ScoreReport: ...
```

- **Computation per §6.6.**
- **Does not return a coverage fraction.** No scope-adjustment term.
- **Uses Vampire with witness axioms (§6.5)** to check each positive (should entail) and each contrastive (should not entail).

### C9a. `check_entailment_monotonicity`

```python
def check_entailment_monotonicity(
    extraction: SentenceExtraction,
    test_suite: TestSuite,
) -> tuple[bool, Optional[str]]: ...
```

- **Semantics:** with `P` = conjunction of `test_suite`'s positives and `Q` = `compile_canonical_fol(extraction)`, Vampire-check both `P ⊨ Q` and `Q ⊨ P`.
- **Returns `(True, None)`** iff both directions proved.
- **Returns `(False, reason)`** if either direction fails, times out, or returns unknown. **Timeout is a failure, not a skip.**
- **Witness axioms are NOT applied.** The bidirectional entailment check runs without them; it is a pure compiler-path equivalence check and must not depend on domain assumptions.

### C9b. `check_contrastive_soundness`

```python
def check_contrastive_soundness(
    test_suite: TestSuite,
) -> tuple[bool, Optional[str]]: ...
```

- **Semantics:** with `P` = conjunction of positives, for each contrastive `C`, Vampire-check that `(P ∧ C)` is `unsat`.
- **Returns `(True, None)`** iff every contrastive is unsat against the positives.
- **Returns `(False, reason)`** on the first `C` that is `sat`, `timeout`, or `unknown`. **Timeout is a failure, not a skip.**
- **Witness axioms ARE applied** to the `(P ∧ C)` unsat check, matching the generator's acceptance rule (§6.5).

---

## 8. Soundness invariants

Two CI-level checks run on every compiled test suite during continuous integration and fail the build on violation:

1. **Entailment monotonicity (C9a).** For every extraction, the conjunction of its positive tests must be bidirectionally equivalent (via Vampire) to the formula produced by `compile_canonical_fol`. This catches bugs where the two compilation paths disagree.

2. **Contrastive soundness (C9b).** For every contrastive test, Vampire must prove it inconsistent with the positive tests. This catches any entailment-neutral mutants the generator's filter missed.

Both invariants run against a curated corpus of sentences checked into the repository (see Phase 4). The corpus covers all four `Formula` cases — bare atoms, quantifications, negations, connectives — plus nestings thereof.

The claim "SIV is sound" is only defensible if soundness is mechanically checked on every build. Without these invariants, soundness is an assertion that degrades every time someone touches the compiler. With them, soundness is a property CI enforces.

---

## 9. Dependencies

The complete list:

- **spaCy** (pre-analyzer).
- **Pydantic** (schema definition and validation).
- **OpenAI API client** (extractor; frozen LLM snapshot).
- **Vampire** (theorem prover; used by generator, scorer, and invariants).
- **NLTK-compatible FOL string format** (compiler output convention).
- **pytest** (invariant CI harness).

Any dependency not on this list requires a deliberate decision and an update to this document. No WordNet, no PMI, no FraCaS corpus, no rejection taxonomy, no embedding models, no fine-tuning.

---

## 10. Modes of operation

SIV has two modes, sharing all seven components above.

### 10.1 Evaluator

**Input:** a dataset of (sentence, candidate FOL) pairs — typically a benchmark like FOLIO with gold annotations, or a model's predicted translations.

**Process:** for each pair, run the full pipeline and produce a per-sentence score plus the passing/failing test breakdown.

**Output:** aggregate F1 across the dataset, plus per-sentence reports.

### 10.2 Generator (Clean-FOLIO)

**Input:** natural language sentences only.

**Process:** run the pipeline through compilation to produce a canonical FOL translation for each sentence. Verify each translation against its own test suite as a self-consistency check.

**Output:** a cleaned dataset — the same sentences as FOLIO, with canonical formula-structured FOL translations.

See §20 (Deferred decisions) for a known open question about whether §10.2 should eventually include an LLM-driven translation step that consumes `nl` alongside the extraction. For Phases 1–6, Clean-FOLIO uses `compile_canonical_fol` output; the open question revisits post-Phase-5.

---

## 11. Phase plan — how to execute this refactor

Seven phases. Each phase is one commit and one review gate. Do not merge a phase until its gate passes. Do not merge two phases into one commit.

| Phase | Implements | Touches | Gate |
|-------|-----------|---------|------|
| 0 | Revert + docs | `docs/`, `reports/archive/` | Repo at `v1-final` + canonical doc; v1 test suite green |
| 1 | Schema (`Formula` + tripartite + `TestSuite`/`UnitTest`) + recursive compiler | `schema.py`, `compiler.py`, `json_schema.py` | All nine Formula-case tests pass; two-path equivalence via Vampire |
| 2 | Pre-analyzer + extractor + prompts | `pre_analyzer.py`, `extractor.py`, `prompts/` | Live round-trip ≥ 12/14 |
| 3 | Contrastive + scorer | `contrastive_generator.py`, `scorer.py` | Telemetry thresholds met on 14 examples |
| 4 | Invariants in CI | `invariants.py`, CI config | Invariants green on 22-sentence corpus; deliberate-bug test catches it |
| 5 | FOLIO validation | `scripts/run_folio_evaluation.py` | F1 ≥ 0.85 on target class; per-Formula-case breakdown reported |
| 6 | Cleanup + release | README, CHANGELOG | Forbidden grep returns zero |

### Ground rules (apply to every phase)

1. **Every change traces to this document.** No change exists that cannot cite a section here.
2. **One phase, one commit, one review gate.** A phase does not merge until its gate is green.
3. **Pydantic models are the source of truth for all schemas.** The JSON Schema passed to the LLM is derived. Hand-rolled JSON Schemas are forbidden.
4. **Forbidden concepts stay forbidden.** §5 is the authoritative negative list. No phase introduces anything on it.
5. **Rename cleanly, never alias.** If a symbol is renamed, every call site is updated in the same commit. No `X = Y` backward-compatibility aliases.
6. **Failing tests are information.** Do not loosen assertions to pass tests; fix the underlying issue or escalate.
7. **The `Formula` type is the complete grammar.** Frege's five constructs (atomic predications, boolean connectives AND/OR/NOT/IMPLIES/IFF, quantifiers ∀/∃, variables, constants) are represented via the four `Formula` cases plus entity/constant declarations. No fifth `Formula` case is ever added. If a sentence appears to need one, it is either expressible in the four existing cases or outside FOL.
8. **Narrow out-of-scope fixes are permitted when a gate is structurally unreachable.** If a phase's gate is unreachable due to a bug in a file not listed in the phase's "files touched," the agent may make a narrow, targeted fix in a separate commit that precedes the phase's main commit. The fix must be minimal (no scope expansion), must include a test demonstrating the bug, and must be surfaced in the completion report. The agent does not make such fixes silently and does not expand them beyond what the gate requires. If the fix would be non-trivial (e.g., requires restructuring), the agent stops and surfaces instead of fixing.

### Escalation rule (applies to every phase)

If anything in a phase prompt contradicts this document, or a required implementation choice is ambiguous, or an exact token (enum value, field name, file path, function name) cannot be confirmed against this document or the v1 codebase — **stop and surface** the contradiction or ambiguity to the user before proceeding. Do not guess. Do not loosen requirements to get unstuck.

### If something goes wrong mid-refactor

- **A gate fails.** Stop. Do not merge. Diagnose. Passing the gate is the minimum bar for the phase's correctness; missing it means the phase is not ready.
- **A drift issue surfaces.** Audit before patching. Drift is always "two components disagree about a concept and nothing checks they agree." The fix is always "make one of them the source of truth and derive or verify the other from it."
- **A forbidden concept feels necessary.** It isn't. If you genuinely believe it is, update §5 of this document first (with written rationale) and only then adjust the plan.
- **A sentence appears to need a fifth `Formula` case.** It doesn't. Frege's grammar is closed. The sentence is either expressible in the four existing cases or outside FOL. *"Only X are Y"* is `∀x.(Y(x) → X(x))`, not a new "only" construct.
- **A phase is larger than anticipated.** Split it and update this document before proceeding.
- **The generator produces too many contrastive mutants.** Cap at a fixed number per sentence (e.g., 50) and log the cap hit; do not silently drop operators or restrict the tree walk.

---

## 12. Phase 0 prompt

```
You are executing Phase 0 of the SIV refactor.

Before doing anything, read in full:
- SIV.md §1–§5 (what SIV is and is not, principles, scope, forbidden list).
- SIV.md §11 (phase plan, ground rules, escalation rule).
- SIV.md §12 (this prompt).

Goal: Return the repository to the last clean v1 state, with SIV.md in place as the single canonical specification for everything that follows.

Files touched:
- Create tag: v1-final.
- Create branch: v2-from-clean.
- Create: docs/SIV.md (the single canonical document).
- Move (if they exist from any archived v2 work): any baseline_audit.csv, baseline_audit_summary.json, drift_audit.md, compiler_state_audit.md → reports/archive/.
- Move (if exists): any prior v1 master document → docs/archive/v1_master_document.md.
- Archive (do not delete) any prior v2-era plan files: move to docs/archive/ preserving their filenames.

What to do:

1. Identify the last commit where `pytest tests/` is fully green. This is the v1-final base. Notes:
   - If a commit appears to be v1 but its own change introduces a test-suite failure (for example, a commit whose message suggests it is the final v1 state but whose diff violates an existing test invariant), that commit is not v1-final. Walk back commit-by-commit until `pytest tests/` is green, and report the bisect trail.
   - A real instance: commit 5266902 ("added nl to generation process") on the reference codebase introduces nl into the generator's LLM prompt and fails test_generator_does_not_include_nl_in_prompt. This commit must not be v1-final. Walk back.

2. Tag the identified commit as v1-final.

3. Create branch v2-from-clean from v1-final. All subsequent phases commit to this branch.

4. Place docs/SIV.md on the branch. This is the single canonical specification. Do not place multiple architecture documents; if prior documents (SIV_Philosophy.md, SIV_Master_Document.md, SIV_Refactor_Plan.md, SIV_v2_Development_Spec.md) exist in the repo, move them to docs/archive/. SIV.md supersedes all of them.

5. If a v1 master document exists in the repo root or elsewhere under a different name, move it to docs/archive/v1_master_document.md. Do not delete.

6. Move any audit files from any archived v2 work (baseline_audit.csv, baseline_audit_summary.json, drift_audit.md, compiler_state_audit.md) into reports/archive/. If none exist, skip this step and report it as a no-op.

7. Archive (do not delete) any untracked v2-era plan files at the repo root by moving them to docs/archive/ with descriptive names. Untracked files lost to rm are unrecoverable; archival is cheaper than regret.

8. Create reports/archive/phase_0_notes.md recording: any commits excluded from v1-final and why (cite the specific test that failed), the bisect trail, the final v1-final sha, and the list of archived files and their new locations.

9. Commit the Phase 0 work as a single commit on v2-from-clean. Message: "Phase 0: tag v1-final, establish v2-from-clean branch, install canonical SIV.md."

Forbidden moves:
- Do not modify any code in siv/ or tests/ during this phase. Phase 0 is revert plus docs only.
- Do not delete untracked v2-era artifacts; archive them.
- Do not add anything from SIV.md §5 forbidden list to any file.
- Do not skip the phase_0_notes.md record; Phase 2 and later phases may need this history.

Tests required: no new tests. The existing v1 test suite must pass unmodified on v2-from-clean at HEAD.

Gate:
- Tag v1-final applied to a commit where `pytest tests/` is fully green.
- Branch v2-from-clean exists, based on v1-final, and contains docs/SIV.md.
- `pytest tests/` on v2-from-clean at HEAD is green.
- reports/archive/phase_0_notes.md exists and records the bisect trail (if any) and the excluded-commit reasoning.
- `git log --oneline` on v2-from-clean shows v1 history up to v1-final plus the Phase 0 documentation commit.

If anything in this prompt contradicts SIV.md, stop and surface. If a required implementation choice is ambiguous — for example, multiple candidate v1-final commits appear green — stop and ask. Do not guess.
```

---

## 13. Phase 1 prompt

```
You are executing Phase 1 of the SIV refactor. The codebase is at the state Phase 0 left it in: v1-final tagged on a green v1 commit; branch v2-from-clean contains docs/SIV.md.

Before writing any code, read:
- SIV.md §6.2 (Schema) in full.
- SIV.md §6.4 (Compiler) in full.
- SIV.md §7 (Contracts C0, C1, C2, C3, C6).
- SIV.md §8 (Soundness invariants — for context on the two-path requirement).
- SIV.md §11 (ground rules, escalation rule).

Goal: Implement the Formula-based schema and the recursive two-path compiler. This is the foundational change; everything else builds on it.

Files touched:
- siv/schema.py — full rewrite.
- siv/compiler.py — full rewrite.
- siv/json_schema.py — NEW file; derives API-level JSON Schema from the Pydantic model.
- tests/test_schema.py — full rewrite.
- tests/test_compiler.py — full rewrite.
- Everything else in siv/ — LEFT ALONE. Modules in siv/ that import the old schema or compiler WILL BREAK after this commit. This is expected. pre_analyzer, extractor, frozen_client, contrastive_generator, scorer, invariants are fixed in Phases 2, 3, and 4. Do not patch them here. If pytest collection errors on import, scope the run to `pytest tests/test_schema.py tests/test_compiler.py` for the Phase 1 gate; do not "fix" other tests to make full-suite collection work.

What to implement:

1.1 — Schema models, exactly as follows (no rename, no added fields, no reordered semantics):

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
    pred: str
    args: List[str]
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

class UnitTest(BaseModel):
    fol: str
    kind: Literal["positive", "contrastive"]
    mutation_kind: Optional[str] = None

class TestSuite(BaseModel):
    extraction: SentenceExtraction
    positives: List[UnitTest] = []
    contrastives: List[UnitTest] = []

Forward references require model_rebuild() calls at module bottom. Enforce the UnitTest invariant (mutation_kind non-None iff kind == "contrastive") via a Pydantic model_validator on UnitTest.

1.2 — Validation. Implement validate_extraction(extraction: SentenceExtraction) -> None raising SchemaViolation for any of:
- A Formula with zero or more than one case populated.
- A Formula with connective populated but operands empty/missing/wrong arity (implies/iff are binary; and/or are n-ary with >= 2 operands).
- A Formula with operands populated but connective absent.
- An AtomicFormula whose pred does not match any declared PredicateDecl.name.
- An AtomicFormula whose args length differs from the referenced predicate's arity.
- An AtomicFormula whose arg references a variable or constant not in scope (variables in scope within the quantification that binds them; constants globally).
- A TripartiteQuantification with empty restrictor AND nucleus is a single atom over the bound variable.

1.3 — JSON Schema derivation. Implement siv/json_schema.py::derive_extraction_schema() -> dict returning an OpenAI-compatible JSON Schema derived from SentenceExtraction.model_json_schema(). Inline $ref/$defs, set additionalProperties: false on every object, mark every property required (null via union types), strip title/description/default. This function is the single API-level schema. Hand-rolled JSON Schemas forbidden anywhere in the codebase.

1.4 — Recursive compiler. Two entry points in siv/compiler.py:
- compile_sentence_test_suite(extraction) -> TestSuite
- compile_canonical_fol(extraction) -> str

Both are recursive over Formula; both are pure functions of the extraction (do NOT read nl). The two entry points must be structurally distinct code paths — different traversal order, different variable-naming, different string-assembly — so a bug in one does not silently propagate to the other.

Skeleton:

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

Compilation rules per SIV.md §6.4:
- Atomic → Pred(args...) or -Pred(args...) if negated.
- Negation → -(<compiled operand>).
- Connective and → operands joined with &.
- Connective or → operands joined with |.
- Connective implies → (A -> B), binary.
- Connective iff → (A <-> B), binary.
- Quantification universal → all x.(⋀restrictor -> compile(nucleus)).
- Quantification existential → exists x.(⋀restrictor & compile(nucleus)).

Inner quantifications (per SIV.md §6.2.3 and §6.4) wrap the restrictor conjunction in declaration order, innermost-last. For an outer universal over x with restrictor R, nucleus N, and a single existential InnerQuantification on y:
    all x.(exists y.(⋀R) -> compile(N))
For an outer existential:
    exists x.(exists y.(⋀R) & compile(N))
Multiple inner quantifications nest left-to-right in declaration order. Inner quantifiers scope inside the restrictor only; the nucleus handles its own quantifications via its own Formula.

If a sentence appears to need a different inner-quantification scoping, STOP and surface rather than guess.

Non-trivial sub-formula definition (for compile_sentence_test_suite): every quantification node, every negation node, every connective node, plus every atomic node that appears as a top-level restrictor conjunct or as the top-level nucleus atom. Leaf atoms already present as arguments of a parent connective or quantification do NOT generate their own sub-entailment test.

Output format: NLTK-compatible ASCII only: all x.(P(x) -> Q(x)), exists x.(P(x) & Q(x)), -P(x), (A & B), (A | B), (A -> B), (A <-> B).

Forbidden moves (from SIV.md §5):
- No is_fol_expressible, rejection_reason, rejection_note, FOLRejectionReason, coverage_fraction, is_collective, detected_modal, detected_temporal, detected_proportional, proportional_quantifier, PROPORTIONAL_QUANTIFIER, or plural_non_distributive.
- No ontological type values (person, animal, place) in Entity.type or Constant.type. Type is grammatical.
- No hand-rolled JSON Schema.
- No backward-compatibility aliases for renamed v1 symbols.
- No fifth Formula case under any name.
- Compiler does NOT consume nl.

Tests required.

tests/test_schema.py:
- Every validator has positive and negative cases.
- Every SchemaViolation listed in 1.2 has a dedicated test.
- A test that JSON Schema derivation is deterministic across runs (byte-identical output for same input).

tests/test_compiler.py — exactly these nine cases:
1. Atomic: "Miroslav Venhoda was a Czech choral conductor" → CzechChoralConductor(miroslav).
2. Quantification (the employees-meetings bug-killer): "All employees who schedule meetings attend the company building" → all x.(Employee(x) & exists y.(Meeting(y) & Schedule(x, y)) -> exists z.(CompanyBuilding(z) & Attend(x, z))) or semantic equivalent with populated restrictor on the left of the implication.
3. Negation: "Smith is not a Czech conductor" → -CzechConductor(smith).
4. Connective-and: "Alice is tall and Bob is short" → (Tall(alice) & Short(bob)).
5. Connective-or: "The L-2021 monitor is either used in the library or has a type-c port" → (UsedIn(monitor, library) | HasTypeC(monitor)) (with appropriate atomic decomposition).
6. Connective-implies: "If it rains, then the ground is wet" → (Rains(weather) -> Wet(ground)). `weather` and `ground` are declared as `Constant`. Per Principle 2, "It rains" decomposes as `Rains(weather)` with `weather` as an event constant (Parsons 1990); arity stays `Literal[1, 2]`.
7. Connective-iff: "Archie can walk if and only if he has functional brainstems" → (CanWalk(archie) <-> HasFunctionalBrainstems(archie)).
8. Nested case: "If a legislator is found guilty, they will be suspended" → all x.(Legislator(x) -> (exists y.(Theft(y) & FoundGuilty(x, y)) -> Suspended(x))) or semantic equivalent.
9. Quantifier in connective: "If the forecast calls for rain, then all employees work from home" — top-level connective=implies whose antecedent is atomic and whose consequent is a quantification. Expected FOL semantic shape: (ForecastRain(weather) -> all x.(Employee(x) -> WorkFromHome(x))) or semantic equivalent. `weather` declared as `Constant`.

Two-path equivalence test: for each of the nine cases, call both compile_sentence_test_suite and compile_canonical_fol on the same extraction and use Vampire to verify bidirectional entailment of their outputs. This is the live Phase 1 exercise of the §8 soundness invariant.

Gate:
- All schema and compiler tests pass.
- All nine Formula-case tests produce correct FOL.
- Vampire-based bidirectional-entailment test passes on every test case.
- Line count of siv/compiler.py under 400.

Report on completion:
- Merge commit sha.
- Line count of siv/compiler.py.
- Vampire bidirectional-entailment result across all nine cases.
- Any ambiguity surfaced (you should be surfacing more than deciding at this stage).

Explicit non-goals:
- No extractor, no pre-analyzer, no contrastive generator, no scorer. Later phases.
- No few-shot examples file. Phase 2.

If anything in this prompt contradicts SIV.md, stop and surface. If a required implementation choice is ambiguous, stop and ask. Do not guess and do not loosen requirements.
```

---

## 14. Phase 2 prompt

```
You are executing Phase 2 of the SIV refactor. The codebase is at the state Phase 1 left it in: new schema and compiler live; pre_analyzer, extractor, frozen_client, contrastive_generator, scorer, invariants are broken because they import the old schema.

Before writing any code, read:
- SIV.md §6.1 (Pre-analyzer) and §6.3 (Extractor).
- SIV.md §7 (Contracts C4, C5).
- SIV.md §5 (forbidden concepts).
- SIV.md §11 (ground rules, escalation rule).

Goal: Implement the deterministic pre-analyzer and the extractor with JSON-schema binding and tripwire enforcement.

Files touched:
- siv/pre_analyzer.py — rewrite.
- siv/extractor.py — rewrite.
- siv/frozen_client.py — update response_format binding to use derive_extraction_schema() from Phase 1.
- prompts/extraction_system.txt — rewrite.
- prompts/extraction_examples.json — rewrite.
- tests/test_pre_analyzer.py, tests/test_extractor.py, tests/test_extraction_roundtrip.py — rewrite or create.
- Other broken modules (contrastive_generator.py, scorer.py, invariants.py) — LEFT ALONE. Fixed in Phases 3 and 4.

What to implement:

2.1 — Pre-analyzer. Implement compute_required_features(sentence: str) -> RequiredFeatures where RequiredFeatures is a frozen dataclass with exactly two bool fields: requires_restrictor, requires_negation. No other fields. No modal/temporal/proportional/collective/ontological detection.

Detection rules (per SIV.md §6.1):
- requires_restrictor: any subject-NP token has dep_ == "relcl", OR the sentence matches regex ^(all|every|each|no|any)\s+\w+\s+(who|that|which)\b (case-insensitive).
- requires_negation: lemma no|none|never|neither appears, OR neg dependency on the main verb.

Deterministic. No LLM call. No network call.

2.2 — Extractor. Implement extract_sentence(sentence, client) -> SentenceExtraction:

- Call the frozen LLM with the system prompt, few-shot examples, and the sentence. Pass derive_extraction_schema() as response_format.
- Parse the response into a SentenceExtraction via Pydantic.
- Run validate_extraction from Phase 1.
- Compute RequiredFeatures via compute_required_features and enforce tripwires:
  - If requires_restrictor=True: walk the formula tree for at least one TripartiteQuantification with non-empty restrictor. If none, raise SchemaViolation("restrictor required but missing").
  - If requires_negation=True: walk the formula tree for at least one negation occurrence — a Formula.negation node OR an AtomicFormula with negated=True — anywhere in the tree, including inside connectives, inside quantification nuclei, and inside quantification restrictors. If none, raise SchemaViolation("negation required but missing").
- On any SchemaViolation, retry ONCE with the violation message appended to the system prompt.
- If the retry also fails, raise to caller. No second retry. No infinite loop.

The tripwire tree-walk is recursive, mirroring the compiler's recursion. Implement a helper _walk_formula(f: Formula, visitor) and use it for both tripwires.

2.3 — System prompt. prompts/extraction_system.txt:
- Under 1000 tokens.
- Describes the schema neutrally.
- No reasoning steps, no soft hedges, no commentary on rationale.
- Points to examples as the authoritative pattern.
- Explicitly describes the four Formula cases (atomic, quantification, negation, connective). Schema fragment plus one-sentence descriptions of each case; examples carry the pattern-matching burden.

2.4 — Few-shot examples. prompts/extraction_examples.json: exactly fourteen examples covering the four Formula cases and their common combinations:

1. Atomic — "Miroslav Venhoda was a Czech choral conductor."
2. Atomic with binary relation — "Alice taught Bob."
3. Simple universal — "All dogs are mammals." (top-level quantification)
4. Restricted universal (the bug-killer) — "All employees who schedule meetings attend the company building." (top-level quantification with populated restrictor)
5. Existential — "Some student read a book." (top-level quantification, existential)
6. Nested universal — "Every student who takes a class that is taught by a professor passes."
7. "No X is Y" — "No dog is a cat." (universal with single negated atom in nucleus)
8. "Only X are Y" — "Only managers attend the meeting." (universal: ∀x.(Attend(x) → Manager(x)))
9. Connective-and — "Alice is tall and Bob is short."
10. Connective-or — "The L-2021 monitor is either used in the library or has a type-c port."
11. Connective-implies — "If it rains, the ground is wet."
12. Connective-iff — "Archie can walk if and only if he has functional brainstems."
13. Sentential conditional with quantifier consequent — "If the forecast calls for rain, then all employees work from home."
14. Negation of a compound — "It is not the case that Alice is tall and Bob is short."

All examples use "type": "entity" uniformly. No "person"/"animal"/"place".

Forbidden moves:
- No fields on RequiredFeatures beyond the two bools.
- No modal/temporal/proportional/collective detection.
- No ontological type values in examples.
- No is_fol_expressible/rejection_reason/rejection_note/FOLRejectionReason anywhere.
- No scope classification or out-of-scope handling. If the LLM returns an extraction for a modal sentence, process it like any other.
- No second retry, third retry, or infinite loop.
- No hand-rolled JSON Schema; use derive_extraction_schema().
- No backward-compatibility aliases.

Tests required.

tests/test_pre_analyzer.py: at least two positive and two negative cases for each of the two flags.

tests/test_extractor.py (mocked LLM):
- Validation failure triggers one retry.
- Tripwire failure (missing restrictor; missing negation) triggers one retry.
- Both retries failing raises SchemaViolation to the caller.
- One test per Formula case confirming the tripwire walks the tree: a negation buried inside a connective must satisfy requires_negation.

tests/test_extraction_roundtrip.py (live LLM, @pytest.mark.requires_llm):
- Parametrized over all fourteen examples.
- Each example's extraction from the live LLM must be semantically equivalent to the gold extraction: same predicates modulo renaming, same Formula tree structure modulo commutativity of and/or.

Gate:
- All mocked tests pass.
- Live round-trip ≥ 12/14 when run with OPENAI_API_KEY. Below 12/14, iterate on prompt/examples; do not loosen the equivalence check.
- Manual smoke: `python -m siv extract "All employees who schedule meetings attend the company building."` returns an extraction whose formula contains a TripartiteQuantification with populated restrictor containing the Schedule atom.

Explicit non-goals:
- No out-of-scope handling.
- No contrastive generator, scorer, or invariants.

If anything in this prompt contradicts SIV.md, stop and surface. Do not guess, do not loosen.
```

---

## 15. Phase 3 prompt

```
You are executing Phase 3 of the SIV refactor. The codebase is at the state Phase 2 left it in: schema, compiler, pre-analyzer, extractor live. contrastive_generator.py, scorer.py, invariants.py are still broken or stale.

Before writing any code, read:
- SIV.md §6.5 (Contrastive generator) and §6.6 (Scorer).
- SIV.md §7 (Contracts C7, C8).
- SIV.md §5 (forbidden concepts).
- SIV.md §11 (ground rules).

Goal: Implement the mutation-based contrastive generator with Vampire filtering, and the scorer that produces the F1 metric.

Files touched:
- siv/contrastive_generator.py — new file (replace any v1 stub).
- siv/scorer.py — new file (replace any v1 stub).
- siv/vampire_interface.py — already exists from v1; confirm or update contract to: (fol_a: str, fol_b: str, check: Literal["unsat", "entails"]) -> Literal["sat", "unsat", "timeout", "unknown"].
- tests/test_contrastive_generator.py — new.
- tests/test_scorer.py — new.
- siv/invariants.py — LEFT ALONE. Fixed in Phase 4.

What to implement:

3.1 — Six mutation operators in siv/contrastive_generator.py. Each is a tree-walker over Formula, recursing and emitting mutants at every applicable node:

1. negate_atom: for each AtomicFormula, emit a mutant with negated flag flipped.
2. swap_binary_args: for each binary atomic formula, emit the arg-swapped variant.
3. flip_quantifier: for each TripartiteQuantification, emit a mutant with quantifier flipped.
4. drop_restrictor_conjunct: for each quantification with non-empty restrictor, emit one mutant per removed restrictor atom.
5. flip_connective: for each connective node, emit mutants by type:
   - and → or (same operands, connective replaced).
   - or → and (same operands, connective replaced).
   - implies → iff (same operand order, connective replaced).
   - implies → implies with operands reversed (asymmetric flip).
   - iff → implies (same operand order; no reversed variant since iff is commutative).
6. replace_subformula_with_negation: for each non-root non-atomic sub-formula, emit a mutant wrapping it in Formula.negation.

Each operator produces a list of SentenceExtraction mutants carrying mutation_kind: str equal to the operator name.

Note (expected Vampire behavior, not a telemetry failure): implies → iff and iff → implies are often entailment-neutral in concrete interpretations; Vampire returns sat and the mutants are dropped. This contributes to dropped_neutral and is correct per the acceptance rule.

3.2 — Vampire-filtered acceptance. Implement:

def generate_contrastives(
    extraction: SentenceExtraction,
    timeout_s: int = 5,
) -> tuple[list[UnitTest], TelemetryDict]: ...

For each mutant: compile mutant via compile_canonical_fol; compile original via compile_canonical_fol; ask Vampire whether (original ∧ mutant) is unsat. Accept only on unsat. Drop on sat, timeout, or unknown.

TelemetryDict keys: generated, accepted, dropped_neutral, dropped_unknown, unknown_rate, per_operator (breakdown by operator name).

Wire generate_contrastives into compile_sentence_test_suite so the returned TestSuite has a populated contrastives list.

3.3 — Scorer. siv/scorer.py::score(test_suite, candidate_fol) -> ScoreReport:

- For each positive: Vampire-check candidate entails it.
- For each contrastive: Vampire-check candidate entails it (should not).
- recall = positives_entailed / positives_total.
- precision = contrastives_rejected / contrastives_total.
- f1 = 2·recall·precision / (recall + precision).
- No coverage fraction. No adjustment.

Return ScoreReport with: recall, precision, f1, positives_entailed, positives_total, contrastives_rejected, contrastives_total, per_test_results.

Forbidden moves:
- No coverage fraction or scope-aware scoring.
- No seventh mutation operator. The six are exhaustive.
- No silent operator dropping if mutant counts grow large. If compute requires a per-sentence cap, implement it as an explicit numeric cap and log the cap hit; do not restrict the tree walk.
- No accepting sat/timeout/unknown mutants.
- No backward-compatibility aliases.

Tests required.

tests/test_contrastive_generator.py:
- One test per operator confirming structural output. Tree-walking matters: replace_subformula_with_negation on (A and B) produces THREE mutants (negate A, negate B, negate whole conjunction), not one.
- swap_binary_args on a symmetric predicate (e.g., a sibling relation) produces a mutant Vampire rejects as neutral (sat).
- swap_binary_args on an asymmetric predicate (e.g., Schedule(person, event)) produces a mutant Vampire accepts as contrastive (unsat).
- flip_connective on a disjunction produces a conjunction Vampire confirms inconsistent with the original in at least one context.
- generate_contrastives on each of the fourteen Phase 2 examples produces a non-empty, all-unsat-verified negatives list. Fourteen tests, one per example.

tests/test_scorer.py:
- Perfect candidate gives F1 = 1.0.
- Candidate missing a positive gives expected recall drop.
- Candidate entailing a contrastive gives expected precision drop.

Gate:
- All tests pass.
- Telemetry on the fourteen Phase 2 examples: unknown_rate < 0.2 and accepted / generated > 0.3. If either fails, investigate before proceeding.
- employees-meetings test suite has populated positives AND populated contrastives; canonical FOL scores 1.0 on its own test suite.

Explicit non-goals:
- No CI invariant harness. Phase 4.
- No FOLIO-scale evaluation. Phase 5.

If anything contradicts SIV.md, stop and surface. Do not guess, do not loosen.
```

---

## 16. Phase 4 prompt

```
You are executing Phase 4 of the SIV refactor. The codebase is at the state Phase 3 left it in: full pipeline from pre-analyzer through scorer is live.

Before writing any code, read:
- SIV.md §8 (Soundness invariants).
- SIV.md §7 (Contracts C9a, C9b).
- SIV.md §5 (forbidden concepts).
- SIV.md §11 (ground rules).

Goal: Enforce soundness mechanically on every build.

Files touched:
- siv/invariants.py — rewrite (add the two functions).
- tests/test_soundness_invariants.py — new file.
- tests/data/invariant_corpus.json — new file, curated sentences.
- CI configuration (.github/workflows/ or equivalent) — ensure invariant tests run on every PR.

What to implement:

4.1 — Invariants.

def check_entailment_monotonicity(extraction, test_suite) -> tuple[bool, Optional[str]]:
    Let P = conjunction of test_suite positives.
    Let Q = compile_canonical_fol(extraction).
    Vampire-check both P ⊨ Q and Q ⊨ P.
    Return (False, reason) if either direction fails, times out, or returns unknown. Timeout = failure.
    Return (True, None) iff both directions proved.

def check_contrastive_soundness(test_suite) -> tuple[bool, Optional[str]]:
    Let P = conjunction of positives.
    For each contrastive C: check (P ∧ C) is unsat via Vampire.
    Return (False, reason) on the first failure (sat, timeout, or unknown). Timeout = failure.
    Return (True, None) iff every contrastive is unsat against P.

4.2 — Invariant corpus. tests/data/invariant_corpus.json contains the fourteen Phase 2 examples PLUS at least eight additional in-scope sentences exercising patterns the examples don't cover. Required additional patterns (each present at least once):

- Nested quantification with both universal and existential at different scopes.
- Connective containing a quantification that itself contains a connective (e.g. "If it rains, then every employee who is remote and every employee who is in-person works from home").
- Disjunction with three operands.
- Deeply nested negations (triple-negation or negation-of-implication).
- A biconditional between two quantified statements.
- A ground fact as an atomic formula with two constants.
- A universal whose nucleus is a disjunction.
- A universal whose restrictor draws from an inner existential that itself contains a connective.

Corpus total: at least 22 sentences.

4.3 — Tests. tests/test_soundness_invariants.py:
- Both invariants pass on every corpus entry.
- Deliberately-broken test: modify the compiler in a test-only way to produce a subtly-wrong positive (e.g., off-by-one universe), confirm monotonicity catches it, restore. This proves the invariant is load-bearing.

4.4 — CI wiring: invariant tests run on every PR; failure fails the build.

Forbidden moves:
- Timeout is not a pass, skip, or warning. Timeout = failure.
- Unknown is not a pass. Unknown = failure.
- No reducing the corpus below 22 or skipping any required additional pattern.
- No modifying the compiler to make the deliberately-broken test unnecessary; the test must exercise a real bug.
- No "soundness bypass" flag or environment variable.

Gate:
- Both invariants green on the full 22-sentence corpus.
- CI configured and verified to fail the build on invariant violation. Verify by pushing a throwaway branch with an intentional bug and confirming the CI run fails.

If anything contradicts SIV.md, stop and surface. Do not guess, do not loosen.
```

---

## 17. Phase 5 prompt

```
You are executing Phase 5 of the SIV refactor. The codebase is at the state Phase 4 left it in: full pipeline live, invariants enforced in CI.

Before writing any code, read:
- SIV.md §1–§4 (what SIV is, is not, principles, scope).
- SIV.md §10.1 (Evaluator mode).
- SIV.md §5 (forbidden concepts).
- SIV.md §11 (ground rules).

Goal: Measure how well the system handles real FOLIO premises. This is the empirical validation underwriting the paper's claims.

Files touched:
- scripts/run_folio_evaluation.py — new.
- reports/folio_agreement.json — new output.

What to implement:

1. Load the public FOLIO dataset (premises only; this phase does not evaluate conclusions).
2. For each premise, run the full pipeline: extract → compile → generate contrastives → score against FOLIO's gold FOL as the candidate.
3. Aggregate:
   - Mean F1 across all premises.
   - F1 distribution (histogram).
   - Per-Formula-case breakdown: F1 restricted to premises whose top-level Formula case is atomic, quantification, connective, negation respectively.
   - Premises where F1 < 0.5 (manual review list).
   - Premises where extraction failed (manual review list).
4. Write reports/folio_agreement.json with the aggregates.

Forbidden moves:
- No coverage fraction in the report.
- No claim about sentences outside the FOL-translatable class. A genuinely modal or proportional premise reports whatever F1 it reports with no commentary categorizing it as "out of scope."
- No is_fol_expressible filter to skip premises.
- No scope-aware F1 adjustment.
- No scope-rejection taxonomy for extraction failures. Failures are categorized for manual review only as "user-scope issue" (real sentence SIV cannot handle) or "actionable bug." This binary categorization does not affect reported F1.
- Do not modify the pipeline in this phase. Phase 5 is measurement only. If measurement reveals a bug, STOP and surface rather than patch silently.

Tests required: no new tests mandated; the existing suite must remain green. The script and its numbers are the deliverable.

Gate:
- Script runs to completion on the full FOLIO dataset (300 premises).
- Mean F1 on the employees-meetings class (universal-with-restrictive-relative) ≥ 0.85. Headline empirical claim: the system handles the v1 bug class.
- Mean F1 on atomic (ground) predications ≥ 0.90.
- Mean F1 on connective-only sentences ≥ 0.80.
- Extraction failure rate documented; failures manually reviewed and categorized; categorization recorded in reports/folio_agreement.json.

If a threshold misses: stop, surface the result with diagnosis (which Formula case, which premises). Do not loosen the threshold. Do not move to Phase 6.

After Phase 5 completes, also revisit the Deferred Decisions list in SIV.md §20 — in particular, the open question on whether §10.2 Clean-FOLIO should use an LLM translation step. Inspect Phase 5 sample outputs and the F1 per-case breakdown for evidence on this; do not act on it within Phase 5, but surface findings as a note for the user.

If anything contradicts SIV.md, stop and surface. Do not guess, do not loosen.
```

---

## 18. Phase 6 prompt

```
You are executing Phase 6 of the SIV refactor. The codebase is at the state Phase 5 left it in: full pipeline validated on FOLIO; reports/folio_agreement.json written.

Before writing any code, read:
- SIV.md §5 (forbidden concepts).
- SIV.md §9 (dependencies).
- SIV.md §11 (ground rules).

Goal: Remove any v1 remnants, finalize documentation, tag the release.

Files touched:
- Anything in siv/ not on the §9 dependency list — delete.
- README.md — rewrite.
- CHANGELOG.md — add v2.0.0 entry.
- Release tag: v2.0.0.

What to do:

1. Run `git grep` for each forbidden/obsolete term. Any match outside docs/archive/ must be deleted (the match, and usually the containing symbol, field, or file):

   MacroTemplate, macro_template, universal_affirmative, Fact, is_fol_expressible, rejection_reason, FOLRejectionReason, rejection_note, coverage_fraction, is_collective, detected_modal, detected_temporal, detected_proportional, proportional_quantifier, PROPORTIONAL_QUANTIFIER, plural_non_distributive.

   For ambiguous grep matches (e.g. "Fact" may match unrelated identifiers, comments, or test fixtures), surface the match rather than editing in place.

2. Rewrite README.md with a quick-start reflecting the seven-component architecture from SIV.md §6. Include a minimal working example exercising all four Formula cases.

3. Write CHANGELOG.md entry for v2.0.0: concise list of what changed, what was removed, and the headline empirical result from Phase 5 (mean F1 on employees-meetings class).

4. Tag the release v2.0.0 on the final commit of v2-from-clean.

Forbidden moves:
- Do not reintroduce any forbidden term while cleaning up.
- Do not add cleanup steps beyond those listed. Note lint-level issues for a separate change; Phase 6 is scoped.
- Do not skip the grep check. Zero matches outside docs/archive/ is the gate.
- Do not omit the CHANGELOG or README rewrite. They are gate items.
- Do not add a Phase 7. The refactor ends at Phase 6.

Tests required: full test suite including slow invariant tests must be green.

Gate:
- `git grep` on the forbidden-term list returns zero matches outside docs/archive/.
- README quick-start copy-pastes and runs end to end.
- Full test suite green including slow invariant tests.
- Tag v2.0.0 applied to final commit on v2-from-clean.

If anything contradicts SIV.md, stop and surface. Do not guess, do not loosen.
```

---

## 19. Post-refactor verification prompt

```
All seven phases (0–6) have completed and v2.0.0 is tagged. Run the following verification pass. Do not make code changes; if any check fails, stop and surface.

Before starting, read:
- SIV.md in full.

Perform these checks in order:

1. Contract verification. For each contract C0 through C9b in SIV.md §7, inspect the implementation and confirm: type signature, preconditions, postconditions, error modes, invariants. Report one line per contract: PASS or FAIL with reason.

2. Forbidden-term grep. Run `git grep` for each term in the Phase 6 list:
   MacroTemplate, macro_template, universal_affirmative, Fact, is_fol_expressible, rejection_reason, FOLRejectionReason, rejection_note, coverage_fraction, is_collective, detected_modal, detected_temporal, detected_proportional, proportional_quantifier, PROPORTIONAL_QUANTIFIER, plural_non_distributive.
   Confirm zero matches outside docs/archive/.

3. Full test suite. Run full pytest including slow invariant tests. Confirm green. Report pass count and any failures.

4. FOLIO replay. Re-run scripts/run_folio_evaluation.py; confirm reports/folio_agreement.json matches Phase 5 gate thresholds:
   - Mean F1 on employees-meetings class ≥ 0.85.
   - Mean F1 on atomic (ground) predications ≥ 0.90.
   - Mean F1 on connective-only sentences ≥ 0.80.
   Report actual numbers.

5. CHANGELOG summary. One-page summary suitable for CHANGELOG.md: (a) removed, (b) rewritten, (c) new, (d) Phase 5 headline result. No prose beyond one page.

6. Deferred decisions check. Inspect SIV.md §20. For each deferred decision: has the revisit trigger fired (e.g., post-Phase-5 for the Clean-FOLIO translation-generator question)? If yes, note it for the user. Do not act on deferred decisions during verification.

If any check fails, stop after reporting. Fixes are a separate scoped change.
```

---

## 20. Deferred decisions

Open questions recorded here so they are not lost. Each has a revisit trigger and the doc-update order required if adopted.

### 20.1 LLM translation step for Clean-FOLIO mode (§10.2)

**Status:** deferred from pre-Phase-1 discussion. Revisit after Phase 5.

**Context.** §10.2 Clean-FOLIO publishes `compile_canonical_fol(extraction)` as the FOL translation for each NL sentence. The compiler is a pure function of `SentenceExtraction` and does not see `nl`. This is correct for the compiler's role in tests and soundness invariants (§6.4, §8), because the two-path bidirectional-entailment check requires both paths to be functions of the extraction alone.

**Concern raised.** Published translations derived solely from the extraction may miss NL details the extractor did not capture. A translation step that consumes both `nl` and `extraction` and emits an LLM-produced FOL translation would recover those details and strengthen §10.2's self-consistency check (the check becomes non-trivial when the translation is not constructed from the same extraction that defines the tests).

**Why deferred.** Adding a translation generator is an eighth component; the architecture currently has seven. Per §5 and §11 ground rule 1, architecture changes require doc revision first. The concern is a hypothesis, not evidence. Phase 5 runs 300 FOLIO premises end-to-end; if compiler-output translations are impoverished, that shows up as qualitatively poor Clean-FOLIO outputs or low F1 against gold. That is the decision point. If the extractor is missing NL details, the proper fix is strengthening the extractor (Phase 2 prompt/examples), not a downstream LLM step that papers over extractor weakness.

**Revisit trigger.** After Phase 5, inspect:
- Sample Clean-FOLIO translations for qualitative faithfulness to `nl`.
- FOLIO evaluator F1, per-Formula-case breakdown, especially connective and nested-quantification classes.
- Phase 5's manual-review list of F1 < 0.5 premises and extraction failures.

**If adopted.** Scope: §10.2 Clean-FOLIO only. Evaluator mode (§10.1) unchanged. Compiler role (tests + invariants) unchanged. New component: `generate_translation(extraction, nl) -> str`. Fold into a post-refactor change; do not retrofit mid-refactor.

**Doc-update order (if adopted):** SIV.md §5 review (is an eighth component consistent with the negative list?) → SIV.md §6 (add component) → SIV.md §7 (add contract) → SIV.md §10.2 (specify use).

**Do not add this during Phases 1–6.** The spec is executing; scope creep here is what §2 warns against.

---

## 21. References

The theoretical foundation is standard; the citations are load-bearing.

- **Frege, G.** (1879). *Begriffsschrift*. Halle: Nebert. — original inductive definition of FOL formulas: atoms, connectives, quantifiers. SIV's `Formula` type is a direct implementation.
- **Enderton, H. B.** (2001). *A Mathematical Introduction to Logic* (2nd ed.). Academic Press. — modern standard reference for FOL's formal grammar; the recursive structure of `Formula` in §6.2 is Enderton's Chapter 2 structure.
- **Barwise, J., & Cooper, R.** (1981). Generalized Quantifiers and Natural Language. *Linguistics and Philosophy* 4(2), 159–219. — origin of the tripartite representation used by `TripartiteQuantification`.
- **Heim, I.** (1982). *The Semantics of Definite and Indefinite Noun Phrases*. PhD dissertation, UMass Amherst. — tripartite logical forms, independent development.
- **Kamp, H.** (1981). A Theory of Truth and Semantic Representation. In *Formal Methods in the Study of Language*. — tripartite logical forms, third independent development.
- **Parsons, T.** (1990). *Events in the Semantics of English: A Study in Subatomic Semantics*. MIT Press. — Neo-Davidsonian atomic decomposition; justification for arity-1-or-2 predicates.
- **Chen, T. Y., et al.** (2018). Metamorphic Testing: A Review of Challenges and Opportunities. *ACM Computing Surveys* 51(1). — methodology of mutation-based contrastive testing.
- **Claessen, K., & Hughes, J.** (2000). QuickCheck: A Lightweight Tool for Random Testing of Haskell Programs. *ICFP '00*. — property-based testing lineage for the soundness invariants.
- **Kovács, L., & Voronkov, A.** (2013). First-Order Theorem Proving and Vampire. *CAV 2013*. — the theorem prover.
