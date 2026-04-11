# SIV: Systematic Inference-Based Verification
## The Definitive Master Document

*A Neuro-Symbolic Evaluation Framework for Natural Language to First-Order Logic Translation*

---

## 1. Executive Summary / Abstract

The evaluation of Natural Language to First-Order Logic (NL-to-FOL) translation systems is in a methodological crisis. The dominant metrics in the literature fail along two opposing axes: **Exact Match** and its syntactic variants are punitively rigid, rewarding systems only when they reproduce the idiosyncratic annotation conventions of a specific human-curated gold standard, while **Denotation Accuracy** — evaluating whether a candidate entails the same conclusion as the reference — is catastrophically permissive, silently endorsing models that arrive at correct boolean verdicts through spurious logical trajectories. N-gram and embedding-based metrics (BLEU, BERTScore) are structurally blind to formal logic: a single dropped negation token inverts truth conditions while barely perturbing the score. No existing metric is simultaneously **sound** (penalizing logical error), **structural** (rewarding downstream usability), and **deterministic** (reproducible without human adjudication).

We introduce **SIV (Systematic Inference-Based Verification)**, an automated, deterministic, neuro-symbolic evaluation framework that reconceives NL-to-FOL scoring as a problem of *atomic faithfulness* rather than holistic equivalence. SIV decomposes each source sentence into a structured extraction of entities, predicates, and macro-templates using a frozen LLM, deterministically compiles that extraction into a **test suite** of positive (recall) and contrastive (precision) FOL unit tests, and verifies candidates against the suite via a tiered pipeline culminating in the Vampire theorem prover. The resulting score is an F1 over structural recall and contrastive precision — what we call, without apology, *the BLEU score for atomic logic*. SIV is strict by design. It penalizes monolithic annotation, rejects morphological softening, and treats lexical drift as an error rather than a paraphrase. In doing so, SIV reframes the evaluation contract: a translation is not "correct" because a human annotator accepted it; a translation is correct if and only if its atomic, decomposable content can be verified against the source and is structurally usable by downstream symbolic systems.

---

## 2. The Core Problem: The Adversaries We Replace

SIV is defined in opposition to three classes of metric, each of which fails on a specific and irrecoverable axis.

### 2.1 Exact Match — The Annotator-Worship Problem

Exact Match (and its close variants: logical-form equality modulo variable renaming, AST isomorphism) treats the human-annotated gold as ground truth. This is defensible only if the gold is canonical. It is not. Consider the sentence *"All employees who schedule a meeting with their customers will go to the company building."* A FOLIO annotator produced:

```
∀x ((Employee(x) ∧ Schedule(x, meeting, customers)) → AppearIn(x, company))
```

This is a valid FOL translation. It is also **downstream-hostile**. The ternary predicate `Schedule(x, meeting, customers)` welds three entities into a single opaque relation that cannot be queried, cannot be joined against a knowledge graph, and cannot be extended with modifiers (*urgent* meeting? *recurring* meeting? *enterprise* customer?). A Neo-Davidsonian translation that correctly decomposes the event into `Employee(x) ∧ Meeting(y) ∧ Schedule(x, y) ∧ With(y, customers)` is **strictly superior** for every conceivable downstream task — and yet under Exact Match it scores *zero*. Exact Match punishes the better translation for failing to reproduce the annotator's arity collapse. This is not a metric; it is stylistic hazing.

### 2.2 Denotation Accuracy — The Spurious Trajectory Problem

Denotation Accuracy checks whether the candidate FOL, when combined with background premises, entails the same final hypothesis as the gold. It is seductive: it appears to measure "what matters" by grading on the final answer. But this flattens the entire logical journey into a single boolean, and first-order logic is exactly the domain where the journey is the point. A model that translates premises incorrectly can still derive the right answer through compensating errors, irrelevant lemmas, or — most damningly — via `ex falso quodlibet` from an internally inconsistent candidate set. Denotation Accuracy cannot distinguish a sound translator from a lucky one. For a community that claims to care about *reasoning*, using a metric that treats all roads to the correct answer as equivalent is a categorical failure.

### 2.3 N-Gram and Embedding Metrics — The Negation-Blindness Problem

BLEU, chrF, ROUGE, and BERTScore inherit all the pathologies of their original domain (machine translation) and add new ones when applied to formal logic. The canonical failure is negation: a candidate that translates *"No managers work remotely"* as `∀x (Manager(x) → Work(x, home))` — the direct logical inversion of the correct translation — will differ from the reference by perhaps a single token, scoring in the high 0.9s on any n-gram or embedding-based metric. BLEU cannot see that the candidate is not merely *wrong* but *antipodal*. The truth value has been flipped; the score has not. Any metric that assigns near-perfect similarity to a logically inverted translation is disqualified on its face as a measure of semantic faithfulness in formal logic.

---

## 3. The SIV Philosophy: The Four Tenets

The four tenets below are not engineering preferences. They are the **load-bearing philosophical commitments** that distinguish SIV from every existing NL-to-FOL metric, and we defend them aggressively. Every tenet is a line drawn against a specific form of metric drift that has historically eroded the rigor of machine translation evaluation.

### Tenet 1 — Strict Lexical Faithfulness (Anti-Hallucination)

**SIV demands that every predicate and entity in the candidate translation preserves the exact surface form of the source sentence, case-normalized and whitespace-normalized only.** We explicitly and permanently reject:

- **Stemmers and lemmatizers.** `Employees` and `Employee` are different predicate identifiers. If the source says "employees," the candidate must say `Employees`. A metric that silently collapses morphological variants is a metric that cannot distinguish "the employee" from "employees in general" — a distinction first-order logic was invented to capture.
- **WordNet and hypernymy expansion.** `Dog ⊑ Animal` is not a fact SIV will infer on the candidate's behalf. If the source says "dog," the candidate must say `Dog`. A translator that substitutes "Animal" has introduced semantic drift, and the metric must register that drift as an error, not absolve it.
- **Synonym tables and thesaurus substitution.** "Buy" and "purchase" are different tokens. A metric that equates them is a metric that has smuggled in a lexicographer's judgment about a decision that should belong to the translator.
- **CamelCase component matching in evaluation mode.** `LovesDeeply(x, y)` and `Loves(x, y)` are different predicates with different extensions in every model. SIV's strict evaluation path gives zero credit for component overlap.

The philosophical justification is simple: **a metric that forgives lexical drift cannot detect lexical drift.** Every softening mechanism is a false-positive generator. Translators that hallucinate — that import vocabulary the source never contained — are the single most dangerous failure mode in neural NL-to-FOL systems, and any metric that obscures hallucination through morphological normalization is actively harmful to the field. Tenet 1 is the promise that SIV will never flatter a hallucinating model.

### Tenet 2 — The Neo-Davidsonian Imperative (Extensibility)

**SIV mandates that facts be expressed as unary or binary relations, and explicitly rejects ternary and higher-arity monolithic predicates that are not prepositional.** Consider again the FOLIO annotation `Schedule(employee, meeting, customer)`. This ternary predicate has three pathologies:

1. **Entity trapping.** The entities `meeting` and `customer` are *inside* the predicate rather than first-class individuals in the logic. They cannot be referenced elsewhere. A downstream query like "which customer did Bonnie schedule with?" cannot be answered because `customer` is a predicate argument, not an individual.
2. **Non-extensibility.** There is no place in the ternary form to attach modifiers. "An *urgent* meeting" requires the fact to be decomposed as `Meeting(y) ∧ Urgent(y)` — a decomposition that is impossible once `meeting` has been welded into `Schedule`'s second slot.
3. **Knowledge-graph incompatibility.** Every modern symbolic AI system — RDF triple stores, property graphs, description logic reasoners, automated theorem provers with equality reasoning — assumes binary (or binary-plus-role) fact representation. A ternary predicate is not ingestible without lossy reshaping.

The Neo-Davidsonian event decomposition, pioneered by Donald Davidson and refined by Terence Parsons, resolves all three pathologies by reifying the event itself: `Schedule(x, y) ∧ Employee(x) ∧ Meeting(y) ∧ With(y, customers)`. Every entity is first-class. Every modifier has a place. Every fact is a binary triple. SIV enforces this form **as the definition of computationally usable FOL**, and the SIV compiler contains a validator (`extraction_invalid`) that flags non-prepositional high-arity facts as schema violations. A translation that fails Neo-Davidsonian form is not a stylistic alternative; it is structurally unusable output, and SIV records it as such.

### Tenet 3 — Structural Overlap over Deep Pragmatics

**SIV evaluates the presence, arity, and binding of atomic logical facts — the "n-grams" of first-order logic — and deliberately declines to engage in deep pragmatic reasoning.** The test suite compiled from a source sentence consists of decomposable unit tests: vocabulary tests (does the candidate contain `Dog` as a predicate?), binding tests (does it assert `∃x. Dog(x) ∧ Brown(x)`?), and macro-template tests (does it have the `∀x.(P(x) → Q(x))` shape the source demands?). We do **not** attempt:

- Full coreference resolution across sentence boundaries.
- Nested disjunction parsing with exclusive-or disambiguation.
- Modal and temporal operator reasoning (except at the tense-canonicalization stage of extraction).
- Recursive conditional restructuring (e.g., inferring Horn-clause equivalences).

Where a source sentence expresses a complex nested disjunction, SIV will flatten it to its atomic components and test each disjunct for structural presence rather than attempting to verify the full nested shape. This is a deliberate, defensible trade-off: infinite recursive parsing is neither computationally tractable nor epistemically honest for an automated metric. By restricting our grain of analysis to atomic facts and macro-template skeletons, SIV achieves three things simultaneously: it remains deterministic (every test is a closed-form FOL query), it remains fast (tiered verification short-circuits most tests before the prover), and — most importantly — **it remains honest about what it measures**. SIV is a metric of structural usability, not a full natural-language understanding engine, and we refuse to let feature creep turn it into the latter.

### Tenet 4 — A Standard, Not a Safety Net

**This is the tenet that most directly breaks with the existing metric culture, and it is the tenet we defend most aggressively.** When a benchmark dataset — FOLIO is the archetype — contains gold annotations that use monolithic ternary predicates, stemming-like morphological collapse, or lexically drifted vocabulary, **SIV scores those annotations lower**. We do not adjust the metric to match the benchmark. We do not introduce multi-reference tolerance to "be fair" to the annotator's choice. We do not add alias tables to preserve backward compatibility. 

The argument is straightforward. A benchmark is worth respecting only to the extent that its annotations are actually usable. If a benchmark's gold labels cannot be ingested into a knowledge graph, cannot be reasoned over by a theorem prover, and cannot be extended with domain modifiers, then the benchmark has been certifying non-executable logic as correct — and any metric that matches that benchmark is validating the same failure. SIV **intentionally penalizes** non-compliant gold annotations because doing so reveals what has been hidden: that the field has been training and evaluating models against a standard that was never suitable for the downstream tasks the field claims to care about.

This produces a stronger paper narrative than "SIV agrees with human annotators." The narrative is: *SIV reveals that the accepted benchmarks in the NL-to-FOL literature have been quietly accepting non-executable logic for years, and the metric that surfaces this failure is more valuable to the community than the metric that papers over it.* A benchmark that scores poorly under SIV is not evidence against SIV. It is evidence against the benchmark — and SIV provides the first principled way to say so.

---

## 4. Metric Architecture and Mathematical Defensibility

SIV is implemented as a four-stage pipeline, each stage deterministic in the sense that every stochastic choice is either frozen, seeded, or explicitly logged. The architecture is designed to satisfy a single overarching property: **two independent runs of SIV on the same (source, candidate) pair must produce the same score**, modulo the known best-effort drift of frozen LLM snapshots.

### 4.1 Stage 1 — Symbolic Pre-Analysis

Before any LLM is invoked, SIV runs a symbolic pre-analyzer over each source sentence. For every modifier–noun compound detected via spaCy dependency parsing, it computes four objective signals: WordNet lexicalization status, Pointwise Mutual Information from the NLTK Brown corpus, proper-noun flag, and dependency scope. These signals yield a `KEEP` or `SPLIT` recommendation that is injected as structured evidence into the extractor's prompt. The pre-analyzer does not make decisions for the LLM; it provides objective input that constrains the LLM toward Neo-Davidsonian decomposition. This is the only point in the pipeline where statistical NLP is used, and it is used as an *input signal to the extractor*, never as a softening mechanism in the validator or scorer — a distinction that preserves Tenet 1 downstream of pre-analysis.

### 4.2 Stage 2 — Frozen LLM Extraction

The extractor calls a **frozen GPT-4 API snapshot** (`gpt-4o-2024-08-06` as primary, `gpt-4-0613` as reproducibility fallback) with `temperature=0.0` and a pinned random seed, producing a JSON extraction conforming to the SIV schema:

```json
{
  "entities": [
    {"id": "e1", "surface": "employees", "entity_type": "universal"},
    {"id": "e2", "surface": "meeting",   "entity_type": "existential"}
  ],
  "facts": [
    {"pred": "Schedule", "args": ["e1", "e2"], "negated": false}
  ],
  "macro_template": "universal_affirmative"
}
```

The model snapshot is hardcoded in a single configuration file (`siv/frozen_config.py`) and the OpenAI `system_fingerprint` is logged on every call. Any drift in the fingerprint surfaces as a warning, keeping reproducibility claims honest. The extraction prompt enforces Tenet 1 (surface-form preservation) and Tenet 2 (decomposition of non-prepositional compounds) through few-shot examples and an explicit rule set.

### 4.3 Stage 3 — Schema Validation

Before compilation, a strict Python validator scans the extraction for schema violations. The single most important check is the **non-prepositional high-arity guard**: any fact with arity ≥ 3 whose predicate does not correspond to a natural prepositional relation is flagged as `extraction_invalid`. This is where Tenet 4 is mechanized. A FOLIO annotation that produced `Schedule(employee, meeting, customer)` causes the entire extraction to be marked invalid, and the compiler refuses to produce a test suite for it. The metric does not silently adjust; it announces the violation and returns zero.

### 4.4 Stage 4 — Compilation and Tiered Entailment

The compiler deterministically maps the validated extraction to a test suite consisting of:

| Test Category | Purpose | Example |
|---|---|---|
| **Vocabulary** | Recall — predicate presence | `∃x. Employees(x)` |
| **Binding** | Recall — typed existentials and groundings | `∀x.(Employees(x) → ∃y.(Meeting(y) ∧ Schedule(x, y)))` |
| **Macro-Template** | Recall — sentence-level logical skeleton | `∀x.(Manager(x) → ¬Work(x, home))` |
| **Precision Perturbation** | Precision — argument-order swap, polarity flip, cross-premise substitution | `∃x.(Employee(x) ∧ ∃y.(Meeting(y) ∧ Schedule(y, x)))` — must be *rejected* |

Critically, **all precision perturbations use only predicates and entities that appear in the problem's own extraction**. There is no antonym table, no synonym expansion, no foreign vocabulary injected from lexical resources. Precision tests are constructed by structural rearrangement of the surface forms already present — argument swaps, polarity flips, cross-premise predicate substitution — preserving Tenet 1 throughout the contrastive evaluation pathway.

The resulting tests are evaluated through a tiered verifier:

- **Tier 0 (Syntax):** NLTK parses the candidate; invalid FOL is rejected before any test is run.
- **Tier 1 (Vocabulary):** Strict set-equality check for predicate presence.
- **Tier 2 (AST):** Lightweight structural matching without the prover.
- **Tier 3 (Vampire):** Full theorem proving for the tests that require it.

The final score is an F1 of the recall and precision rates:

```
recall_rate     = positive_tests_entailed / positive_tests_total
precision_rate  = contrastive_tests_rejected / contrastive_tests_total
SIV             = 2 · recall · precision / (recall + precision)
```

---

## 5. The End-to-End Pipeline: Two Modes of the SIV Engine

The completed SIV engine operates in two complementary modes, sharing the same extraction layer and the same test-compilation layer but targeting different artifacts.

### 5.1 Mode 1 — The Evaluator

**Input:** An existing NL-to-FOL dataset (e.g., FOLIO) consisting of source sentences paired with candidate or gold FOL translations.

**Process:** For each problem, the Evaluator runs the frozen extraction pipeline on the source sentences, validates the extraction against the Neo-Davidsonian schema, compiles the test suite, and scores each candidate FOL against the suite using the tiered verifier. Both the dataset's gold annotation and any model-produced candidate can be scored against the same suite, enabling direct comparison under a unified, deterministic metric.

**Output:** A per-premise and aggregate SIV score, a breakdown of recall and precision, a list of extraction validation failures (Tenet 4 penalties), and a report of any prover-unresolved tests. The CLI entry point is `scripts/siv_score.py`, producing both human-readable and machine-parseable JSON output.

**Use case:** Replacing Exact Match and Denotation Accuracy as the primary automated metric in NL-to-FOL benchmark papers. The Evaluator is what enables the paper's central empirical claim: *a substantial fraction of FOLIO gold annotations score lower under SIV than a mechanically compiled Neo-Davidsonian translation does, and this gap is not noise — it is the measurable quantity of downstream-unusable logic that has been accepted as "correct" by the prior generation of metrics.*

### 5.2 Mode 2 — The Generator (Clean-FOLIO)

**Input:** Natural language source sentences only.

**Process:** The Generator runs the same frozen extraction pipeline to produce a validated SIV JSON extraction, then hands that JSON — **and only that JSON, without the source natural language** — to a downstream LLM prompt that deterministically compiles the extraction into a Neo-Davidsonian-compliant FOL translation. The generator is constrained by five programmatic invariants before its output is accepted:

1. **Syntactic validity** — the output must parse as FOL under NLTK.
2. **Vocabulary containment** — every predicate in the output must appear in the input JSON's facts.
3. **Constant containment** — every constant in the output must appear in the input JSON's entities.
4. **Quantifier correspondence** — the count of universal quantifiers must equal the count of universal-typed entities in the JSON.
5. **Self-consistency** — when the generator's output is re-scored through SIV against the test suite compiled from the same extraction, it must meet a recall floor.

The JSON-only constraint is architecturally load-bearing. If the Generator were allowed to see the source NL, a reviewer could correctly object that the Generator is doing its own NL-to-FOL translation and SIV has become a self-fulfilling metric. By restricting the Generator to the structured extraction alone, its role is reduced to *deterministic compilation* — and any claim that the Generator "beats FOLIO gold" under SIV becomes a defensible claim about the *extraction*, not a claim about the metric policing its own output.

**Output:** A **Clean-FOLIO** dataset: the same premises as FOLIO, but with FOL translations that are Neo-Davidsonian, extensible, knowledge-graph-ready, and provably SIV-compliant.

**Use case:** Supplanting FOLIO as the training and evaluation substrate for future NL-to-FOL research. Where FOLIO's gold annotations encode an annotator's stylistic preferences alongside their logical judgments, Clean-FOLIO encodes *only* the logical content, in a form that every downstream symbolic AI system can ingest without reshaping. Clean-FOLIO is not a replacement for FOLIO; it is what FOLIO should have been from the start, and what the community should have been training against all along.

---

## Appendix: Why SIV Is the Metric the Field Has Been Waiting For

The NL-to-FOL community has been caught between two failure modes for a decade. On one side, metrics that are too rigid — Exact Match and its variants, which reject every translation that does not reproduce an annotator's idiosyncratic conventions. On the other, metrics that are too permissive — Denotation Accuracy and n-gram similarity, which reward any candidate that happens to coincide with the reference on the measurements they are actually sensitive to. No existing metric simultaneously rewards structural usability, penalizes hallucination, and defends against adversarial exploitation of FOL's semantic loopholes. SIV is that metric. It is strict, deterministic, automated, and mathematically sound. It is the BLEU score for atomic logic, and — like BLEU did for machine translation — it will force the field to build systems whose outputs are not merely acceptable to human annotators, but actually usable by the symbolic AI infrastructure the outputs were always meant to serve.

We are not apologizing for the strictness. The strictness is the point.
