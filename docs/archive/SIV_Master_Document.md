# SIV Master Document

*A short, complete description of what SIV is, what it does, and how it works.*

This document is the single reference for the project. It is intentionally short. Any coding agent or new reader should be productive after reading it end to end. Deeper architectural rationale lives in `SIV_Philosophy.md`; the actionable refactor steps live in `SIV_Refactor_Plan.md`.

---

## 1. What problem SIV solves

Current metrics for natural-language-to-first-order-logic translation all fail in ways that make them unusable as research tools.

- **Exact match** rewards only translations that exactly reproduce a specific human annotator's style. A better translation that decomposes the logic correctly scores zero.
- **Denotation accuracy** — checking whether the final conclusion matches the gold — treats all paths to the right answer as equivalent, including paths that go through hallucinated premises.
- **N-gram and embedding metrics** (BLEU, BERTScore) cannot see the difference between a sentence and its logical negation, because the surface forms differ by a single token.

What is needed is a metric that checks whether a candidate FOL translation captures the atomic logical content of the source sentence — each quantifier, each predicate, each argument binding, each connective — independently and mechanically. That metric is SIV.

## 2. What SIV does

SIV takes two inputs:

1. A natural language sentence that has a faithful FOL translation.
2. A candidate FOL translation of that sentence.

It produces one output: an F1 score in `[0, 1]` measuring how well the candidate captures the source's atomic logical content.

The score has two components:

- **Recall:** the fraction of positive atomic tests the candidate entails.
- **Precision:** the fraction of contrastive (mutation) tests the candidate correctly rejects.

If the user sends a sentence that is not cleanly FOL-translatable, SIV will still produce a score, but the score carries no correctness guarantee. Scope is the user's responsibility, not SIV's. See `SIV_Philosophy.md` for why this boundary matters.

## 3. The bug that motivates the whole design

SIV version 1 failed on one recognizable class of sentence:

> "All employees who schedule meetings attend the company building."

V1 produced the FOL equivalent of *"All employees attend the company building"* — dropping the *"who schedule meetings"* clause entirely. This is not a scope problem; the sentence is perfectly FOL-translatable. It is a faithfulness problem: the translation lost the condition that restricts which employees the universal applies to.

Every design decision that follows exists to make this collapse structurally impossible.

## 4. How SIV works: the seven components

SIV is seven components and six dependencies. Anything not on this list is not part of SIV.

### 4.1 Pre-analyzer

Given a natural language sentence, the pre-analyzer uses spaCy's dependency parse to compute two flags:

- `requires_restrictor`: true if the sentence contains a restrictive relative clause on the subject (detected by the `relcl` dependency), or a universal/existential determiner followed by *who*, *that*, or *which*.
- `requires_negation`: true if the sentence contains *no*, *none*, *never*, *neither*, or a `neg` dependency on the main verb.

No LLM call, no other flags, no other outputs. This component exists solely to catch the v1 bug: when the sentence structurally requires a restrictor, something downstream must check that the extraction has one.

### 4.2 Schema

The schema defines the data structure that extraction produces and compilation consumes. Every component that manipulates logical structure reads and writes this schema.

The schema represents exactly the grammar of first-order logic as fixed by Frege (1879): atomic predications, boolean connectives, and quantifiers. It has no other constructs. The closure of this grammar is what makes SIV's scope bounded: any sentence outside this grammar is outside FOL and therefore outside SIV.

#### 4.2.1 The top-level structure

A `SentenceExtraction` contains:

- `nl`: the source sentence.
- `predicates`: declared predicates, each with a name, an arity (1 or 2), and per-position argument types.
- `entities`: variable-bound individuals referenced in the sentence.
- `constants`: named individuals (proper nouns).
- `formula`: a single `Formula` representing the full logical content of the sentence.

The `formula` field is the whole payload. It is a recursive structure that can represent any FOL formula — a bare atomic predication, a quantified statement, a boolean combination of sub-formulas, or any nesting of these.

#### 4.2.2 The Formula type

`Formula` is a sum type with exactly four cases. Every valid FOL formula is exactly one of these:

```python
class Formula(BaseModel):
    # Exactly one of the following four is populated.
    atomic: Optional[AtomicFormula] = None
    quantification: Optional[TripartiteQuantification] = None
    negation: Optional[Formula] = None                         # ¬φ
    connective: Optional[Literal["and", "or", "implies", "iff"]] = None
    operands: Optional[List[Formula]] = None                   # populated iff connective is
```

- **Atomic case** (`atomic` populated): a single predication like `CzechConductor(miroslav)` or `Schedule(x, y)`. This is the leaf of the formula tree.
- **Quantification case** (`quantification` populated): a universal or existential over a domain, with its own internal tripartite structure (see §4.2.3).
- **Negation case** (`negation` populated): `¬φ` for some sub-formula `φ`. Negation is unary, so there is one operand, expressed as a nested `Formula`.
- **Connective case** (`connective` and `operands` populated together): binary or n-ary boolean combinations — `φ ∧ ψ`, `φ ∨ ψ`, `φ → ψ`, `φ ↔ ψ`.

A validator enforces that exactly one of the four cases is active per `Formula` instance.

Recursion handles all nesting for free. `"The L-2021 monitor is either used in the library or has a type-c port"` becomes a connective-`or` over two atomic formulas. `"Miroslav Venhoda was a Czech choral conductor"` becomes a bare atomic. `"All employees who schedule meetings attend the company building"` becomes a bare quantification. `"If the forecast calls for rain, then all employees work from home"` becomes a connective-`implies` over an atomic antecedent and a quantification consequent.

#### 4.2.3 TripartiteQuantification

Quantifications have their own internal structure, the **tripartite form** of Barwise & Cooper (1981), Heim (1982), and Kamp (1981):

```python
class TripartiteQuantification(BaseModel):
    quantifier: Literal["universal", "existential"]
    variable: str
    var_type: str
    restrictor: List[AtomicFormula]   # conjuncts that bound the domain
    nucleus: Formula                  # what is asserted of the bounded domain
```

The restrictor is a conjunctive list of atoms — these are the clauses that define which individuals the quantifier ranges over (*"employees who schedule meetings"*). The nucleus is a full `Formula`, not a list of atoms — this is critical, because it means the nucleus can be any FOL formula, including a boolean combination or another quantification. This supports sentences like *"Every student reads a book or watches a movie"* (nucleus is a disjunction) and *"Every student who takes a class that is taught by a professor passes"* (nested quantification in the restrictor, via an inner quantification mechanism described below).

The tripartite form is what forces the distinction between *which individuals the quantifier ranges over* and *what is claimed of them* — the exact distinction v1 could not make and that the employees-meetings bug turned on.

Restrictor atoms may contain free variables bound by inner existentials. These are declared in a parallel `inner_quantifications: List[InnerQuantification]` field on the quantification, one per variable introduced in the restrictor beyond the bound variable itself. The compiler emits these as existentials scoped inside the restrictor. Similarly, the nucleus can introduce inner quantifications via its own `Formula` structure; no separate field is needed because the nucleus is already a full formula.

#### 4.2.4 Atomic formulas

```python
class AtomicFormula(BaseModel):
    pred: str                   # must reference a declared PredicateDecl
    args: List[str]             # variable names or constant IDs; length == pred.arity
    negated: bool = False       # convenience flag; equivalent to Formula.negation on this atom
```

The `negated` flag on an atomic formula is a convenience: it allows compact representation of common patterns like "No X is Y" (a universal with a single negated atom in the nucleus) without wrapping every such atom in a `Formula.negation`. The compiler treats both representations as equivalent. The validator enforces that atom arities and argument types match their declared `PredicateDecl`.

Types in this schema are **grammatical**, not ontological. A `type` field distinguishes entities from constants from predicate names, to prevent ill-formed FOL like `Employee(Schedule)`. It does not classify entities as `person` versus `animal`; that level of typing is not the metric's job.

#### 4.2.5 Derivation of the JSON Schema

The JSON Schema passed to the LLM as `response_format` is derived mechanically from the Pydantic `SentenceExtraction` model. Hand-rolled JSON Schemas are forbidden. This guarantees the Pydantic model and the API-level constraint cannot drift — a class of bug that cost two phases of the previous refactor.

### 4.3 Extractor

The extractor takes a sentence and returns a validated `SentenceExtraction`. It calls a frozen LLM (GPT-4 snapshot, temperature 0, pinned seed), passing the system prompt, a small set of few-shot examples, and the sentence.

The LLM's output is constrained by the Pydantic-derived JSON Schema, so it cannot return something syntactically malformed. After the response arrives, two checks run:

1. **Schema validation**: every atom's predicate is declared; arities match; every argument references a declared entity or constant; every `Formula` has exactly one of its four cases populated.
2. **Tripwire enforcement**: if the pre-analyzer said `requires_restrictor`, the extraction's top-level formula must contain at least one `TripartiteQuantification` with a populated restrictor. If `requires_negation` was set, at least one negation must appear somewhere in the formula tree (either as `Formula.negation`, as an `AtomicFormula.negated` flag, or inside a connective).

If either check fails, the extractor retries once with the violation appended to the prompt. If the retry also fails, the extractor raises. There is no silent acceptance and no second retry — infinite retries hide systemic prompt failures.

### 4.4 Compiler

The compiler turns a validated `SentenceExtraction` into FOL formulas. It has two entry points, and it is recursive over the `Formula` structure.

- `compile_sentence_test_suite` emits the positive tests — the FOL formulas a correct candidate must entail. The full canonical FOL is one positive test. Sub-formula entailments (every sub-node of the formula tree) are also emitted, so each atomic claim the source makes is independently checkable.
- `compile_canonical_fol` emits the full canonical FOL for the sentence as a single string.

The compiler's recursion handles each `Formula` case:

- **Atomic** → emit `Pred(args...)` or `-Pred(args...)` if `negated`.
- **Negation** → emit `-(` + compile(operand) + `)`.
- **Connective `and`** → join compiled operands with `&`.
- **Connective `or`** → join compiled operands with `|`.
- **Connective `implies`** → emit `(` + compile(op1) + `->` + compile(op2) + `)`.
- **Connective `iff`** → emit `(` + compile(op1) + `<->` + compile(op2) + `)`.
- **Quantification, universal** → emit `all x.(⋀restrictor → compile(nucleus))`.
- **Quantification, existential** → emit `exists x.(⋀restrictor & compile(nucleus))`.

The two entry points are deliberately separate code paths. Different traversal order, different variable naming, different string assembly. Their independent outputs must be bidirectionally entailing — a property checked by the soundness invariants (§4.7). If both paths had the same bug, the check would not catch it; by making them structurally distinct, we reduce that risk to negligible.

### 4.5 Contrastive generator

For each `SentenceExtraction`, the generator produces candidate negative tests by mutating the extraction, then filters them through Vampire.

Six mutation operators, each operating at an appropriate level of the formula tree:

1. **Negate an atom.** Walk the tree; for each `AtomicFormula` encountered, emit a mutant with its `negated` flag flipped.
2. **Swap binary arguments.** For each binary atom in the tree, emit a mutant with its two arguments swapped.
3. **Flip a quantifier.** For each quantification in the tree, emit a mutant with its quantifier flipped between universal and existential.
4. **Drop a restrictor conjunct.** For each restrictor in the tree, emit a mutant with one conjunct removed, strengthening that universal.
5. **Flip a connective.** For each connective node, emit a mutant with `and ↔ or`, `implies ↔ iff`, or operands reordered for asymmetric connectives.
6. **Replace sub-formula with its negation.** For each non-atomic sub-formula, emit a mutant with that sub-formula wrapped in `Formula.negation`.

Each mutant is compiled via `compile_canonical_fol`. Vampire checks whether the mutant is logically inconsistent with the original. If Vampire proves inconsistency (`unsat`), the mutant becomes a contrastive test. If Vampire proves consistency (`sat`) — meaning the mutation is entailment-neutral — the mutant is dropped. If Vampire times out or returns unknown, the mutant is also dropped.

The filter means every accepted contrastive test is **provably wrong**, not merely different. This is the key improvement over v1's hand-rolled perturbations, which were often semantically neutral.

### 4.6 Scorer

Given a test suite (positive tests + contrastive tests) and a candidate FOL translation, the scorer calls Vampire to check:

- For each positive test `P`: does the candidate entail `P`?
- For each contrastive test `C`: does the candidate entail `C`? (It should not.)

```
recall    = (positives entailed) / (total positives)
precision = (contrastives not entailed) / (total contrastives)
SIV       = 2 · recall · precision / (recall + precision)
```

No coverage fraction. No adjustment. Just F1.

### 4.7 Soundness invariants

Two CI-level checks run on every compiled test suite during continuous integration and fail the build on violation:

1. **Entailment monotonicity.** For every extraction, the conjunction of its positive tests must be bidirectionally equivalent (via Vampire) to the formula produced by `compile_canonical_fol`. This catches bugs where the two compilation paths disagree.
2. **Contrastive soundness.** For every contrastive test, Vampire must prove it inconsistent with the positive tests. This catches any entailment-neutral mutants the generator's filter missed.

Both invariants run against a curated corpus of sentences checked into the repository. The corpus covers all four `Formula` cases — bare atoms, quantifications, negations, and connectives — plus nestings thereof.

The claim "SIV is sound" is only defensible if soundness is mechanically checked on every build. Without these invariants, soundness is an assertion that degrades every time someone touches the compiler. With them, soundness is a property CI enforces.

## 5. Architecture diagram

The flow of a sentence through SIV. Solid arrows are runtime data flow; dashed arrows are CI-time checks that read from the runtime components but do not participate in scoring.

```
                        ┌───────────────────────┐
                        │     NL sentence       │
                        └───────────┬───────────┘
                                    │
                                    ▼
                        ┌───────────────────────┐
                        │   1. Pre-analyzer     │
                        │   (spaCy)             │
                        │                       │
                        │ requires_restrictor   │
                        │ requires_negation     │
                        └───────────┬───────────┘
                                    │
                                    ▼
                        ┌───────────────────────┐
                        │   3. Extractor        │
                        │   (frozen LLM)        │
                        │                       │
                        │ JSON-schema bound     │
                        │ tripwire + retry      │
                        └───────────┬───────────┘
                                    │
                                    ▼
                        ┌───────────────────────┐
                        │   2. Schema           │
                        │                       │
                        │ Formula = atomic /    │
                        │  quantif. / neg. /    │
                        │  connective           │
                        └──┬─────────────────┬──┘
                           │                 │
                ┌──────────┘                 └──────────┐
                ▼                                       ▼
    ┌───────────────────────┐               ┌───────────────────────┐
    │   4. Compiler         │               │   5. Contrastive      │
    │   (two paths)         │               │      generator        │
    │                       │               │                       │
    │ compile_sentence_     │               │ mutate + Vampire      │
    │   test_suite          │               │ accept only unsat     │
    │ compile_canonical_    │               │                       │
    │   fol                 │               │                       │
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
                        │   6. Scorer (Vampire) │
                        │                       │
                        │   F1(recall,          │
                        │      precision)       │
                        └───────────────────────┘


    ┌───────────────────────┐
    │   7. Soundness        │  ◄┄┄┄┄┄┄┄┄ reads from Compiler (§4.4)
    │      invariants       │  ◄┄┄┄┄┄┄┄┄ reads from Generator (§4.5)
    │                       │
    │   CI-enforced;        │
    │   breaks build on     │
    │   violation           │
    └───────────────────────┘
```

## 6. Dependencies

The complete list:

- **spaCy** (pre-analyzer).
- **Pydantic** (schema definition and validation).
- **OpenAI API client** (extractor; frozen LLM snapshot).
- **Vampire** (theorem prover; used by generator, scorer, and invariants).
- **NLTK-compatible FOL string format** (compiler output convention).
- **pytest** (invariant CI harness).

Any dependency not on this list requires a deliberate decision and an update to this document. No WordNet, no PMI, no FraCaS corpus, no rejection taxonomy, no embedding models, no fine-tuning.

## 7. Coverage claim

SIV's schema represents exactly Frege's grammar of FOL: atoms, boolean connectives, quantifiers, variables, constants. Every FOL formula decomposes into these constructs. Therefore the schema represents every FOL formula, and SIV scores every FOL-translatable sentence. Sentences outside this grammar are outside FOL and are the user's scope boundary, not SIV's.

Empirically on FOLIO's 300-premise sample, this grammar accounts for the full in-scope space: quantified sentences (54% of FOLIO), ground predications (31%), sentential conditionals and biconditionals (12%), and disjunctive constructions (3%). Sentences SIV does not handle — modal attitudes, proportional quantifiers, lexically collective predicates — are exactly the sentences whose logical form exceeds FOL, and whose handling would require modal logic, generalized quantifier theory, or plural logic respectively.

## 8. Modes of operation

SIV has two modes, sharing all seven components above:

### 8.1 Evaluator

**Input:** A dataset of (sentence, candidate FOL) pairs — typically a benchmark like FOLIO with gold annotations, or a model's predicted translations.

**Process:** For each pair, run the full pipeline and produce a per-sentence score plus the passing and failing test breakdown.

**Output:** Aggregate F1 across the dataset, plus per-sentence reports.

**Use case:** Replacing exact match and denotation accuracy as the primary automated metric in NL-to-FOL papers.

### 8.2 Generator (Clean-FOLIO)

**Input:** Natural language sentences only.

**Process:** Run the pipeline through compilation to produce a canonical FOL translation for each sentence. Verify each translation against its own test suite as a self-consistency check.

**Output:** A cleaned dataset — the same sentences as FOLIO, with canonical formula-structured FOL translations.

**Use case:** A training and evaluation substrate for future NL-to-FOL work, with FOL translations that are structurally clean and usable by downstream symbolic systems.

## 9. References

The theoretical foundation is standard and the citations are load-bearing.

- **Frege, G.** (1879). *Begriffsschrift, eine der arithmetischen nachgebildete Formelsprache des reinen Denkens*. Halle: Nebert. — the original inductive definition of FOL formulas: atoms, connectives, quantifiers. SIV's `Formula` type is a direct implementation.
- **Enderton, H. B.** (2001). *A Mathematical Introduction to Logic* (2nd ed.). Academic Press. — modern standard reference for FOL's formal grammar; the recursive structure of `Formula` in §4.2 is the structure Enderton defines in Chapter 2.
- **Barwise, J., & Cooper, R.** (1981). Generalized Quantifiers and Natural Language. *Linguistics and Philosophy* 4(2), 159–219. — the origin of the tripartite representation used by `TripartiteQuantification`.
- **Heim, I.** (1982). *The Semantics of Definite and Indefinite Noun Phrases*. PhD dissertation, UMass Amherst. — tripartite logical forms, independent development.
- **Kamp, H.** (1981). A Theory of Truth and Semantic Representation. In *Formal Methods in the Study of Language*. — tripartite logical forms, third independent development.
- **Parsons, T.** (1990). *Events in the Semantics of English: A Study in Subatomic Semantics*. MIT Press. — Neo-Davidsonian atomic decomposition; the justification for arity-1-or-2 predicates.
- **Chen, T. Y., et al.** (2018). Metamorphic Testing: A Review of Challenges and Opportunities. *ACM Computing Surveys* 51(1). — the methodology of mutation-based contrastive testing.
- **Claessen, K., & Hughes, J.** (2000). QuickCheck: A Lightweight Tool for Random Testing of Haskell Programs. *ICFP '00*. — the property-based testing lineage for the soundness invariants.
- **Kovács, L., & Voronkov, A.** (2013). First-Order Theorem Proving and Vampire. *CAV 2013*. — the theorem prover.

---

## Appendix: What is not in SIV

This list is as important as the architecture. Each item is something an earlier version of SIV tried to include, which either drifted or bloated the system. They are called out here so the pattern is not repeated.

- No `is_fol_expressible` flag.
- No `FOLRejectionReason` enum.
- No `rejection_note` field.
- No coverage fraction in the headline score.
- No detection of modal, temporal, or proportional sentence features.
- No `is_collective` field or collective-predication handling.
- No ontological type vocabulary (`person`, `animal`, `place`).
- No hand-rolled JSON schemas; always derive from Pydantic.
- No backward-compatibility aliases for renamed symbols.
- No FraCaS-based scope enforcement.
- No grammatical constructs beyond Frege's five. The `Formula` type in §4.2 is the complete grammar; nothing is added to it.

See `SIV_Philosophy.md` §9 for why each of these is excluded.
