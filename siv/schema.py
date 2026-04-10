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
from typing import List, Optional
from enum import Enum


# FIX C1: raised by the scorer when a caller computes a SIV score for an
# extraction that contains schema violations.
class ExtractionInvalidError(RuntimeError):
    """
    Raised by the scorer when a caller attempts to compute a SIV score
    for an extraction that contains schema violations. Violating
    extractions are scored as SIV=0 with the extraction_invalid flag
    set; callers that want to see the score must read the
    VerificationResult directly.
    """


# FIX B1: raised when unresolved_policy="raise" and any test is unresolved.
class ProverUnavailableError(RuntimeError):
    """
    Raised when unresolved_policy="raise" (the default) and one or more tests
    could not be resolved because the Vampire theorem prover was unavailable or
    timed out. SIV's published scores require a working prover; silently
    degrading to vocabulary-level credit is a Tenet-1 violation.
    """


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
class SchemaViolation:
    """
    A single Neo-Davidsonian violation detected in an extraction.
    See Tenet 2 in the refactor context: all facts must decompose into
    unary properties or binary relations; prepositional phrases must
    be reified into separate entities and binary edges.

    # FIX C1: prepositional_unary and high_arity violations detected by
    # validate_neo_davidsonian in siv/compiler.py.
    """
    sentence_nl: str
    fact_pred: str
    fact_args: List[str]
    violation_type: str       # e.g. "prepositional_unary", "high_arity"
    message: str              # human-readable explanation


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
    # FIX C1: schema violations from validate_neo_davidsonian; non-empty means
    # the extraction violated the Neo-Davidsonian imperative (Tenet 2).
    violations: List["SchemaViolation"] = field(default_factory=list)

    @property
    def total_tests(self) -> int:
        return len(self.positive_tests) + len(self.negative_tests)

    @property
    def has_violations(self) -> bool:
        # FIX C1: True when the extraction failed the Neo-Davidsonian validator.
        return len(self.violations) > 0


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
    # FIX B1: counts of tests that could not be resolved by the prover.
    # In "exclude" mode these are excluded from the denominator so they neither
    # help nor hurt the candidate. In "raise" mode the verifier raises before
    # these fields are ever populated.
    unresolved_recall: int = 0
    unresolved_precision: int = 0
    # FIX C1: set to True when the test suite carried Neo-Davidsonian violations;
    # the verifier short-circuits and siv_score returns 0.0.
    extraction_invalid: bool = False
    schema_violations: List["SchemaViolation"] = field(default_factory=list)
    # Task 03: set to True when the candidate is provably internally inconsistent
    # (contains P(a) & -P(a) or equivalent); siv_score short-circuits to 0.0.
    candidate_inconsistent: bool = False

    @property
    def recall_rate(self) -> float:
        # FIX B1: unresolved tests are excluded from the effective denominator.
        effective_denom = self.recall_total - self.unresolved_recall
        if effective_denom <= 0:
            return 0.0
        return self.recall_passed / effective_denom

    @property
    def precision_rate(self) -> float:
        # FIX B1: unresolved tests are excluded from the denominator in
        # non-strict mode; in strict mode the verifier raises before we ever
        # compute rates.
        effective_denom = self.precision_total - self.unresolved_precision
        if effective_denom <= 0:
            return 1.0
        return self.precision_passed / effective_denom

    @property
    def siv_score(self) -> float:
        # FIX C1: schema violations short-circuit the score to 0.0. Under Tenet 4
        # we do not silently degrade — invalid extractions score zero.
        if self.extraction_invalid or self.candidate_inconsistent:
            return 0.0
        effective_recall_total = self.recall_total - self.unresolved_recall
        effective_precision_total = self.precision_total - self.unresolved_precision
        if effective_recall_total <= 0 and effective_precision_total <= 0:
            return 0.0
        if effective_recall_total <= 0:
            return self.precision_rate
        if effective_precision_total <= 0:
            return self.recall_rate
        r, p = self.recall_rate, self.precision_rate
        if r + p == 0:
            return 0.0
        return 2.0 * r * p / (r + p)
