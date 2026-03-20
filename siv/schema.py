"""
SIV Schema: Core data structures for the pipeline.

The JSON extraction schema has three sections:
  - constants: named individuals (proper nouns, specific entities)
  - entities:  quantified things that exist in the world
  - facts:     what is true about them (pred + args)

Each fact's arity (len(args)) implicitly encodes its type:
  1-arg → unary predicate (type or property)
  2-arg → binary relation or reified attribute
  3-arg → ternary relation

The macro_template field on sentences captures the logical skeleton
using the Aristotelian categorical forms (A, E, I, O) plus ground
facts and conditionals.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from enum import Enum


class EntityType(Enum):
    CONSTANT = "constant"        # Named individual (backward compat): nancy, garfield
    EXISTENTIAL = "existential"  # "a car", "some bears"
    UNIVERSAL = "universal"      # "all kids", "every student"


class MacroTemplate(Enum):
    """
    The 7 canonical sentence forms, grounded in the Aristotelian
    Square of Opposition (A, E, I, O) + ground facts + conditional.

    Reference: Russell & Norvig AIMA Ch. 8; Aristotle's Prior Analytics.
    """
    # Categorical propositions (quantified)
    TYPE_A = "universal_affirmative"    # All P are Q:      ∀x(P(x) → Q(x))
    TYPE_E = "universal_negative"       # No P are Q:       ∀x(P(x) → ¬Q(x))
    TYPE_I = "existential_affirmative"  # Some P are Q:     ∃x(P(x) ∧ Q(x))
    TYPE_O = "existential_negative"     # Some P are not Q: ∃x(P(x) ∧ ¬Q(x))
    # Ground facts (about constants)
    GROUND_POSITIVE = "ground_positive"  # P(c) or P(c) ∧ Q(c)
    GROUND_NEGATIVE = "ground_negative"  # ¬P(c)
    # Compositional
    CONDITIONAL = "conditional"          # A → B (where A, B are from above)
    BICONDITIONAL = "biconditional"      # A ↔ B or ¬(A ⊕ B)


@dataclass
class Constant:
    """A named individual (proper noun) in the sentence."""
    id: str      # camelCase logical name: "bonnie", "schoolTalentShow", "c1"
    surface: str # original surface form: "Bonnie", "school talent show"


@dataclass
class Entity:
    id: str                    # e1, e2, c1, c2, ...
    surface: str               # "nancy", "car", "Harvard student"
    entity_type: EntityType    # constant (compat), existential, universal


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
    entities: List[Entity]     # quantified entities (existential / universal)
    facts: List[Fact]
    macro_template: MacroTemplate
    compound_analyses: List[CompoundAnalysis] = field(default_factory=list)
    constants: List[Constant] = field(default_factory=list)  # named individuals


@dataclass
class ProblemExtraction:
    """Complete extraction for one FOLIO problem (multiple sentences)."""
    problem_id: str
    sentences: List[SentenceExtraction]

    @property
    def all_constants(self) -> List[Constant]:
        """Deduplicated constants across all sentences."""
        seen: set = set()
        result: List[Constant] = []
        for s in self.sentences:
            for c in s.constants:
                if c.id not in seen:
                    seen.add(c.id)
                    result.append(c)
        return result

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
        total_credit = sum(self.partial_credits.values())
        return (self.recall_passed + total_credit) / self.recall_total

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
