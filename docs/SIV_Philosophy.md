# SIV Philosophy

*The scope, the contract, and the boundaries SIV does not cross.*

---

## 1. What SIV is for

SIV is a metric for one task: **given a natural language sentence and a candidate first-order logic translation of it, score how faithfully the candidate captures the atomic logical content of the source.**

The score decomposes into two parts:

- **Recall.** Does the candidate entail the atomic facts the source asserts?
- **Precision.** Does the candidate reject mutations that would contradict the source?

The headline number is the F1 of these two rates. That is the whole metric.

## 2. What SIV is not

SIV is not a filter, a classifier, or a gatekeeper. It does not decide whether a sentence belongs in first-order logic. It does not refuse to score sentences it finds difficult. It does not maintain a taxonomy of reasons for rejection. It does not report a coverage fraction alongside its score.

SIV assumes the user is sending it sentences that have faithful FOL translations. If the user sends something else — a modal attitude report, a proportional quantifier, a genuinely ambiguous sentence — SIV will still produce output, but that output carries no correctness guarantee. **The scope boundary lives with the user, not with the metric.**

This is deliberate. Every attempt to push scope enforcement into SIV itself has failed: the rejection taxonomy drifted, the pre-analyzer heuristics misclassified edge cases, the coverage fraction became a lever for gaming the score. The metric is stronger when it does one thing well than when it tries to be its own user.

## 3. The one bug SIV was built to kill

Version 1 of SIV had a single load-bearing failure: on sentences of the form *"All X who V₁ do V₂"*, it produced the FOL *"All X do V₂"* — collapsing the restrictive clause into nothing. The clause *"who V₁"* is the condition; the clause *"do V₂"* is the consequence. V1 lost the condition and asserted the consequence universally. Every design decision in SIV v2 exists to make that collapse structurally impossible.

The sentence is fully FOL-translatable. The bug was not scope confusion; it was faithfulness failure. SIV's job is to prevent faithfulness failures on translatable sentences. That is the entire mission.

## 4. The three principles

**Principle 1 — Lexical exactness.** SIV does not stem, lemmatize, or paraphrase. "Schedule" and "scheduled" are different predicates; a translation that conflates them has lost information. The metric evaluates exact surface forms because in formal logic "close enough" is a category error.

**Principle 2 — Binary decomposition.** Every predicate has arity one or two. Ternary and higher-arity predicates (*Schedule(person, meeting, customer)*) are not representable in the schema. Multi-participant events decompose into atomic binary relations (*Schedule(person, meeting)* and *With(meeting, customer)*). This is Neo-Davidsonian atomic decomposition applied at the schema level, and it is non-negotiable because it is what makes SIV's output usable by downstream symbolic systems.

**Principle 3 — Atomic entailment.** A correct conclusion does not redeem a hallucinated premise. SIV tests every atomic fact independently and uses a theorem prover to verify each test. The metric proves the translation path, not the endpoint. Denotation accuracy — checking whether the final boolean matches — is exactly the failure mode SIV refuses to repeat.

## 5. What defines the scope

SIV targets the class of sentence that has a faithful first-order logic translation. In practice this is the class where a competent human translator would produce an FOL formula without caveat. The metric does not attempt a rejection-based characterization of this class, because doing so has historically been the source of scope creep: every rejection reason, every scope enumeration, every coverage fraction is a small invitation to grow the metric's responsibilities beyond its one job.

The positive characterization, by contrast, is simple and finite. First-order logic's grammar has five constructs and no others: atomic predications, boolean connectives (AND, OR, NOT, IMPLIES, IFF), quantifiers (∀, ∃), variables, and constants. Any sentence expressible as a finite combination of these five constructs is in SIV's scope. This is the grammar fixed by Frege (1879) and reproduced in every logic textbook since; SIV's schema represents exactly it, and nothing outside it. The grammar is closed — there is no sixth construct waiting to appear in some future sentence.

The sentences SIV does not handle are the sentences that fall outside this closed grammar: modal attitudes, proportional quantifiers, lexically collective predicates, scope-ambiguous sentences where the reading cannot be recovered from syntax. These are sentences formal semantics has needed more than FOL to describe. If the user sends SIV one of these, SIV makes no claim about the result. This is a contract, not a capability.

## 6. What the user gets

A user sends SIV a sentence and a candidate FOL translation. SIV returns a score in `[0, 1]` and a test-by-test report showing which atomic facts the candidate captured and which mutations it correctly rejected. No coverage fraction. No rejection reason. No diagnostic about whether the sentence was "in scope." Just the metric.

If the user wants to know whether their sentence was FOL-translatable in the first place, that is a separate question, answered by other tools, and not SIV's concern.

## 7. What the scope-question costs us

The earlier design of SIV tried to include scope classification — an `is_fol_expressible` flag, a `FOLRejectionReason` enum, a coverage-adjusted score, an escape hatch for modal and proportional sentences. Each of these was well-intentioned. Each created drift: the enum values disagreed with the prompt values, the coverage denominator leaked into places it shouldn't have, the scope heuristics classified unambiguous sentences as out-of-scope and vice versa. The scope apparatus consumed more of the refactor's attention than the actual metric did.

The lesson is that scope enforcement is a second product. Building it alongside the core metric couples their failure modes: a bug in either degrades both. By separating them — making SIV a pure metric with a user-owned scope contract — both products become simpler to build, test, and defend.

## 8. The defensibility claim

SIV is defensible because every component can be named and justified in one sentence. The formula grammar is Frege 1879 (modern standard reference: Enderton 2001). The tripartite quantifier substructure is Barwise & Cooper 1981. The atomic decomposition is Parsons 1990. The theorem prover is Vampire. The contrastive testing is Chen et al. 2018. The schema-model-derived validation is Pydantic. The restrictor detection is a spaCy dependency parse. Nothing is invented here and nothing is hand-waved. Every line of code traces to a line in this philosophy, and every line in this philosophy traces to established practice.

If a future decision cannot be traced to this document, it is either wrong or is a change to the philosophy — in which case the document changes first, the code after.

## 9. Forbidden concepts

To protect the scope, the following are explicitly not part of SIV and must not be added without revising this document:

- No rejection taxonomy or `FOLRejectionReason` enum.
- No `is_fol_expressible` flag or equivalent.
- No coverage fraction or scope-aware scoring.
- No ontological type vocabulary beyond grammatical category (`entity`, `constant`, `predicate name`).
- No detection of modal, temporal, or proportional sentence features.
- No handling of collective predication.
- No handling of scope ambiguity.
- No hand-rolled JSON schemas; all schemas derive from Pydantic models.
- No backward-compatibility aliases for renamed symbols.
- No grammatical constructs beyond Frege's five (atomic predications, boolean connectives, quantifiers, variables, constants). FOL's grammar is closed; any "new construct" is either expressible in the existing grammar or is outside FOL and therefore outside SIV.

Each of these is on this list because an earlier version of SIV tried to include it, and the inclusion created drift or scope creep that had to be unwound. The negative list is as load-bearing as the positive one.

## 10. The contract, restated

> SIV takes a sentence and a candidate FOL translation. It returns an F1 score measuring recall and precision of atomic logical content. It assumes the sentence is FOL-translatable — expressible in Frege's closed grammar of atoms, connectives, and quantifiers. It does not classify, reject, or adjust for sentences outside that class. The user owns the scope.
