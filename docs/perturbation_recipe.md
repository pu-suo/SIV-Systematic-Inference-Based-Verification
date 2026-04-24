# Perturbation Recipe — Human Annotation Study

Frozen specification of all AST-level perturbation operators applied to FOLIO
gold FOL formulas.  Every perturbation is deterministic given a seed and
operates on a parsed NLTK `Expression` object.

Implementation: `siv/nltk_perturbations.py`

## Tier A — Subtle (annotators may disagree)

### A_arity_decompose

Fold a constant argument into the predicate name, reducing arity.

- **Input:**  `Loves(alice, bob)`
- **Output:** `LovesBob(alice)`
- **Applicability:** Binary predicate with at least one `ConstantExpression` arg.

### A_const_to_unary

Same transformation as `A_arity_decompose` — merges constant into predicate
name.  Provided as an alternative dispatch target when only one Tier A slot
needs filling.

- **Input:**  `Has(alice, fever)`
- **Output:** `HasFever(alice)`
- **Applicability:** Any predicate with a constant argument.

### A_compound_decompose

Split a CamelCase compound predicate into component predicates conjoined.

- **Input:**  `all x.(ProfessionalTennisPlayer(x) -> Athlete(x))`
- **Output:** `all x.((Professional(x) & Tennis(x) & Player(x)) -> Athlete(x))`
- **Applicability:** Unary predicate whose name has >= 2 CamelCase components.

### A_const_rename

Stylistic constant rename (truncation + numeric suffix).

- **Input:**  `Happy(john)`
- **Output:** `Happy(john82)` (deterministic given seed)
- **Applicability:** Any formula containing constants.

## Tier B — Meaning-Altering (paper's Exhibit A)

### B_arg_swap

Swap arguments of a binary predicate.

- **Input:**  `Loves(alice, bob)`
- **Output:** `Loves(bob, alice)`
- **Applicability:** Binary predicate not in symmetric allowlist
  (`Equal`, `SameAs`, `Similar`, `Adjacent`, `Married`, `Sibling`).

### B_restrictor_drop

Drop the last conjunct from the antecedent of a universal implication.

- **Input:**  `all x.((Dog(x) & Large(x)) -> Scary(x))`
- **Output:** `all x.(Dog(x) -> Scary(x))`
- **Applicability:** `AllExpression` with `ImpExpression` body whose antecedent
  has >= 2 conjuncts (S3 formulas).

### B_restrictor_add

Add an extra conjunct to the antecedent from another predicate in the same story.

- **Input:**  `all x.(Dog(x) -> Animal(x))` + story has `Fluffy`
- **Output:** `all x.((Dog(x) & Fluffy(x)) -> Animal(x))`
- **Applicability:** `AllExpression` with `ImpExpression` body; story context has
  a predicate not already in the formula.

### B_scope_flip

Swap the order of two nested quantifiers.

- **Input:**  `all x.(Person(x) -> exists y.(Dog(y) & Owns(x, y)))`
- **Output:** `exists y.(all x.(Person(x) -> (Dog(y) & Owns(x, y))))`
- **Applicability:** Two quantifiers nested at the top level.

### B_quantifier_swap

Swap the outermost quantifier type.

- **Input:**  `all x.(Dog(x) -> Animal(x))`
- **Output:** `exists x.(Dog(x) -> Animal(x))`
- **Applicability:** Top-level `AllExpression` or `ExistsExpression`.

## Tier C — Clearly Wrong

### C_predicate_substitute

Replace one predicate with its antonym from a hardcoded lexicon.

- **Input:**  `Tall(john)`
- **Output:** `Short(john)`
- **Applicability:** Formula contains a predicate present in the antonym lexicon.

**Antonym lexicon** (30 pairs):
`Tall/Short`, `Happy/Sad`, `Rich/Poor`, `Strong/Weak`, `Love/Hate`,
`Loves/Hates`, `Like/Dislike`, `Likes/Dislikes`, `Before/After`,
`Above/Below`, `Taller/Shorter`, `Larger/Smaller`, `Accept/Reject`,
`Win/Lose`, `True/False`, `Good/Bad`, `Fast/Slow`, `Hot/Cold`,
`Old/Young`, `Cheap/Expensive`, `Safe/Dangerous`, `Legal/Illegal`,
`Dependent/Independent`, `Aware/Unaware`, `LocatedIn/NotIn`.

### C_negation_drop

Remove the first `NegatedExpression` found in the AST.

- **Input:**  `-Happy(john)`
- **Output:** `Happy(john)`
- **Input:**  `all x.(Dog(x) -> -Fly(x))`
- **Output:** `all x.(Dog(x) -> Fly(x))`
- **Applicability:** Formula contains at least one negation.

### C_entity_swap

Replace one constant with a different constant from the same story.

- **Input:**  `Loves(alice, bob)` + story has `carol`
- **Output:** `Loves(carol, bob)`
- **Applicability:** Formula contains constants; story has a different constant.

## Tier D — Nonsense

### D_random_predicates

Replace all predicate names with random 6-character alphanumeric strings.
The mapping is deterministic given the RNG seed: the same predicate always
maps to the same random name within one formula.

- **Input:**  `all x.(Dog(x) -> Animal(x))`
- **Output:** `all x.(Xk3mq2(x) -> Rv9pl1(x))` (varies by seed)
- **Applicability:** Always applicable when predicates exist.

## Dispatch Rules

Within each tier, operators are shuffled by the session RNG and tried in
order.  The first operator that:
1. Does not raise `NotApplicable`
2. Produces an output that round-trips through `str()` -> `parse_fol()`

is selected.  If no operator in the tier succeeds, the candidate slot is
marked as failed.

For Tier B (which needs 2 candidates per premise), the second call excludes
the operator used by the first call via `exclude_ops`.
