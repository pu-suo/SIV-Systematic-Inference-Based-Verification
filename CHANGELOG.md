# Changelog

## 2.0.0 — 2026-04-15

The v2 refactor. SIV is rebuilt from the ground up around a Frege-closed
four-case `Formula` type, a recursive compiler, and a Vampire-enforced
soundness invariant. See `docs/SIV.md` for the full specification.

### Added
- **Schema** (§6.2, `siv/schema.py`). Four-case `Formula`:
  atomic / quantification / negation / connective. Tripartite
  quantification (Barwise–Cooper 1981 / Heim 1982 / Kamp 1981) with
  explicit `inner_quantifications`. Bound-variable-in-restrictor
  invariant (C2). `TestSuite` / `UnitTest` with `mutation_kind`.
- **JSON Schema derivation** (§6.2.7, `siv/json_schema.py`). Single
  source of truth derived from the Pydantic model; no hand-rolled JSON.
- **Compiler** (§6.4, `siv/compiler.py`). Two structurally distinct
  recursive paths (`compile_canonical_fol`, `compile_sentence_test_suite`)
  whose agreement is enforced by C9a. Polarity-aware sub-entailment
  emission per §6.4 Amendment B-revised.
- **Pre-analyzer** (§6.1, `siv/pre_analyzer.py`). Two deterministic
  tripwire flags: `requires_restrictor`, `requires_negation`.
- **Extractor** (§6.3, `siv/extractor.py`). Frozen LLM bound to the
  derived JSON Schema; one retry on validation or tripwire violation.
  Fifteen few-shot gold examples covering all four `Formula` cases.
- **Contrastive generator** (§6.5, `siv/contrastive_generator.py`). Six
  tree-walking mutation operators; Vampire-filtered with two-level
  witness axioms (Barwise–Cooper existential import at predicate and
  quantification-restrictor levels, Amendment E).
- **Scorer** (§6.6, `siv/scorer.py`). Recall / precision / F1;
  recall-only when the source is structurally weak (§6.5 structural
  coverage limits). `precision` and `f1` are `Optional[float]`.
- **Invariants** (§8, `siv/invariants.py`). `check_entailment_monotonicity`
  (C9a, without witness axioms) and `check_contrastive_soundness` (C9b,
  with witness axioms). CI (`.github/workflows/soundness.yml`) fails
  the build on violation.
- **Invariant corpus** (`tests/data/invariant_corpus.json`). 22 sentences
  covering nested quantification, three-way disjunction, negation of
  implication, quantified biconditional, and more.
- **FOLIO evaluation** (§17, `scripts/run_folio_evaluation.py`).
  Self-consistency + FOLIO-faithfulness measurement modes; reports
  written to `reports/folio_agreement.json`.

### Removed
- `siv/generator.py`, `siv/verifier.py`, `siv/vllm_backend.py`,
  `siv/_bootstrap.py` — not on the §9 dependency list.
- `scripts/siv_generate.py`, `scripts/siv_inspect.py`,
  `scripts/siv_score.py` — replaced by `python -m siv extract`.
- `prompts/generation_*.{txt,json}`, `prompts/predicability_check.txt`.
- v1-era tests: `test_generator.py`, `test_invariants.py`,
  `test_metric_properties.py`, `test_regression_1208.py`,
  `test_siv_*_script.py`, `test_soundness_tripwires.py`,
  `test_verifier.py`.
- Forbidden v1 identifiers: `MacroTemplate`, `macro_template`,
  `universal_affirmative`, `Fact`, `is_fol_expressible`,
  `rejection_reason`, `FOLRejectionReason`, `rejection_note`,
  `coverage_fraction`, `is_collective`, `detected_modal`,
  `detected_temporal`, `detected_proportional`,
  `proportional_quantifier`, `PROPORTIONAL_QUANTIFIER`,
  `plural_non_distributive` — per §5.

### Headline empirical result (Phase 5, §17)

Run on the full FOLIO validation split (377 unique premises):

- **Self-consistency `logical_recall = 1.000`** (397/397 entailed
  positives, 24 Vampire timeouts, 0 logical disagreements). Pipeline
  internally coherent at scale.
- **Pipeline extraction failure rate: 7.1%** (23/326 excluding OpenAI
  rate-limit errors). Total with rate limits: 19.4%.
- **FOLIO-faithfulness mean F1 = 0.355** across 303 evaluated premises.
- **Compound-restrictor-universal class (v1-bug target): mean F1 = 0.186**
  across 39 premises, with 27 confirmed **restrictor-collapse** cases.

This confirms the paper's thesis: FOLIO gold translations have
systematic faithfulness failures on quantified sentences with
restrictive relative clauses, invisible to existing metrics and caught
mechanically by SIV.

## 1.x (archived)

v1 development history preserved under `docs/archive/`.
