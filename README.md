# SIV — Sub-entailment Vector

SIV is a graded, per-aspect diagnostic metric for natural-language to
First-Order-Logic translation faithfulness. It scores a candidate FOL
translation against a *test suite* of positive entailments and
contrastive mutants derived deterministically from a gold FOL annotation,
verified by the Vampire theorem prover.

The test suites are produced by a deterministic parser of FOLIO gold FOL
(Stage 1, 94.2% coverage of the 1,675-premise corpus, 99.94% round-trip
Vampire equivalence on what it parses), so SIV never depends on an LLM
extraction step at evaluation time.

## Architecture

| Module | Role |
| --- | --- |
| `siv/fol_parser.py` | Deterministic FOLIO-gold-FOL → `SentenceExtraction`. |
| `siv/gold_suite_generator.py` | Compose parser + compiler + contrastive generator into a `TestSuite`. |
| `siv/compiler.py` | `SentenceExtraction` → canonical FOL + per-positive unit tests. |
| `siv/contrastive_generator.py` | Six mutation operators; Vampire-filtered with witness axioms. |
| `siv/scorer.py` | Vampire-checked recall / precision / F1; recall-only when the source is structurally weak. |
| `siv/vampire_interface.py` | `vampire` binary wrapper for entailment checks. |
| `siv/aligner.py` | Embedding-based cross-vocabulary symbol alignment (soft mode). |
| `siv/schema.py` | Core `Formula` / `TestSuite` / `UnitTest` / `SentenceExtraction` data model. |
| `siv/fol_utils.py` | FOL-string normalization. |
| `siv/stratum_classifier.py` | Gold-FOL stratum classification (used by `generate_candidates.py`). |
| `siv/nltk_perturbations.py` | AST-level FOL perturbation operators (used to generate broken candidates). |
| `siv/invariants.py` | C9a/C9b soundness invariants (CI-enforced via `tests/test_soundness_invariants.py`). |
| `siv/malls_le.py`, `siv/brunello_lt.py` | Baseline metrics (MALLS-LE, Brunello-LT). |

The Vampire binary itself ships at `./vampire`.

## Setup

```bash
bash scripts/setup.sh
# or:
pip install -r requirements.txt
python -m spacy download en_core_web_sm
python -c "from siv.vampire_interface import setup_vampire; setup_vampire('.')"
```

## Reproducing the headline results

The locked test-suite artifact is `reports/test_suites/test_suites.jsonl`
(1,471 premises, frozen). All headline experiments load it directly.

```bash
# Stage 1 — deterministic parser coverage.
python scripts/parser_coverage_report.py
# → reports/parser_coverage_report.json (94.2% / 99.94%)

# Generate / score candidates.
python scripts/generate_candidates.py --split train
python scripts/score_candidates.py \
  --test-suites reports/test_suites/test_suites.jsonl \
  --candidates candidates.jsonl

# Locked headline: Exp B (rank correlation; ρ = 0.8543, n=33 with regeneration).
python scripts/stage4_regenerate.py
python scripts/stage4_rescore_exp1.py
python scripts/stage4_rescore_exp2.py
# → reports/stage4/{stage4b_regeneration,rescore_exp1,rescore_exp2}.json

# Exp C1 — coarse / fine error-stratum macro-F1 (0.81 / 0.29).
python scripts/exp_c1_diagnostic_structure.py
# → reports/c1/

# Pre-registered nulls (supplementary).
python scripts/c2_investigation_4.py
python scripts/c2_path1_step1.py
python scripts/c2_path1_hard_step5_main_v2.py
# → reports/c2_investigations/{investigation_4_*, path1/, path1_hard/}
```

## Repository layout

```
siv/                         core library
scripts/                     locked experiment runners
scripts/experiments/         Exp 1–3 runners (cached outputs in reports/experiments/)
tests/                       unit / soundness tests (pytest)
reports/                     all locked artifacts (parser coverage, test suites,
                             stage4 rescore, c1, experiments, c2 nulls)
docs/                        SIV.md (canonical spec), translation_prompt.md,
                             corrections_template.md (30 hand-corrected gold
                             annotations from Exp D)
```

## Tests

```bash
pytest tests/                                 # all mocked + deterministic tests
pytest tests/test_soundness_invariants.py     # C9a / C9b on the 22-sentence corpus
```

## Documentation

- `docs/SIV.md` — canonical specification.
- `docs/translation_prompt.md` — frozen NL→FOL prompt used for the human-study models.
- `docs/corrections_template.md` — the 30 hand-corrected FOLIO gold annotations (Exp D artifact).

## Prior exploration

An earlier iteration of this project used LLM-extracted canonical FOL as
the scoring reference. That direction was abandoned in favor of the
deterministic parser presented here, but the original pipeline is
preserved at <https://github.com/pu-suo/SIV-archive> for anyone interested
in revisiting it.

## License

See `LICENSE`.
