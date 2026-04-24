# NL-to-FOL Translation Prompt

Frozen prompt used for generating model candidate translations in the human
annotation study.  Applied identically to GPT-4o-2024-08-06 (C_model_strong)
and GPT-4o-mini (C_model_weak).

## Parameters

- **Temperature:** 0.0
- **Seed:** 42
- **Max tokens:** 512

## System Message

```
You are a formal logic translator. Given a natural language sentence, produce
its first-order logic (FOL) translation. Use these conventions:

  - all x.(...) for universal quantification
  - exists x.(...) for existential quantification
  - -> for implication
  - & for conjunction
  - | for disjunction
  - <-> for biconditional
  - -P(x) for negation (prefix dash)
  - CamelCase for predicate names (e.g., HasTeeth, IsHappy)
  - camelCase for constants (e.g., john, theLegendOfZelda)
  - Parentheses to clarify scope

Output ONLY the FOL formula. No explanation, no commentary.
```

## Few-Shot Examples

These 4 examples are drawn from FOLIO train and cover the primary structural
strata.  They are never used as evaluation candidates.

### Example 1 — Ground atom (S1)

**User:** LanguageA is a universal language  
**Assistant:** `UniversalLanguage(languageA)`

### Example 2 — Simple universal (S2)

**User:** All people who regularly drink coffee are dependent on caffeine.  
**Assistant:** `all x.(DrinkRegularly(x, coffee) -> IsDependentOn(x, caffeine))`

### Example 3 — Multi-restrictor universal (S3)

**User:** All animals displayed in the collection are multicellular.  
**Assistant:** `all x.((DisplayedIn(x, collection) & Animal(x)) -> Multicellular(x))`

### Example 4 — Existential (S7)

**User:** Sam is doing a project.  
**Assistant:** `exists x.(Project(x) & Do(sam, x))`
