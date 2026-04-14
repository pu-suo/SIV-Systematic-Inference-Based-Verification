"""
SIV Schema: Formula-based extraction schema (Phase 1).

Defined per SIV.md §6.2 and §7 (C0–C3). The Formula sum type is the
complete grammar; it has exactly four cases (atomic, quantification,
negation, connective+operands). No fifth case.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, model_validator


class SchemaViolation(Exception):
    """Raised by validate_extraction on any structural schema violation."""


# ── Core leaf models ─────────────────────────────────────────────────────────

class PredicateDecl(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    arity: Literal[1, 2]
    arg_types: List[str]

    @model_validator(mode="after")
    def _arg_types_matches_arity(self) -> "PredicateDecl":
        if len(self.arg_types) != self.arity:
            raise SchemaViolation(
                f"PredicateDecl {self.name!r}: arg_types length "
                f"{len(self.arg_types)} != arity {self.arity}"
            )
        return self


class Entity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    surface: str
    type: str


class Constant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    surface: str
    type: str


class AtomicFormula(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pred: str
    args: List[str]
    negated: bool = False


class InnerQuantification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantifier: Literal["universal", "existential"]
    variable: str
    var_type: str


class TripartiteQuantification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantifier: Literal["universal", "existential"]
    variable: str
    var_type: str
    restrictor: List[AtomicFormula]
    nucleus: "Formula"
    inner_quantifications: List[InnerQuantification] = []


class Formula(BaseModel):
    model_config = ConfigDict(extra="forbid")

    atomic: Optional[AtomicFormula] = None
    quantification: Optional[TripartiteQuantification] = None
    negation: Optional["Formula"] = None
    connective: Optional[Literal["and", "or", "implies", "iff"]] = None
    operands: Optional[List["Formula"]] = None


class SentenceExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nl: str
    predicates: List[PredicateDecl] = []
    entities: List[Entity] = []
    constants: List[Constant] = []
    formula: Formula


# ── Test suite models (C0) ───────────────────────────────────────────────────

class UnitTest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fol: str
    kind: Literal["positive", "contrastive"]
    mutation_kind: Optional[str] = None

    @model_validator(mode="after")
    def _mutation_kind_iff_contrastive(self) -> "UnitTest":
        if self.kind == "contrastive" and self.mutation_kind is None:
            raise SchemaViolation(
                "UnitTest.kind == 'contrastive' requires mutation_kind"
            )
        if self.kind == "positive" and self.mutation_kind is not None:
            raise SchemaViolation(
                "UnitTest.kind == 'positive' forbids mutation_kind"
            )
        return self


class TestSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    extraction: SentenceExtraction
    positives: List[UnitTest] = []
    contrastives: List[UnitTest] = []


TripartiteQuantification.model_rebuild()
Formula.model_rebuild()
SentenceExtraction.model_rebuild()
TestSuite.model_rebuild()


# ── Validation (C3) ──────────────────────────────────────────────────────────

_BINARY_CONNECTIVES = {"implies", "iff"}
_NARY_CONNECTIVES = {"and", "or"}


def _formula_active_cases(f: Formula) -> int:
    count = 0
    if f.atomic is not None:
        count += 1
    if f.quantification is not None:
        count += 1
    if f.negation is not None:
        count += 1
    if f.connective is not None or f.operands is not None:
        count += 1
    return count


def _validate_formula(
    f: Formula,
    predicates: dict,
    global_scope: set,
    bound_scope: set,
) -> None:
    # Exclusivity: exactly one case populated.
    cases = _formula_active_cases(f)
    if cases == 0:
        raise SchemaViolation("Formula has zero cases populated")
    if cases > 1:
        raise SchemaViolation("Formula has more than one case populated")

    if f.atomic is not None:
        _validate_atom(f.atomic, predicates, global_scope, bound_scope)
        return

    if f.negation is not None:
        _validate_formula(f.negation, predicates, global_scope, bound_scope)
        return

    if f.quantification is not None:
        _validate_quantification(f.quantification, predicates, global_scope, bound_scope)
        return

    # Connective case.
    if f.connective is None:
        raise SchemaViolation("Formula operands populated without connective")
    if f.operands is None:
        raise SchemaViolation("Formula connective populated without operands")
    ops = f.operands
    if f.connective in _BINARY_CONNECTIVES:
        if len(ops) != 2:
            raise SchemaViolation(
                f"Connective {f.connective!r} requires exactly 2 operands, "
                f"got {len(ops)}"
            )
    elif f.connective in _NARY_CONNECTIVES:
        if len(ops) < 2:
            raise SchemaViolation(
                f"Connective {f.connective!r} requires at least 2 operands, "
                f"got {len(ops)}"
            )
    for op in ops:
        _validate_formula(op, predicates, global_scope, bound_scope)


def _validate_atom(
    atom: AtomicFormula,
    predicates: dict,
    global_scope: set,
    bound_scope: set,
) -> None:
    if atom.pred not in predicates:
        raise SchemaViolation(
            f"AtomicFormula references undeclared predicate {atom.pred!r}"
        )
    decl: PredicateDecl = predicates[atom.pred]
    if len(atom.args) != decl.arity:
        raise SchemaViolation(
            f"AtomicFormula {atom.pred!r}: args length {len(atom.args)} "
            f"!= declared arity {decl.arity}"
        )
    in_scope = global_scope | bound_scope
    for a in atom.args:
        if a not in in_scope:
            raise SchemaViolation(
                f"AtomicFormula {atom.pred!r}: argument {a!r} is not a "
                f"declared entity/constant or bound variable"
            )


def _validate_quantification(
    q: TripartiteQuantification,
    predicates: dict,
    global_scope: set,
    bound_scope: set,
) -> None:
    inner_vars = {iq.variable for iq in q.inner_quantifications}
    restrictor_scope = bound_scope | {q.variable} | inner_vars
    for atom in q.restrictor:
        _validate_atom(atom, predicates, global_scope, restrictor_scope)

    # Empty-restrictor + single-atom-over-bound-variable nucleus is forbidden:
    # this is the degenerate pattern the §6.2 TripartiteQuantification is
    # designed to preclude.
    if len(q.restrictor) == 0:
        nuc = q.nucleus
        if (
            nuc.atomic is not None
            and len(nuc.atomic.args) == 1
            and nuc.atomic.args[0] == q.variable
        ):
            raise SchemaViolation(
                "TripartiteQuantification with empty restrictor and nucleus "
                "of a single atom over the bound variable is forbidden"
            )

    nucleus_scope = bound_scope | {q.variable}
    _validate_formula(q.nucleus, predicates, global_scope, nucleus_scope)


def validate_extraction(extraction: SentenceExtraction) -> None:
    """Validate a SentenceExtraction per SIV.md §7 C2 and C3.

    Raises SchemaViolation on any violation. Returns None on success.
    Deterministic; no LLM/network calls.
    """
    predicates: dict = {}
    for p in extraction.predicates:
        if p.name in predicates:
            raise SchemaViolation(f"Duplicate PredicateDecl name {p.name!r}")
        predicates[p.name] = p

    global_scope: set = set()
    for e in extraction.entities:
        if e.id in global_scope:
            raise SchemaViolation(f"Duplicate entity/constant id {e.id!r}")
        global_scope.add(e.id)
    for c in extraction.constants:
        if c.id in global_scope:
            raise SchemaViolation(f"Duplicate entity/constant id {c.id!r}")
        global_scope.add(c.id)

    _validate_formula(extraction.formula, predicates, global_scope, set())
