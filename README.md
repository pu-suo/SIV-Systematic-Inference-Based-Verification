# SIV: Systematic Inference-Based Verification for NL-to-FOL Translation

SIV is a neuro-symbolic evaluation framework for Natural Language to
First-Order Logic translation. It replaces Exact Match, Denotation
Accuracy, and n-gram metrics with a deterministic, atomic-faithfulness
test-suite approach.

This README is a quickstart and CLI reference. For the full philosophical
and architectural rationale, read the SIV Master Document.

> **No GPU required.** SIV's published metric path uses the OpenAI API for
> extraction and generation. All compilation, verification, and scoring is pure
> CPU. GPU is only needed for the optional vLLM backend (training experiments).

---

## Quick Start

### 1. Setup (one time)

    git clone <repo>
    cd siv-project
    bash scripts/setup.sh
    # Edit .env and add your OpenAI API key

### 2. Inspect a sentence

    python -m siv inspect "All dogs are mammals."

### 3. Inspect with candidate scoring

    python -m siv inspect "All dogs are mammals." \
        --candidate "all x.(Dog(x) -> Mammal(x))"

### 4. Score existing FOL candidates

    python -m siv score input.json --format human

### 5. Generate Clean-FOLIO translations

    python -m siv generate input.json --format json

### 6. Head-to-head comparison

    python -m siv generate input.json --compare-to-gold gold

---

## Environment

SIV reads its configuration from environment variables. The easiest
approach is to copy `.env.example` to `.env` and fill in your values:

    cp .env.example .env
    # Edit .env: set OPENAI_API_KEY=sk-...

The `.env` file is gitignored. You can also export variables directly:

    export OPENAI_API_KEY=sk-...

On Google Colab, use Colab Secrets (key icon in the left sidebar) to
set `OPENAI_API_KEY`.

---

## Vampire Theorem Prover

Vampire is optional but recommended for full-strength scoring.
`scripts/setup.sh` downloads it automatically. To install manually:

    python -c "from siv.vampire_interface import setup_vampire; setup_vampire()"

Or set `VAMPIRE_PATH` in your `.env` to point to an existing installation.

Without Vampire, SIV resolves tests at Tiers 0–2 only. Tests requiring
Tier 3 (full theorem proving) are marked "unresolved" and excluded from
the score denominator. This produces valid but less discriminating scores
for complex universally-quantified sentences.

---

## The Four Tenets

1. **Strict Lexical Faithfulness.** No stemming, no lemmatization, no
   WordNet, no synonym substitution. Exact surface forms only.
2. **Neo-Davidsonian Imperative.** Facts are unary or binary. Ternary and
   higher-arity predicates are schema violations.
3. **Structural Overlap over Deep Pragmatics.** SIV evaluates atomic
   logical n-grams, not full pragmatic parses.
4. **A Standard, Not a Safety Net.** Benchmark annotations that violate
   Tenets 1–3 score lower under SIV. SIV does not paper over bad
   annotations with multi-reference tolerance.

---

## The Pipeline

    NL sentence
         │
         ▼
    Stage 1: symbolic pre-analysis  (siv/pre_analyzer.py)
         │   (WordNet, PMI, POS, dep parse) → CompoundAnalysis
         ▼
    Stage 2: frozen LLM extraction  (siv/extractor.py + siv/frozen_client.py)
         │   (gpt-4o-2024-08-06, seed=42, temperature=0, JSON Schema binding)
         ▼
    Stage 3: Neo-Davidsonian validation  (siv/compiler.py::validate_neo_davidsonian)
         │   → SchemaViolation list; invalid extractions short-circuit to SIV=0
         ▼
    Stage 4: deterministic test-suite compilation  (siv/compiler.py)
         │   (vocabulary + binding + macro + contrastive perturbation tests)
         ▼
    Stage 5: tiered verification  (siv/verifier.py)
         │   Tier 0 syntax + consistency
         │   Tier 1 vocabulary
         │   Tier 2 AST
         │   Tier 3 Vampire
         ▼
    SIV score = F1(recall, precision)

---

## Two Modes

### Mode 1 — Evaluator (`scripts/siv_score.py`)

Score existing NL-to-FOL translations against a test suite derived from
the source sentences. Takes NL premises + candidate FOL strings, emits
per-premise and aggregate SIV scores.

### Mode 2 — Generator (`scripts/siv_generate.py`)

Compile validated extractions into Neo-Davidsonian-compliant FOL. The
Generator receives only the structured JSON extraction — never the
source NL — and its output must satisfy five programmatic invariants
before being accepted. Paired with `--compare-to-gold`, it produces the
head-to-head comparison the paper's empirical claims rest on.

---

## Soundness Defenses

SIV defends against the two general-purpose exploits of entailment-based
FOL evaluation:

1. **Inhabitation Preconditions** — every universal binding test is
   wrapped with `(exists x.T(x)) & all x.(T(x) -> ...)`. A candidate
   asserting an empty domain cannot vacuously satisfy universal tests.
2. **Tier 0 Consistency Check** — internally inconsistent candidates are
   flagged and short-circuited to SIV=0 before any entailment test runs.
   Ex falso quodlibet cannot produce a spurious perfect score.

See `tests/test_soundness_tripwires.py` for mechanical enforcement and
`tests/test_metric_properties.py` for property-test coverage.

---

## Reproducibility

All API calls route through `siv/frozen_client.py`, which pins:
- Model snapshot: `gpt-4o-2024-08-06`
- Seed: 42
- Temperature: 0.0
- Max tokens: 1200
- Response format: JSON Schema binding against `siv/schema.py`

The OpenAI `system_fingerprint` is logged on every call; drift emits a
WARNING. Extraction and generation results are cached on disk at
`.siv_cache/extraction_cache.jsonl` (gitignored) keyed by a SHA256 of
(model, system_prompt, few_shots, user_content).

Published SIV scores require the frozen API extractor. Outputs from
`siv/vllm_backend.py` are not published SIV scores.

---

## Running Tests

    pytest tests/ -v

Key test files:
- `tests/test_regression_1208.py` — FOLIO Problem 1208 end-to-end
- `tests/test_soundness_tripwires.py` — philosophical trip-wires
- `tests/test_metric_properties.py` — mathematical property tests
- `tests/test_generator.py` — Generator invariants

---

## Project Structure

    siv/
      schema.py             # Dataclasses: Entity, Fact, TestSuite, VerificationResult, ...
      pre_analyzer.py       # Stage 1 symbolic pre-analysis
      frozen_config.py      # Pinned model, seed, temperature, cache paths
      frozen_client.py      # FrozenClient wrapper for extract() and generate()
      extractor.py          # Stage 2 LLM extraction through FrozenClient
      compiler.py           # Stage 3 Neo-Davidsonian validation + test compilation
      verifier.py           # Tiered verification with Tier 0 consistency
      scorer.py             # SIV score aggregation
      generator.py          # Mode 2: JSON-only compilation to Neo-Davidsonian FOL
      invariants.py         # Five invariants enforced on Generator outputs
      vampire_interface.py  # Vampire prover + satisfiability
      vllm_backend.py       # NOT A PUBLISHED METRIC PATH
    prompts/
      extraction_system.txt
      extraction_examples.json
      generation_system.txt
      generation_examples.json
    scripts/
      setup.sh              # One-command setup
      siv_inspect.py        # Mode 1: inspect extraction and test suite
      siv_score.py          # Mode 2: score FOL candidates (Evaluator)
      siv_generate.py       # Mode 3: generate FOL (Generator)
    tests/
      test_schema.py
      test_compiler.py
      test_verifier.py
      test_extractor.py
      test_frozen_client.py
      test_scorer.py
      test_generator.py
      test_invariants.py
      test_metric_properties.py
      test_soundness_tripwires.py
      test_regression_1208.py
      test_siv_score_script.py
      test_siv_generate_script.py

---

## Installation

### Local

```bash
git clone https://github.com/<your-username>/siv-project.git
cd siv-project

pip install -r requirements.txt
python -m spacy download en_core_web_sm

python -c "import nltk; [nltk.download(r) for r in \
    ['wordnet', 'averaged_perceptron_tagger_eng', 'punkt_tab', 'brown']]"
```

### Google Colab

Open `notebooks/main.ipynb` in Colab. Cell 1 runs all installs automatically.

---

## Vampire Setup

Vampire is optional. Tests unresolvable at Tier 1–2 are marked "unresolved" when Vampire is unavailable.

**Linux / Colab:**
```python
from siv.vampire_interface import setup_vampire
setup_vampire()   # downloads Vampire 4.8 binary to ./vampire
```

**macOS:**
```python
setup_vampire()   # downloads macOS binary
```

Or set the `VAMPIRE_PATH` environment variable to point to an existing binary.

---

## Evaluator CLI (`scripts/siv_score.py`)

Scores FOL candidate translations against NL premises using the full frozen SIV pipeline.

### Prerequisites

```bash
export OPENAI_API_KEY=sk-...
```

### Usage

```bash
# Score all problems in an input file (human-readable output)
python -m scripts.siv_score path/to/input.json

# Machine-readable JSON output
python -m scripts.siv_score path/to/input.json --format json

# Write output to a file
python -m scripts.siv_score path/to/input.json --format json --output results.json

# Score a single problem by ID
python -m scripts.siv_score path/to/input.json --problem-id folio_1208

# Allow prover-unresolved tests (exclude from denominator instead of aborting)
python -m scripts.siv_score path/to/input.json --unresolved-policy exclude
```

### Input format

```json
[
  {
    "problem_id": "folio_1208",
    "premises": [
      "All employees who schedule a meeting with their customers will go to the company building today.",
      "Everyone who goes to the company building today will eat in the company building."
    ],
    "candidates": {
      "gold": "all x.((Employee(x) & exists y.(Meeting(y) & Schedule(x,y))) -> AppearIn(x,companyBuilding))",
      "model_a": "..."
    }
  }
]
```

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Normal run (low scores are not errors) |
| `1` | Catastrophic failure (API error, unhandled exception) |
| `2` | Configuration error (missing `OPENAI_API_KEY`, invalid input) |

---

## Generator CLI (`scripts/siv_generate.py`)

Produces Clean-FOLIO: Neo-Davidsonian, extensible, provably SIV-compliant FOL.

### Usage

```bash
# Generate Clean-FOLIO JSON for all problems in an input file
python -m scripts.siv_generate path/to/input.json

# Human-readable output
python -m scripts.siv_generate path/to/input.json --format human

# Write output to a file
python -m scripts.siv_generate path/to/input.json --output clean_folio.json

# Process a single problem by ID
python -m scripts.siv_generate path/to/input.json --problem-id folio_1208

# Head-to-head comparison: generated FOL vs. an existing gold candidate
python -m scripts.siv_generate path/to/input.json --compare-to-gold gold
```

### Refusals

The Generator refuses at two stages:

| Stage | Cause | `refusal_stage` |
|---|---|---|
| Pre-call | Extraction has Neo-Davidsonian violations (ternary facts, prepositional unary) | `"pre_call"` |
| Post-call | Generated FOL fails one or more of the five invariants | `"post_call"` |

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Normal run |
| `1` | Catastrophic failure (API error, unhandled exception) |
| `2` | Configuration error (missing `OPENAI_API_KEY`, invalid input) |

---

## FOLIO Dataset

The FOLIO evaluation dataset is downloaded at runtime from HuggingFace (`yale-nlp/FOLIO`) if `data/folio_problems.json` is not present. To use a local copy, place it at `data/folio_problems.json` in the format:

```json
[
  {
    "id": "problem_001",
    "premises": ["All dogs are animals.", "Fido is a dog."],
    "hypothesis": "Fido is an animal.",
    "hypothesis_fol": "Animal(fido)",
    "label": "True"
  }
]
```

---

## License

MIT
