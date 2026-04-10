# SIV: Systematic Inference-Based Verification for NL-to-FOL Translation

SIV is a **neuro-symbolic evaluation framework** that replaces sparse dataset supervision with dense, faithful unit tests for scoring natural language → first-order logic (FOL) translation.

Instead of checking whether a model's output exactly matches a gold formula, SIV compiles each natural language sentence into a **test suite** of positive and negative FOL unit tests, then verifies candidates against it using a tiered pipeline that escalates from cheap string matching to full theorem proving only when necessary.

---

## Key Ideas

| Concept | Description |
|---|---|
| **Stage 1 Pre-Analysis** | Symbolic analysis of modifier+noun compounds before calling the LLM — computes WordNet, PMI, POS, and dependency signals to decide KEEP vs. SPLIT |
| **Stage 2 Extraction** | GPT-4o (or rule-based fallback) extracts entities and facts into a minimal JSON schema guided by the pre-analysis |
| **Stage 3 Compilation** | Deterministic mapping from the JSON extraction to FOL unit tests using arity-based templates and Aristotelian macro-forms |
| **Tiered Verifier** | Tier 0 (syntax) → Tier 1 (strict vocabulary) → Tier 2 (AST patterns) → Tier 3 (Vampire prover) |
| **SIV Score** | F1 of recall rate (positive tests passed) and precision rate (negative/contrastive tests rejected) |

---

## Project Structure

```
siv-project/
├── siv/                        # Core library
│   ├── schema.py               # Dataclasses: Entity, Fact, TestSuite, VerificationResult, …
│   ├── pre_analyzer.py         # Stage 1: compound analysis (spaCy + WordNet + PMI)
│   ├── extractor.py            # Stage 2: LLM / fallback entity+fact extraction
│   ├── compiler.py             # Stage 3: JSON extraction → FOL unit tests
│   ├── verifier.py             # Tiered verification with partial credit
│   ├── scorer.py               # SIV score computation and aggregation
│   ├── fol_utils.py            # FOL parsing, normalization, TPTP conversion (NLTK)
│   └── vampire_interface.py    # Vampire theorem prover interface
│
├── data/
│   ├── pmi_cache.json          # Pre-computed PMI from NLTK Brown corpus
│   └── perturbation_map.json   # Antonym vocabulary for contrastive tests
│
├── prompts/
│   ├── extraction_system.txt   # System prompt for Stage 2 LLM extraction
│   ├── extraction_examples.json# 5 few-shot examples covering all macro-forms
│   └── predicability_check.txt # Prompt template for plausibility checking
│
├── notebooks/
│   └── main.ipynb              # End-to-end pipeline (Colab-ready)
│
├── tests/                      # pytest test suite (98 tests)
│   ├── test_schema.py
│   ├── test_fol_utils.py
│   ├── test_pre_analyzer.py
│   ├── test_extractor.py
│   ├── test_compiler.py
│   ├── test_verifier.py
│   └── test_scorer.py
│
├── requirements.txt
└── CLAUDE_CODE_SPEC.md         # Full design specification
```

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

## Quickstart

```python
from siv.pre_analyzer import analyze_sentence
from siv.extractor import extract_problem
from siv.compiler import compile_test_suite
from siv.verifier import verify
from siv.scorer import score_candidates

# Stage 1: symbolic pre-analysis
analyses = analyze_sentence("The tall tree grows quickly.")
# → [CompoundAnalysis(modifier='tall', noun='tree', recommendation='SPLIT', …)]

# Stage 2: extraction (rule-based fallback, no API key needed)
problem = extract_problem(
    ["The crimson car is running.", "All cars have engines."],
    client=None, use_api=False, problem_id="demo"
)

# Stage 3: compile unit tests
suite = compile_test_suite(problem)
print(f"{suite.total_tests} tests: "
      f"{len(suite.positive_tests)} recall + {len(suite.negative_tests)} precision")

# Score FOL candidates
candidates = [
    "exists x.(Car(x) & Crimson(x) & Running(x))",
    "exists x.Car(x)",
]
scored = score_candidates(candidates, suite)
for cs in scored:
    print(f"SIV={cs.siv_score:.3f}  {cs.candidate_fol}")
```

With a GPT-4o API key:

```python
import openai
client = openai.OpenAI(api_key="sk-...")

problem = extract_problem(sentences, client=client, use_api=True)
```

---

## The Pipeline in Detail

### Stage 1 — Symbolic Pre-Analysis (`siv/pre_analyzer.py`)

Runs **before** the LLM. For each modifier+noun pair in a sentence (detected via spaCy dependency parsing), four signals are computed:

| Signal | Method | Effect |
|---|---|---|
| **A** WordNet hit | `wn.synsets(modifier_noun)` | If lexicalized → KEEP |
| **B** PMI score | log₂(P(m,n) / P(m)P(n)) from Brown corpus | High PMI → KEEP |
| **C** Proper noun | spaCy POS = PROPN | Named category → KEEP |
| **D** Dependency scope | Head noun's dep_ label | Subject-targeting + low PMI → SPLIT |

The recommendations are injected as structured context into the LLM prompt, giving the model objective evidence for its split/keep decisions.

### Stage 2 — LLM Extraction (`siv/extractor.py`)

A structured few-shot prompt asks GPT-4o to output:

```json
{
  "entities": [{"id": "e1", "surface": "tree", "entity_type": "existential"}],
  "facts":    [{"pred": "tall", "args": ["e1"], "negated": false}],
  "macro_template": "ground_positive"
}
```

**Macro templates** follow the Aristotelian Square of Opposition:

| Template | NL form | FOL skeleton |
|---|---|---|
| `universal_affirmative` (A) | All P are Q | `∀x(P(x) → Q(x))` |
| `universal_negative` (E) | No P are Q | `∀x(P(x) → ¬Q(x))` |
| `existential_affirmative` (I) | Some P are Q | `∃x(P(x) ∧ Q(x))` |
| `existential_negative` (O) | Some P are not Q | `∃x(P(x) ∧ ¬Q(x))` |
| `ground_positive` | P(c) | `P(c)` |
| `ground_negative` | ¬P(c) | `¬P(c)` |
| `conditional` | If A then B | `A → B` |
| `biconditional` | A iff B | `A ↔ B` |

A rule-based fallback (spaCy + NLTK POS) is used when no API key is available.

### Stage 3 — Test Compilation (`siv/compiler.py`)

Three categories of positive tests are generated:

1. **Vocabulary tests** — `exists x.Pred(x)` for every predicate
2. **Binding tests** — typed existentials and grounded atoms:
   - 1-arg existential: `exists x.(Tree(x) & Tall(x))`
   - 1-arg constant: `Queen(elizabeth)`
   - 2-arg relation: `Directed(lanaWilson, afterTiller)` or `exists x.(exists y.(SubjType(x) & ObjType(y) & Pred(x,y)))`
3. **Macro tests** — structural tests matching the sentence's logical form (e.g. `all x.(Kid(x) -> Young(x))` for TYPE_A)

**Negative (contrastive) tests** are generated by substituting each 1-arg predicate with its antonym from `data/perturbation_map.json`. The candidate must *not* entail these.

### Tiered Verifier (`siv/verifier.py`)

Tests are evaluated with escalating cost:

```
Tier 0 (syntax)       — NLTK parse check; fails fast on unparseable candidates
Tier 1 (vocabulary)   — strict predicate presence check (full match or zero)
Tier 2 (AST)          — lightweight structural matching without the prover
Tier 3 (Vampire)      — full theorem proving (only ~30% of tests reach this tier)
```

Tier 1 is strict: a predicate must appear as a standalone identifier in the candidate. A predicate embedded in a CamelCase compound (e.g. `CrimsonCar` for a test expecting `Crimson`) scores **0.0** — no partial credit. This directly enforces Tenet 1 (Strict Lexical Faithfulness).

### SIV Score (`siv/scorer.py`)

```
recall_rate    = recall_passed / effective_positive_tests
precision_rate = negative_tests_rejected / total_negative_tests
SIV score      = 2 · recall · precision / (recall + precision)   # F1
```

---

## Frozen Extraction Pipeline

All published SIV scores are produced by the **frozen extraction pipeline** (`siv/frozen_client.py`). Every API call to the LLM extractor uses a hardcoded model snapshot (`gpt-4o-2024-08-06`), a fixed random seed (42), temperature 0.0, and a JSON Schema `response_format` binding that structurally constrains the model's output — eliminating the need for hand-written JSON validation. The `system_fingerprint` returned by the API is logged on every call; drift from the session baseline triggers a warning so reproducibility claims remain honest. Responses are cached to `.siv_cache/extraction_cache.jsonl` (the cache directory is tracked in git via `.siv_cache/.gitkeep`; cache entries themselves are gitignored). Raw OpenAI clients passed to `extract_sentence` or `extract_problem` are automatically wrapped in `FrozenClient` — callers do not need to construct one explicitly. All reproducibility-relevant parameters (`PRIMARY_MODEL`, `SEED`, `TEMPERATURE`, `MAX_TOKENS`, `CACHE_DIR`) live in `siv/frozen_config.py`; no magic constants appear elsewhere in the codebase.

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

## Running Tests

```bash
pytest tests/ -v
```

98 tests covering all modules. Tests that require spaCy or NLTK are automatically skipped if the models/data are not installed.

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | `""` | OpenAI key for Stage 2 LLM extraction |
| `VAMPIRE_PATH` | `./vampire` | Path to Vampire binary |

In Google Colab, set `OPENAI_API_KEY` as a Colab secret (key icon in the left sidebar).

---

## Data

### `data/pmi_cache.json`

Pre-computed word and bigram frequencies from the NLTK Brown corpus (~1M words). Used by Stage 1 to compute PMI scores for modifier+noun pairs. Regenerate with:

```python
# Included in siv/pre_analyzer.py setup — runs automatically on first import
# To rebuild manually:
python -c "
import json, math, re
from collections import defaultdict
import nltk; nltk.download('brown')
from nltk.corpus import brown
# ... (see pre_analyzer.py _load_pmi_cache)
"
```

### `data/perturbation_map.json`

Hand-curated antonym vocabulary (~60 entries) used to generate contrastive negative tests. Extend this file to improve negative test quality.

### FOLIO Dataset

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

## Roadmap

- [ ] Phase 2: SIV-guided BRIO training (`notebooks/03_training.ipynb`)
- [ ] `data/calibration_set.json`: 50-example manually annotated calibration set
- [ ] `notebooks/01_pre_analysis_demo.ipynb`, `02_extraction_demo.ipynb`
- [ ] EPR vs. SIV score comparison table
- [ ] FOLIO schema inconsistency analysis

---

## Citation

If you use this framework, please cite the original SIV paper and the FOLIO dataset:

```bibtex
@misc{siv2024,
  title  = {SIV: Systematic Inference-Based Verification for NL-to-FOL Translation},
  year   = {2024}
}

@inproceedings{han2022folio,
  title     = {FOLIO: Natural Language Reasoning with First-Order Logic},
  author    = {Han, Simeng and Schoelkopf, Hailey and Zhao, Yilun and Qi, Zhenting and Riddell, Martin and Benson, Luke and Sun, Lucy and Zubova, Ekaterina and Qiao, Yujie and Burtell, Matthew and others},
  year      = {2022}
}
```

---

## License

MIT
