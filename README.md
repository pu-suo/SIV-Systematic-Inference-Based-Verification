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

`siv/vampire_interface.py`, `siv/fol_utils.py`, `siv/frozen_client.py`, and
`siv/frozen_config.py` are supporting modules. Dependencies are in
`docs/SIV.md` §9. Nothing else is part of SIV.

## Quick start

```bash
# 1. Create a virtualenv, install dependencies.
pip install pydantic openai nltk spacy pytest python-dotenv datasets
python -m spacy download en_core_web_sm

# 2. Install Vampire for your platform (macOS/Linux binaries auto-downloaded).
python -c "from siv.vampire_interface import setup_vampire; setup_vampire('.')"

# 3. Put OPENAI_API_KEY in .env at the repo root.
echo "OPENAI_API_KEY=sk-..." > .env

# 4. Extract a sentence.
python -m siv extract "All employees who schedule meetings attend the company building."
```

## Minimal example (all four Formula cases)

```python
from openai import OpenAI
from dotenv import load_dotenv
from siv.compiler import compile_canonical_fol, compile_sentence_test_suite
from siv.extractor import extract_sentence
from siv.frozen_client import FrozenClient
from siv.scorer import score

load_dotenv()
client = FrozenClient(OpenAI())

sentences = [
    "Miroslav Venhoda was a Czech choral conductor.",          # atomic
    "All employees who schedule meetings attend the company building.",  # quantification
    "It is not the case that Alice is tall and Bob is short.", # negation
    "Alice is tall and Bob is short.",                         # connective
]

for nl in sentences:
    extraction = extract_sentence(nl, client)
    canonical = compile_canonical_fol(extraction)
    suite = compile_sentence_test_suite(extraction)
    report = score(suite, canonical)
    print(f"{nl}\n  canonical: {canonical}")
    print(f"  recall={report.recall} precision={report.precision} f1={report.f1}")
```

The canonical FOL is expected to score `recall = 1.0` on its own test
suite for every example; `precision` and `f1` are `None` when the source is
structurally weak (top-level disjunction, bare implication with atomic
antecedent, or existential over a compound nucleus — see §6.5).

## Running the test suite

```bash
pytest tests/                                 # all mocked + deterministic tests
pytest tests/test_soundness_invariants.py     # C9a / C9b on the 22-sentence corpus
OPENAI_API_KEY=sk-... pytest tests/test_extraction_roundtrip.py  # live round-trip
```

## FOLIO evaluation

`scripts/run_folio_evaluation.py` runs SIV against every unique premise in
the FOLIO validation split in two modes:

- **Self-consistency.** Score `compile_canonical_fol(extraction)` against
  the derived test suite. Measures pipeline coherence.
- **FOLIO-faithfulness.** Score FOLIO's gold FOL against the derived test
  suite. Measures how faithful the benchmark's translations are.

Output is written to `reports/folio_agreement.json`. See `docs/SIV.md` §17.

## Documentation

- `docs/SIV.md` — the single canonical specification.
- `docs/archive/` — historical v1 documents (read-only).

## License

See `LICENSE`.
