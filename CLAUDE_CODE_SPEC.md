# CLAUDE CODE IMPLEMENTATION PROMPT
## SIV: Systematic Inference-Based Verification for NL-to-FOL Translation

---

## HOW TO USE THIS DOCUMENT

This document is a complete specification for Claude Code (VS Code plugin) to generate the codebase for the SIV project. 

### Interacting with Claude Code in VS Code:

1. **Open your project folder** in VS Code (create a new empty folder like `siv-project/`)
2. **Open the Claude Code panel** (Cmd+Shift+P → "Claude Code: Open")
3. **Paste the following as your first prompt:**

```
Read the file CLAUDE_CODE_SPEC.md in this project root. It contains the complete 
specification for a neuro-symbolic NL-to-FOL verification system. Please:

1. First, create the project directory structure as specified
2. Then implement each module one at a time, starting with siv/schema.py
3. After each module, pause and let me review before continuing
4. The entry point is a Jupyter notebook (notebooks/main.ipynb) that runs on Google Colab
5. All file paths should work when the project is uploaded to Google Colab

Start by creating the directory structure and siv/schema.py.
```

4. **Place this spec file** as `CLAUDE_CODE_SPEC.md` in the project root
5. **Also place** the existing `SIV_Evaluation_Framework__3_.ipynb` notebook in the root so Claude Code can reference the existing patterns

### Tips for working with Claude Code:
- Ask it to implement ONE module at a time, review, then continue
- If it deviates from the spec, paste the relevant section back
- Use "implement siv/compiler.py following the spec in CLAUDE_CODE_SPEC.md" for each file
- Ask it to write tests as it goes: "now write tests/test_compiler.py for the module you just created"

---

## 1. PROJECT STRUCTURE

```
siv-project/
├── CLAUDE_CODE_SPEC.md          # This document
├── requirements.txt              # All pip dependencies
├── setup.py                      # Package setup (optional)
│
├── siv/                          # Core library
│   ├── __init__.py
│   ├── schema.py                 # JSON schema dataclasses
│   ├── pre_analyzer.py           # Stage 1: symbolic pre-analysis
│   ├── extractor.py              # Stage 2: LLM extraction with enriched prompts
│   ├── compiler.py               # Stage 3: JSON → FOL unit test compilation
│   ├── verifier.py               # Tiered verification pipeline
│   ├── scorer.py                 # SIV score computation with partial credit
│   ├── fol_utils.py              # FOL parsing, normalization, TPTP conversion
│   └── vampire_interface.py      # Vampire theorem prover interface
│
├── data/                         # Data files
│   ├── folio_problems.json       # Parsed FOLIO dataset
│   ├── calibration_set.json      # 50-example manually annotated calibration set
│   ├── pmi_cache.json            # Pre-computed PMI scores
│   └── perturbation_map.json     # Contrastive antonym/perturbation vocabulary
│
├── notebooks/                    # Jupyter notebooks (Colab entry points)
│   ├── main.ipynb                # Main pipeline: end-to-end SIV evaluation
│   ├── 01_pre_analysis_demo.ipynb    # Demo Stage 1 only
│   ├── 02_extraction_demo.ipynb      # Demo Stage 2 only
│   └── 03_training.ipynb             # SIV-guided BRIO training (Phase 2)
│
├── prompts/                      # LLM prompt templates
│   ├── extraction_system.txt     # System prompt for Stage 2 extraction
│   ├── extraction_examples.json  # Few-shot examples for extraction
│   └── predicability_check.txt   # Prompt for Signal 3 (predicability test)
│
└── tests/                        # Unit tests
    ├── test_schema.py
    ├── test_pre_analyzer.py
    ├── test_compiler.py
    ├── test_verifier.py
    └── test_scorer.py
```

---

## 2. DEPENDENCIES (requirements.txt)

```
# Core ML
torch>=2.0
transformers>=4.35
datasets>=2.14
accelerate>=0.24
sentencepiece

# NLP / Symbolic
nltk>=3.8
spacy>=3.7

# API
openai>=1.0

# Data
pandas>=2.0
numpy>=1.24
tqdm

# Testing
pytest>=7.0
```

**Colab-specific setup** (goes in the notebook, not requirements.txt):
```python
!pip install -q transformers datasets torch nltk sentencepiece accelerate openai pandas spacy tqdm
!python -m spacy download en_core_web_sm
import nltk
nltk.download('wordnet')
nltk.download('averaged_perceptron_tagger_eng')
nltk.download('punkt_tab')
```

---

## 3. MODULE SPECIFICATIONS

### 3.1 siv/schema.py — Data Classes

This module defines all the dataclasses used throughout the pipeline.

```python
"""
SIV Schema: Core data structures for the pipeline.

The JSON extraction schema has two lists:
  - entities: what things exist in the world
  - facts: what is true about them (pred + args)

Each fact's arity (len(args)) implicitly encodes its type:
  1-arg → unary predicate (type or property)
  2-arg → binary relation or reified attribute
  3-arg → ternary relation

The macro_template field on sentences captures the logical skeleton
using the Aristotelian categorical forms (A, E, I, O) plus ground
facts and conditionals.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum

class EntityType(Enum):
    CONSTANT = "constant"     # Named individual: nancy, garfield, google
    EXISTENTIAL = "existential"  # "a car", "some bears"
    UNIVERSAL = "universal"    # "all kids", "every student"

class MacroTemplate(Enum):
    """
    The 7 canonical sentence forms, grounded in the Aristotelian
    Square of Opposition (A, E, I, O) + ground facts + conditional.
    
    Reference: Russell & Norvig AIMA Ch. 8; Aristotle's Prior Analytics.
    """
    # Categorical propositions (quantified)
    TYPE_A = "universal_affirmative"   # All P are Q:     ∀x(P(x) → Q(x))
    TYPE_E = "universal_negative"      # No P are Q:      ∀x(P(x) → ¬Q(x))
    TYPE_I = "existential_affirmative" # Some P are Q:    ∃x(P(x) ∧ Q(x))
    TYPE_O = "existential_negative"    # Some P are not Q: ∃x(P(x) ∧ ¬Q(x))
    # Ground facts (about constants)
    GROUND_POSITIVE = "ground_positive"  # P(c) or P(c) ∧ Q(c)
    GROUND_NEGATIVE = "ground_negative"  # ¬P(c)
    # Compositional
    CONDITIONAL = "conditional"          # A → B (where A, B are from above)
    BICONDITIONAL = "biconditional"      # A ↔ B or ¬(A ⊕ B)

@dataclass
class Entity:
    id: str                    # e1, e2, c1, c2, ...
    surface: str               # "nancy", "car", "Harvard student"
    entity_type: EntityType    # constant, existential, universal
    
@dataclass
class Fact:
    pred: str                  # predicate surface form: "tall", "directed by"
    args: List[str]            # argument IDs or literal constants
    negated: bool = False      # explicit negation in the source sentence

@dataclass 
class CompoundAnalysis:
    """Result of Stage 1 pre-analysis for one modifier+noun pair."""
    modifier: str
    noun: str
    wordnet_hit: bool
    pmi_score: float
    is_proper_noun: bool
    dep_scope: str             # "nsubj", "dobj", "pobj", etc.
    recommendation: str        # "KEEP" or "SPLIT"
    reason: str                # human-readable justification

@dataclass
class SentenceExtraction:
    """Complete extraction for one NL sentence."""
    nl: str                    # original natural language
    entities: List[Entity]
    facts: List[Fact]
    macro_template: MacroTemplate
    compound_analyses: List[CompoundAnalysis] = field(default_factory=list)

@dataclass
class ProblemExtraction:
    """Complete extraction for one FOLIO problem (multiple sentences)."""
    problem_id: str
    sentences: List[SentenceExtraction]
    
    @property
    def all_entities(self) -> List[Entity]:
        """Deduplicated entities across all sentences."""
        seen = set()
        result = []
        for s in self.sentences:
            for e in s.entities:
                if e.id not in seen:
                    seen.add(e.id)
                    result.append(e)
        return result
    
    @property
    def all_facts(self) -> List[Fact]:
        """All facts across all sentences."""
        return [f for s in self.sentences for f in s.facts]

@dataclass
class UnitTest:
    """A single FOL unit test."""
    fol_string: str            # The FOL formula (NLTK format)
    test_type: str             # "vocabulary", "binding", "entailment", "contrastive"
    is_positive: bool          # True = candidate MUST entail; False = must NOT entail
    source_fact: Optional[Fact] = None  # Which fact generated this test

@dataclass
class TestSuite:
    """Complete test suite for one FOLIO problem."""
    problem_id: str
    positive_tests: List[UnitTest]
    negative_tests: List[UnitTest]
    
    @property
    def total_tests(self) -> int:
        return len(self.positive_tests) + len(self.negative_tests)

@dataclass
class VerificationResult:
    """Result of verifying one candidate FOL against a test suite."""
    candidate_fol: str
    syntax_valid: bool
    recall_passed: int
    recall_total: int
    precision_passed: int
    precision_total: int
    tier1_skips: int           # Tests resolved at Tier 1 (vocabulary)
    tier2_skips: int           # Tests resolved at Tier 2 (AST)
    prover_calls: int          # Tests requiring Tier 3 (Vampire)
    partial_credits: Dict[str, float] = field(default_factory=dict)
    
    @property
    def recall_rate(self) -> float:
        if self.recall_total == 0:
            return 0.0
        # Include partial credits
        total_credit = sum(self.partial_credits.values())
        full_passes = self.recall_passed
        return (full_passes + total_credit) / self.recall_total
    
    @property
    def precision_rate(self) -> float:
        if self.precision_total == 0:
            return 1.0
        return self.precision_passed / self.precision_total
    
    @property
    def siv_score(self) -> float:
        r, p = self.recall_rate, self.precision_rate
        if r + p == 0:
            return 0.0
        return 2.0 * r * p / (r + p)
```

### 3.2 siv/pre_analyzer.py — Stage 1: Symbolic Pre-Analysis

```python
"""
Stage 1: Symbolic Pre-Analysis

Runs BEFORE the LLM extraction. Identifies modifier+noun compounds
in the sentence and computes four objective signals for each:

  Signal A: WordNet lookup (is it a lexicalized compound?)
  Signal B: PMI from corpus statistics (how strongly collocated?)
  Signal C: Proper noun check (from POS tags)
  Signal D: Dependency scope (does modifier attach to subject or object?)

Outputs per-compound recommendations (KEEP/SPLIT) that are injected
into the LLM extraction prompt.

Dependencies: spacy, nltk (wordnet)
"""
```

**Key functions to implement:**

```python
def analyze_sentence(sentence: str) -> List[CompoundAnalysis]:
    """
    Run full pre-analysis on one sentence.
    Returns a CompoundAnalysis for each modifier+noun pair found.
    """

def _find_compounds(doc) -> List[dict]:
    """
    Extract modifier+noun pairs from spaCy parse.
    Look for tokens with dep_ in ('amod', 'compound') whose
    head is a NOUN or PROPN.
    """

def _check_wordnet(modifier: str, noun: str) -> bool:
    """
    Check if modifier_noun exists as a WordNet synset.
    Try: modifier_noun, modifiernoun, modifier-noun
    """

def _compute_pmi(modifier: str, noun: str, freq_table: dict) -> float:
    """
    Compute Pointwise Mutual Information.
    PMI = log2(P(w1,w2) / (P(w1) * P(w2)))
    Use pre-cached frequency table from data/pmi_cache.json.
    If not in cache, return 0.0 (unknown → default to conservative KEEP).
    """

def _check_dep_scope(token) -> str:
    """
    Return the dependency label of the noun that the modifier attaches to.
    If the noun is nsubj → modifier targets the subject entity → SPLIT candidate
    If the noun is dobj/pobj → modifier targets an attribute → KEEP candidate
    """

def _make_recommendation(compound: dict) -> CompoundAnalysis:
    """
    Apply decision rule:
      1. WordNet hit → KEEP (lexicalized compound)
      2. Proper noun modifier → KEEP (named category)
      3. High PMI (> threshold) → KEEP (statistically fixed phrase)
      4. Modifier targets subject entity (dep=nsubj) AND low PMI → SPLIT
      5. Default → KEEP (conservative)
    """
```

**PMI Cache:** The `data/pmi_cache.json` file should be pre-computed. For the initial version, use NLTK's Brown corpus or a small Wikipedia sample. Format:
```json
{
  "word_freq": {"tall": 1234, "tree": 5678, ...},
  "bigram_freq": {"tall_tree": 23, "professional_athlete": 89, ...},
  "total_words": 1000000,
  "total_bigrams": 500000
}
```

### 3.3 siv/extractor.py — Stage 2: LLM Extraction

```python
"""
Stage 2: Enriched LLM Extraction

Takes a sentence + the Stage 1 compound analyses and calls GPT-4o
(or Claude) to extract entities and facts into the minimal JSON schema.

The compound analyses are injected into the prompt as structured context,
guiding the LLM's split/keep decisions with objective evidence.

The LLM also identifies the macro_template (which of the 7 Aristotelian
forms this sentence matches).
"""
```

**Key functions:**

```python
def extract_sentence(
    sentence: str,
    compound_analyses: List[CompoundAnalysis],
    client: OpenAI,
    model: str = "gpt-4o",
    use_api: bool = True
) -> SentenceExtraction:
    """
    Full extraction pipeline for one sentence.
    If use_api=False, falls back to rule-based extraction (for testing
    without API key).
    """

def extract_problem(
    problem_sentences: List[str],
    client: OpenAI,
    model: str = "gpt-4o"
) -> ProblemExtraction:
    """
    Extract all sentences in a FOLIO problem.
    Runs Stage 1 pre-analysis, then Stage 2 extraction for each sentence.
    Deduplicates entities across sentences.
    """

def _build_prompt(
    sentence: str,
    compound_analyses: List[CompoundAnalysis]
) -> List[dict]:
    """
    Build the chat messages for the LLM call.
    
    Structure:
      [0] system: base instructions + JSON schema + how to use compound analysis
      [1] user: few-shot example 1 (simple properties)
      [2] assistant: example 1 output
      [3] user: few-shot example 2 (named category + relation)
      [4] assistant: example 2 output
      [5] user: few-shot example 3 (reified attribute)
      [6] assistant: example 3 output
      [7] user: "COMPOUND ANALYSIS:\n{analyses}\n\nSENTENCE: {sentence}"
    
    Returns: list of message dicts for openai.chat.completions.create()
    """

def _parse_response(response_text: str) -> dict:
    """
    Parse the LLM's JSON response. Handle markdown fencing.
    Validate against the schema (entities must have id/surface,
    facts must have pred/args).
    """

def _fallback_extraction(sentence: str) -> SentenceExtraction:
    """
    Rule-based fallback when API is unavailable.
    Uses spaCy NER + POS tagging for basic entity/fact extraction.
    Less accurate than LLM but allows end-to-end testing without API.
    """
```

**The system prompt** (stored in `prompts/extraction_system.txt`) must contain:
1. The JSON schema definition with examples
2. Rules for how to use compound analysis recommendations
3. The 7 macro_template types with descriptions
4. Instruction to use exact surface forms (no lemmatization)

**The few-shot examples** (stored in `prompts/extraction_examples.json`) must cover:
1. A sentence with splittable properties ("The tall red tree grows quickly")
2. A sentence with a named category and relation ("Lana Wilson directed After Tiller")
3. A sentence with a reified attribute ("The region has low rainfall")
4. A universally quantified rule ("All kids are young")
5. A ground fact about a constant ("Elizabeth is a queen")

### 3.4 siv/compiler.py — Stage 3: Deterministic Compilation

```python
"""
Stage 3: Deterministic FOL Test Compilation

Takes a ProblemExtraction (entities + facts + templates) and generates
positive and negative FOL unit tests.

Test generation rules by arity:
  1-arg fact → exists x.Pred(x) + conjunction with entity type
  2-arg fact → exists x.exists y.Pred(x,y) or Pred(constant1, constant2)
  3-arg fact → exists x.Pred(x, const1, const2)

Negative tests by perturbation:
  For each 1-arg property, substitute with antonym from perturbation map
  For each 2-arg relation, substitute the constant argument

All FOL strings are in NLTK-compatible format:
  exists x.(P(x) & Q(x))
  all x.(P(x) -> Q(x))
"""
```

**Key functions:**

```python
def compile_test_suite(extraction: ProblemExtraction) -> TestSuite:
    """Generate the full test suite from a problem extraction."""

def _compile_vocabulary_tests(extraction: ProblemExtraction) -> List[UnitTest]:
    """
    For each predicate in the extraction, generate a test that
    the predicate exists with the correct arity.
    """

def _compile_binding_tests(extraction: ProblemExtraction) -> List[UnitTest]:
    """
    For each fact, generate a test that the predicate applies
    to the correct entity/constant.
    
    1-arg fact on entity e1 (type="tree", property="tall"):
      → exists x.(Tree(x) & Tall(x))
    
    2-arg fact (pred="directed by", args=["c2", "c1"]):
      → DirectedBy(afterTiller, lanaWilson)  (grounded)
      → exists x.exists y.DirectedBy(x, y)  (existential)
    """

def _compile_macro_tests(extraction: ProblemExtraction) -> List[UnitTest]:
    """
    For each sentence with a macro_template, generate a structural test.
    
    TYPE_A (∀x(P→Q)):
      → all x.(P(x) -> Q(x))  — the backbone implication must hold
    
    TYPE_E (∀x(P→¬Q)):
      → all x.(P(x) -> -Q(x))
    
    GROUND_POSITIVE:
      → P(constant)
    
    CONDITIONAL (A → B):
      → The conditional itself as an entailment test
    """

def _compile_negative_tests(extraction: ProblemExtraction) -> List[UnitTest]:
    """
    Contrastive tests using perturbation map.
    For each property fact, swap with antonym.
    """

def _to_camel_case(surface: str) -> str:
    """Convert 'directed by' → 'DirectedBy', 'Harvard student' → 'HarvardStudent'"""

def _to_fol_string(pred: str, args: List[str], negated: bool = False) -> str:
    """Build NLTK-compatible FOL string from predicate + args."""
```

### 3.5 siv/verifier.py — Tiered Verification

```python
"""
Tiered verification pipeline with partial credit.

Tier 0: Syntax check — does the candidate parse as valid FOL?
Tier 1: Vocabulary check with CamelCase-aware partial credit
Tier 2: Lightweight AST pattern matching
Tier 3: Vampire theorem prover (only for complex entailments)

The partial credit system:
  Full match (predicate exists as standalone): 1.0
  Partial match (predicate found as CamelCase component): 0.5
  No match: 0.0
"""
```

**Key functions:**

```python
def verify(candidate_fol: str, test_suite: TestSuite) -> VerificationResult:
    """Run full tiered verification of one candidate against a test suite."""

def _tier0_syntax(candidate: str) -> bool:
    """Parse with NLTK. Return True if syntactically valid."""

def _tier1_vocabulary(candidate: str, test: UnitTest) -> tuple[bool, float]:
    """
    CamelCase-aware vocabulary check.
    Returns (definitive_result, partial_credit).
    
    If the test predicate exists as a standalone predicate in candidate:
      return (True, 1.0)
    If the test predicate appears as a CamelCase COMPONENT of a candidate predicate:
      return (False, 0.5)  — pass to Tier 2 but record partial credit
    If not found at all:
      return (True, 0.0)  — definitive fail, skip Tier 2/3
    """

def _tier2_ast(candidate_expr, test_expr) -> Optional[bool]:
    """
    Lightweight AST check using NLTK parsed expressions.
    Check simple patterns like: does a conjunction contain P(x)?
    Returns True/False if resolved, None if needs Tier 3.
    """

def _tier3_prover(candidate: str, test: str, timeout: int = 5) -> bool:
    """
    Call Vampire theorem prover.
    Convert both to TPTP, check if candidate entails test.
    """

def _extract_predicates_from_fol(fol_string: str) -> List[str]:
    """Extract all predicate names from a FOL string."""

def _camelcase_components(pred_name: str) -> List[str]:
    """Split CamelCase: 'CrimsonCar' → ['Crimson', 'Car']"""
```

### 3.6 siv/scorer.py — SIV Score Computation

```python
"""
SIV Score computation.

SIV Score = F1(recall_rate, precision_rate)
         = 2 * recall * precision / (recall + precision)

Where:
  recall_rate = (full_passes + sum(partial_credits)) / total_positive_tests
  precision_rate = negative_tests_rejected / total_negative_tests
"""
```

### 3.7 siv/fol_utils.py — FOL Utilities

Port the following from the existing notebook:
- `normalize_fol_string()` — convert Unicode symbols to NLTK ASCII
- `is_valid_fol()` — parse with NLTK, return bool
- `extract_predicates()` — extract all predicate names from a FOL expression
- `_convert_to_tptp()` — convert NLTK Expression to TPTP format for Vampire

### 3.8 siv/vampire_interface.py — Vampire Prover

Port from existing notebook:
- `check_entailment(premise_fol, conclusion_fol, timeout)` — returns True/False/None
- Vampire download and setup
- TPTP file generation and parsing

---

## 4. NOTEBOOK STRUCTURE (notebooks/main.ipynb)

The main notebook should follow this flow:

```python
# Cell 1: Setup & Installation
# (pip installs, spacy model download, nltk data, API key setup)

# Cell 2: Import SIV modules
from siv.schema import *
from siv.pre_analyzer import analyze_sentence
from siv.extractor import extract_problem
from siv.compiler import compile_test_suite
from siv.verifier import verify
from siv.scorer import compute_siv_score

# Cell 3: Load FOLIO dataset
# Load from data/folio_problems.json or download from HuggingFace

# Cell 4: Stage 1 Demo — show pre-analysis on example sentences

# Cell 5: Stage 2 Demo — show extraction with enriched prompt

# Cell 6: Stage 3 Demo — show compiled unit tests

# Cell 7: Load pretrained T5 model (from MALLS warmup or HuggingFace)

# Cell 8: Generate FOL candidates with T5 (beam search, K=5)

# Cell 9: Run SIV evaluation (full tiered verification)

# Cell 10: Results & Leaderboard (pandas DataFrame)

# Cell 11: Also evaluate GPT-4o few-shot baseline

# Cell 12: Comparison table: EPR vs SIV score

# Cell 13: FOLIO schema inconsistency analysis

# Cell 14: Export results to CSV
```

---

## 5. KEY DESIGN DECISIONS FOR CLAUDE CODE

1. **Every module must be independently testable.** Each function should work in isolation with mock inputs. No global state.

2. **The API key handling must support both Colab secrets and environment variables:**
```python
try:
    from google.colab import userdata
    OPENAI_API_KEY = userdata.get('OPENAI_API_KEY')
except (ImportError, AttributeError, KeyError):
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
```

3. **The fallback extraction** (when no API key is available) must be good enough to run the full pipeline end-to-end. It won't be as accurate as GPT-4o but must produce valid schema-conforming JSON.

4. **Vampire is optional.** If Vampire can't be installed (e.g., Colab environment issues), the verifier should gracefully skip Tier 3 and report "unresolved" for tests that need it. Most tests should be resolvable at Tier 1-2.

5. **All FOL strings use NLTK format:**
   - `exists x.P(x)` not `∃x.P(x)`
   - `all x.(P(x) -> Q(x))` not `∀x(P(x) → Q(x))`
   - `&` for conjunction, `|` for disjunction, `->` for implication
   - `-` for negation

6. **CamelCase convention:** `_to_camel_case("directed by") → "DirectedBy"`. Multi-word surfaces are CamelCased. Single words are title-cased.

7. **Entity IDs:** Use `e1, e2, ...` for quantified entities and `c1, c2, ...` for named constants. Or if the entity is a well-known constant, use its camelCase name directly (e.g., `nancy`, `garfield`).

---

## 6. EXISTING CODE TO REFERENCE

The file `SIV_Evaluation_Framework__3_.ipynb` contains working implementations of:
- NLTK FOL parser and normalizer (Cell 9-10)
- Vampire TPTP converter and interface (Cell 11-12)
- MALLS dataset loading and cleaning (Cell 14)
- T5 supervised warmup training (Cell 16)
- The original (flawed) SIV sieve and compiler (Cells 20-25)
- The tiered verifier (Cell 27)
- Candidate generation with beam search (Cell 31)
- Results DataFrame construction (Cell 33)

Claude Code should:
- **Port** the FOL utilities (fol_utils.py, vampire_interface.py) directly from the notebook
- **Replace** the extraction logic (the old JSON schema) with the new NSSE pipeline
- **Replace** the old compiler with the new arity-based + macro-template compiler
- **Add** the partial credit system to the verifier (this is NEW, not in the old notebook)
- **Add** the pre-analyzer module (this is entirely NEW)
- **Keep** the T5 training infrastructure from the notebook for Phase 2

---

## 7. TESTING EXPECTATIONS

Each module should have pytest tests. Example test cases:

**test_pre_analyzer.py:**
```python
def test_tall_tree_splits():
    results = analyze_sentence("The tall tree grows quickly.")
    tall = [r for r in results if r.modifier == "tall"][0]
    assert tall.recommendation == "SPLIT"

def test_harvard_student_keeps():
    results = analyze_sentence("A Harvard student passed the exam.")
    harvard = [r for r in results if r.modifier == "Harvard"][0]
    assert harvard.recommendation == "KEEP"
```

**test_compiler.py:**
```python
def test_unary_fact_generates_existence_test():
    extraction = ProblemExtraction(
        problem_id="test",
        sentences=[SentenceExtraction(
            nl="The tall tree.",
            entities=[Entity(id="e1", surface="tree", entity_type=EntityType.EXISTENTIAL)],
            facts=[Fact(pred="tall", args=["e1"])],
            macro_template=MacroTemplate.GROUND_POSITIVE,
        )]
    )
    suite = compile_test_suite(extraction)
    fol_strings = [t.fol_string for t in suite.positive_tests]
    assert "exists x.Tall(x)" in fol_strings
    assert "exists x.(Tree(x) & Tall(x))" in fol_strings
```

**test_verifier.py:**
```python
def test_partial_credit_for_slug():
    # CrimsonCar(x) should get partial credit for test expecting Crimson(x)
    result = _tier1_vocabulary(
        "all x.(CrimsonCar(x) -> MovesQuickly(x))",
        UnitTest(fol_string="exists x.Crimson(x)", test_type="vocabulary", is_positive=True)
    )
    assert result[1] == 0.5  # partial credit

def test_full_credit_for_decomposed():
    result = _tier1_vocabulary(
        "exists x.(Car(x) & Crimson(x) & Running(x))",
        UnitTest(fol_string="exists x.Crimson(x)", test_type="vocabulary", is_positive=True)
    )
    assert result[1] == 1.0  # full credit
```
