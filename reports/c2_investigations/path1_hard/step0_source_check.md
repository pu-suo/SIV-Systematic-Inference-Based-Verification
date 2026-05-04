# Step 0: Source Check — SIV Pipeline on Out-of-Distribution FOL

## ProofWriter Assessment

ProofWriter (`tasksource/proofwriter`) is available (174,476 examples, 18,626 at depth≥3) but uses **NL-format theories** (English sentences for rules and facts), NOT FOL annotations. The v2 parser requires FOL input strings. Converting ProofWriter NL→FOL would require an LLM call, reintroducing the circularity we eliminated.

**Decision: ProofWriter is not directly usable.** Fall back to hand-constructed FOL.

## Hand-constructed FOL Pipeline Test

Tested 5 hand-constructed formulas targeting depth-3+ complexity:
1. Triple-nested quantifiers with compound restrictor — **PASS**
2. Multi-quantifier with nested existential — **PASS**
3. Nested universal with biconditional + function term — **FAIL** (function terms not supported)
4. Complex restrictor with disjunction — **PASS**
5. Triple nested with mixed quantifiers — **PASS**

| Metric | Rate |
|--------|------|
| Parse | 4/5 (80%) |
| Suite generation | 4/5 (80%) |
| Round-trip Vampire equivalence | 4/5 (80%) |

All rates ≥80%. The single failure used a function term `Preimage(f,s)` as a predicate argument, which exceeds the v2 parser schema (flat terms only).

## Constraints on Hand-constructed FOL

Valid constructs (parser handles):
- Nested quantifiers (∀x.∃y.∀z...)
- Multi-conjunct restrictors
- Mixed quantifier types
- Binary and n-ary predicates
- Equality
- All connectives (∧, ∨, →, ↔, ⊕)
- Nested existentials inside universals

Invalid (avoid):
- Function terms as predicate arguments (e.g., `P(f(x))`)
- Higher-order quantification

## Decision

**PROCEED** with hand-constructed FOL as candidate source. Pipeline generalizes to complex first-order formulas without function terms. Difficulty will come from:
- Quantifier nesting depth (3+)
- Multi-conjunct restrictors
- Mixed quantifier scopes
- Multi-predicate interactions requiring careful coordination
