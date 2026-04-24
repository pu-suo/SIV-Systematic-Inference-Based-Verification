# SIV — Soundness-Invariant Verification for NL → FOL

SIV evaluates natural-language-to-First-Order-Logic translations by testing
whether a candidate FOL formula entails the atomic claims the source
sentence actually makes. It replaces exact-match, denotation-accuracy, and
n-gram metrics with a Vampire-verified, structurally grounded F1.

The claim SIV is designed to defend: **a translation is faithful iff every
atomic proposition in the source is independently entailed by the
translation, and every structural contradiction of the source is
independently refuted.**

## Architecture (seven components, §6 of `docs/SIV.md`)

1. **Pre-analyzer** (`siv/pre_analyzer.py`) — spaCy-based, emits two
   tripwire flags: `requires_restrictor`, `requires_negation`.
2. **Schema** (`siv/schema.py`) — `SentenceExtraction` / `Formula`;
   Frege-closed four-case `Formula` type (atomic, quantification,
   negation, connective); `TestSuite` / `UnitTest`.
3. **Extractor** (`siv/extractor.py`) — frozen LLM call bound to the
   Pydantic-derived JSON Schema (`siv/json_schema.py`); one retry on
   violation.
4. **Compiler** (`siv/compiler.py`) — two structurally distinct recursive
   paths over `Formula`. Pure function of the extraction; never reads `nl`.
5. **Contrastive generator** (`siv/contrastive_generator.py`) — six
   mutation operators, filtered by Vampire with witness axioms.
6. **Scorer** (`siv/scorer.py`) — Vampire-checked recall/precision/F1;
   recall-only when the source is structurally weak (§6.5 structural
   coverage limits).
7. **Invariants** (`siv/invariants.py`) — CI-enforced entailment
   monotonicity (C9a) and contrastive soundness (C9b).

Supporting modules: `siv/vampire_interface.py`, `siv/fol_utils.py`,
`siv/frozen_client.py`, `siv/frozen_config.py`, `siv/aligner.py` (soft
cross-vocabulary scoring), `siv/stratum_classifier.py` (gold FOL
classification), `siv/nltk_perturbations.py` (AST-level FOL
perturbations), `siv/test_suite_generator.py` (composing extraction +
compilation + test generation into one callable).

## Quick start

```bash
# 1. Install dependencies.
bash scripts/setup.sh
# — or manually:
pip install -r requirements.txt
python -m spacy download en_core_web_sm
python -c "from siv.vampire_interface import setup_vampire; setup_vampire('.')"

# 2. Put OPENAI_API_KEY in .env at the repo root.
echo "OPENAI_API_KEY=sk-..." > .env

# 3. Generate a test suite for a single sentence.
python scripts/generate_siv_tests.py "All employees who schedule meetings attend the company building." --pretty
```

## Pipeline

SIV's evaluation pipeline is split into four independent, cacheable scripts.
Each produces a frozen artifact consumed by the next.

### 1. Generate test suites (NL → SIV tests)

For each natural language premise, extracts an atomic fact structure via a
frozen LLM call, compiles it into a canonical FOL, and generates a test
suite of positive entailments and contrastive mutants.

```bash
# Single sentence → JSON to stdout:
python scripts/generate_siv_tests.py "All dogs are mammals." --pretty

# Batch — all FOLIO train premises → frozen JSONL artifact:
python scripts/generate_folio_test_suites.py --split train

# Output: reports/human_study/test_suites.jsonl
```

The test suites are the most important artifact. They are generated once
and frozen — downstream scoring loads them without re-running extraction.

### 2. Generate candidates (NL → candidate FOLs)

Produces candidate translations from multiple sources: FOLIO gold,
GPT-4o, GPT-4o-mini, and four tiers of AST perturbations (subtle,
meaning-altering, clearly wrong, nonsense). No SIV involvement — candidates
are independent of the metric.

```bash
# Full run (requires OPENAI_API_KEY):
python scripts/generate_candidates.py --split train

# Dry run (skip LLM calls):
python scripts/generate_candidates.py --split train --limit 10 --skip-models

# Output: reports/human_study/candidates.jsonl
```

### 3. Score candidates (test suites × candidates → scores)

Joins saved test suites with saved candidates and scores each pair using
Vampire. Supports strict mode (SIV vocabulary) and soft mode
(embedding-based cross-vocabulary alignment).

```bash
python scripts/score_candidates.py \
  --test-suites reports/human_study/test_suites.jsonl \
  --candidates reports/human_study/candidates.jsonl

# Output: reports/human_study/scored_candidates.jsonl
```

### Data flow

```
FOLIO NL premises
    │
    ├─→ generate_folio_test_suites.py ─→ test_suites.jsonl
    │       LLM extract → compile → Vampire contrastives
    │
    └─→ generate_candidates.py ─→ candidates.jsonl
            gold + model translations + perturbations

test_suites.jsonl + candidates.jsonl
    │
    └─→ score_candidates.py ─→ scored_candidates.jsonl
            Vampire scoring (strict + soft mode)
```

## Programmatic usage

```python
from openai import OpenAI
from dotenv import load_dotenv
from siv.frozen_client import FrozenClient
from siv.test_suite_generator import generate_test_suite
from siv.scorer import score
from siv.schema import TestSuite, UnitTest, SentenceExtraction

load_dotenv()
client = FrozenClient(OpenAI())

# Generate a complete test suite from NL
suite_dict = generate_test_suite(
    "All employees who schedule meetings attend the company building.",
    client,
)

print(f"Canonical: {suite_dict['canonical_fol']}")
print(f"Positives: {len(suite_dict['positives'])}")
print(f"Contrastives: {len(suite_dict['contrastives'])}")

# Score a candidate against the test suite
extraction = SentenceExtraction(**suite_dict["extraction_json"])
test_suite = TestSuite(
    extraction=extraction,
    positives=[UnitTest(**t) for t in suite_dict["positives"]],
    contrastives=[UnitTest(**t) for t in suite_dict["contrastives"]],
)
report = score(test_suite, suite_dict["canonical_fol"])
print(f"recall={report.recall} precision={report.precision} f1={report.f1}")
```

## Running tests

```bash
pytest tests/                                 # all mocked + deterministic tests
pytest tests/test_soundness_invariants.py     # C9a / C9b on the 22-sentence corpus
OPENAI_API_KEY=sk-... pytest tests/test_extraction_roundtrip.py  # live round-trip
```

## Analysis scripts

| Script | Purpose |
|--------|---------|
| `scripts/run_folio_evaluation.py` | Legacy monolith — runs full SIV pipeline on FOLIO validation |
| `scripts/categorize_folio_results.py` | Classify divergence patterns (vocab, restrictor, entity, quantifier) |
| `scripts/compute_baseline_metrics.py` | BLEU / BERTScore / exact-match baselines |
| `scripts/generate_annotation_set.py` | Stratified annotation sheet generation for human study |
| `scripts/analyze_annotations.py` | Inter-annotator agreement and metric correlation |
| `scripts/soft_alignment_diagnostics.py` | Diagnostic report for soft cross-vocabulary scoring |

## Documentation

- `docs/SIV.md` — the single canonical specification.
- `docs/perturbation_recipe.md` — frozen spec of all FOL perturbation operators.
- `docs/translation_prompt.md` — frozen NL→FOL prompt for model translations.

## License

See `LICENSE`.
