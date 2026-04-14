"""Tests for siv/schema.py and siv/json_schema.py — Phase 1 rewrite."""
import json

import pytest
from pydantic import ValidationError

from siv.json_schema import derive_extraction_schema
from siv.schema import (
    AtomicFormula,
    Constant,
    Entity,
    Formula,
    InnerQuantification,
    PredicateDecl,
    SchemaViolation,
    SentenceExtraction,
    TestSuite as _TestSuite,
    TripartiteQuantification,
    UnitTest,
    validate_extraction,
)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _preds(*triples):
    return [PredicateDecl(name=n, arity=ar, arg_types=ts) for (n, ar, ts) in triples]


def _ext(formula, preds=None, constants=None, entities=None, nl="x"):
    return SentenceExtraction(
        nl=nl,
        predicates=preds or [],
        constants=constants or [],
        entities=entities or [],
        formula=formula,
    )


def _atom(pred, *args, negated=False):
    return AtomicFormula(pred=pred, args=list(args), negated=negated)


def _atomic_f(*args, **kwargs):
    return Formula(atomic=_atom(*args, **kwargs))


# ── UnitTest invariants (C0) ────────────────────────────────────────────────

def test_unit_test_contrastive_requires_mutation_kind_positive():
    t = UnitTest(fol="P(a)", kind="contrastive", mutation_kind="negate_atom")
    assert t.mutation_kind == "negate_atom"


def test_unit_test_contrastive_without_mutation_kind_fails():
    with pytest.raises((SchemaViolation, ValidationError)):
        UnitTest(fol="P(a)", kind="contrastive", mutation_kind=None)


def test_unit_test_positive_with_mutation_kind_fails():
    with pytest.raises((SchemaViolation, ValidationError)):
        UnitTest(fol="P(a)", kind="positive", mutation_kind="negate_atom")


def test_unit_test_positive_without_mutation_kind_passes():
    t = UnitTest(fol="P(a)", kind="positive")
    assert t.mutation_kind is None


# ── PredicateDecl arity invariant ───────────────────────────────────────────

def test_predicate_decl_arg_types_must_match_arity():
    with pytest.raises((SchemaViolation, ValidationError)):
        PredicateDecl(name="P", arity=2, arg_types=["e"])


def test_predicate_decl_valid():
    p = PredicateDecl(name="P", arity=2, arg_types=["e", "e"])
    assert p.arity == 2


# ── Formula exclusivity (C1) ─────────────────────────────────────────────────

def _valid_scope():
    preds = _preds(("P", 1, ["e"]))
    constants = [Constant(id="a", surface="a", type="entity")]
    return preds, constants


def test_validate_rejects_empty_formula():
    preds, constants = _valid_scope()
    with pytest.raises(SchemaViolation):
        validate_extraction(_ext(Formula(), preds=preds, constants=constants))


def test_validate_rejects_multiple_cases():
    preds, constants = _valid_scope()
    f = Formula(atomic=_atom("P", "a"), connective="and", operands=[
        _atomic_f("P", "a"), _atomic_f("P", "a"),
    ])
    with pytest.raises(SchemaViolation):
        validate_extraction(_ext(f, preds=preds, constants=constants))


# ── Connective arity ────────────────────────────────────────────────────────

def test_validate_rejects_connective_without_operands():
    preds, constants = _valid_scope()
    f = Formula(connective="and")
    with pytest.raises(SchemaViolation):
        validate_extraction(_ext(f, preds=preds, constants=constants))


def test_validate_rejects_operands_without_connective():
    preds, constants = _valid_scope()
    f = Formula(operands=[_atomic_f("P", "a"), _atomic_f("P", "a")])
    with pytest.raises(SchemaViolation):
        validate_extraction(_ext(f, preds=preds, constants=constants))


def test_validate_rejects_implies_with_three_operands():
    preds, constants = _valid_scope()
    f = Formula(
        connective="implies",
        operands=[_atomic_f("P", "a"), _atomic_f("P", "a"), _atomic_f("P", "a")],
    )
    with pytest.raises(SchemaViolation):
        validate_extraction(_ext(f, preds=preds, constants=constants))


def test_validate_rejects_iff_with_one_operand():
    preds, constants = _valid_scope()
    f = Formula(connective="iff", operands=[_atomic_f("P", "a")])
    with pytest.raises(SchemaViolation):
        validate_extraction(_ext(f, preds=preds, constants=constants))


def test_validate_rejects_and_with_single_operand():
    preds, constants = _valid_scope()
    f = Formula(connective="and", operands=[_atomic_f("P", "a")])
    with pytest.raises(SchemaViolation):
        validate_extraction(_ext(f, preds=preds, constants=constants))


def test_validate_accepts_nary_and():
    preds, constants = _valid_scope()
    f = Formula(connective="and", operands=[
        _atomic_f("P", "a"), _atomic_f("P", "a"), _atomic_f("P", "a"),
    ])
    validate_extraction(_ext(f, preds=preds, constants=constants))


def test_validate_accepts_binary_implies():
    preds, constants = _valid_scope()
    f = Formula(connective="implies", operands=[
        _atomic_f("P", "a"), _atomic_f("P", "a"),
    ])
    validate_extraction(_ext(f, preds=preds, constants=constants))


# ── Predicate/arg resolution (C2) ────────────────────────────────────────────

def test_validate_rejects_undeclared_predicate():
    f = _atomic_f("Undeclared", "a")
    ext = _ext(
        f,
        preds=_preds(("P", 1, ["e"])),
        constants=[Constant(id="a", surface="a", type="entity")],
    )
    with pytest.raises(SchemaViolation):
        validate_extraction(ext)


def test_validate_rejects_arity_mismatch():
    f = _atomic_f("P", "a", "b")  # P declared unary
    ext = _ext(
        f,
        preds=_preds(("P", 1, ["e"])),
        constants=[
            Constant(id="a", surface="a", type="entity"),
            Constant(id="b", surface="b", type="entity"),
        ],
    )
    with pytest.raises(SchemaViolation):
        validate_extraction(ext)


def test_validate_rejects_undeclared_argument():
    f = _atomic_f("P", "ghost")
    ext = _ext(
        f,
        preds=_preds(("P", 1, ["e"])),
        constants=[Constant(id="a", surface="a", type="entity")],
    )
    with pytest.raises(SchemaViolation):
        validate_extraction(ext)


def test_validate_accepts_bound_variable():
    f = Formula(quantification=TripartiteQuantification(
        quantifier="universal", variable="x", var_type="entity",
        restrictor=[_atom("P", "x")],
        nucleus=_atomic_f("Q", "x"),
    ))
    ext = _ext(f, preds=_preds(("P", 1, ["e"]), ("Q", 1, ["e"])))
    validate_extraction(ext)


# ── Degenerate tripartite quantification ────────────────────────────────────

def test_validate_rejects_empty_restrictor_with_nucleus_single_atom_over_bound_var():
    f = Formula(quantification=TripartiteQuantification(
        quantifier="universal", variable="x", var_type="entity",
        restrictor=[],
        nucleus=_atomic_f("P", "x"),
    ))
    ext = _ext(f, preds=_preds(("P", 1, ["e"])))
    with pytest.raises(SchemaViolation):
        validate_extraction(ext)


def test_validate_accepts_empty_restrictor_with_nonatomic_nucleus():
    # Empty restrictor with a compound nucleus is not degenerate.
    f = Formula(quantification=TripartiteQuantification(
        quantifier="existential", variable="x", var_type="entity",
        restrictor=[],
        nucleus=Formula(connective="and", operands=[
            _atomic_f("P", "x"), _atomic_f("Q", "x"),
        ]),
    ))
    ext = _ext(f, preds=_preds(("P", 1, ["e"]), ("Q", 1, ["e"])))
    validate_extraction(ext)


# ── JSON Schema derivation (C3 / §6.2.7) ────────────────────────────────────

def test_json_schema_deterministic_across_runs():
    s1 = derive_extraction_schema()
    s2 = derive_extraction_schema()
    assert json.dumps(s1, sort_keys=True) == json.dumps(s2, sort_keys=True)


def test_json_schema_inlines_non_recursive_refs():
    # Formula is self-referential (negation, operands, nucleus all recurse
    # back to Formula). A self-referential type cannot be fully inlined, so
    # we preserve Formula as a $def and $ref to it. Non-recursive leaves
    # (AtomicFormula, PredicateDecl, Entity, Constant, ...) must be inlined.
    s = derive_extraction_schema()
    defs = s.get("$defs", {})
    # Only Formula (and structures that necessarily recurse through it, e.g.
    # TripartiteQuantification) may remain as $defs.
    for name in defs.keys():
        assert name in {"Formula", "TripartiteQuantification"}, (
            f"unexpected non-recursive type retained in $defs: {name}"
        )


def test_json_schema_objects_forbid_additional_properties():
    s = derive_extraction_schema()

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                assert node.get("additionalProperties") is False
                props = node.get("properties", {})
                if props:
                    assert set(node.get("required", [])) == set(props.keys())
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for x in node:
                walk(x)

    walk(s)


def test_json_schema_strips_title_and_description():
    s = derive_extraction_schema()
    text = json.dumps(s)
    assert '"title"' not in text
    assert '"description"' not in text
    assert '"default"' not in text


# ── Exercise TestSuite container ────────────────────────────────────────────

def test_test_suite_holds_extraction_and_positives():
    preds, constants = _valid_scope()
    ext = _ext(_atomic_f("P", "a"), preds=preds, constants=constants)
    suite = _TestSuite(
        extraction=ext,
        positives=[UnitTest(fol="P(a)", kind="positive")],
        contrastives=[
            UnitTest(fol="-P(a)", kind="contrastive", mutation_kind="negate_atom"),
        ],
    )
    assert len(suite.positives) == 1
    assert len(suite.contrastives) == 1
