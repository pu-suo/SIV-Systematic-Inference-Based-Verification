"""Tests for siv/fol_parser.py — deterministic gold FOL parser."""
import pytest

from siv.fol_parser import parse_gold_fol, ParseError
from siv.compiler import compile_canonical_fol
from siv.schema import validate_extraction, SchemaViolation


# ════════════════════════════════════════════════════════════════════════════
# Category 1: Universal + implication, flat atom antecedent
# ════════════════════════════════════════════════════════════════════════════


class TestCategory1UniversalImplication:
    def test_simple_universal(self):
        ext = parse_gold_fol("all x.(P(x) -> Q(x))", nl="test")
        assert ext.formula.quantification is not None
        q = ext.formula.quantification
        assert q.quantifier == "universal"
        assert q.variable == "x"
        assert len(q.restrictor) == 1
        assert q.restrictor[0].pred == "P"
        assert q.nucleus.atomic is not None
        assert q.nucleus.atomic.pred == "Q"

    def test_compound_restrictor(self):
        ext = parse_gold_fol("all x.((P(x) & R(x, coffee)) -> Q(x))", nl="test")
        q = ext.formula.quantification
        assert len(q.restrictor) == 2
        preds = {a.pred for a in q.restrictor}
        assert preds == {"P", "R"}

    def test_negated_restrictor_atom(self):
        ext = parse_gold_fol("all x.((-P(x)) -> Q(x))", nl="test")
        q = ext.formula.quantification
        assert len(q.restrictor) == 1
        assert q.restrictor[0].negated is True

    def test_validates(self):
        ext = parse_gold_fol("all x.((Dog(x) & Animal(x)) -> Mortal(x))", nl="test")
        validate_extraction(ext)


# ════════════════════════════════════════════════════════════════════════════
# Category 2: Ground instances
# ════════════════════════════════════════════════════════════════════════════


class TestCategory2Ground:
    def test_single_atom(self):
        ext = parse_gold_fol("P(john)", nl="test")
        assert ext.formula.atomic is not None
        assert ext.formula.atomic.pred == "P"
        assert ext.formula.atomic.args == ["john"]

    def test_conjunction(self):
        ext = parse_gold_fol("(P(john) & Q(mary))", nl="test")
        assert ext.formula.connective == "and"
        assert len(ext.formula.operands) == 2

    def test_ground_negation(self):
        ext = parse_gold_fol("-P(john)", nl="test")
        assert ext.formula.negation is not None
        assert ext.formula.negation.atomic.pred == "P"

    def test_ground_implication(self):
        ext = parse_gold_fol("(P(john) -> Q(john))", nl="test")
        assert ext.formula.connective == "implies"

    def test_constants_extracted(self):
        ext = parse_gold_fol("(P(john) & R(john, mary))", nl="test")
        const_ids = {c.id for c in ext.constants}
        assert "john" in const_ids
        assert "mary" in const_ids

    def test_validates(self):
        ext = parse_gold_fol("(Tall(john) & Smart(mary))", nl="test")
        validate_extraction(ext)


# ════════════════════════════════════════════════════════════════════════════
# Category 3: Existentials
# ════════════════════════════════════════════════════════════════════════════


class TestCategory3Existential:
    def test_simple_existential_conjunction(self):
        ext = parse_gold_fol("exists x.(P(x) & Q(x))", nl="test")
        q = ext.formula.quantification
        assert q.quantifier == "existential"
        # Both atoms mention x, both should be in restrictor or one in nucleus
        assert len(q.restrictor) >= 1

    def test_existential_with_constant(self):
        ext = parse_gold_fol("exists x.(Dog(x) & Owns(john, x))", nl="test")
        q = ext.formula.quantification
        assert q.quantifier == "existential"
        validate_extraction(ext)

    def test_degenerate_existential_unary(self):
        """exists x.P(x) with unary P → duplicate atom strategy."""
        ext = parse_gold_fol("exists x.(EcoFriendly(x))", nl="test")
        q = ext.formula.quantification
        assert q.quantifier == "existential"
        assert len(q.restrictor) == 1
        assert q.restrictor[0].pred == "EcoFriendly"
        assert q.nucleus.atomic is not None
        assert q.nucleus.atomic.pred == "EcoFriendly"
        validate_extraction(ext)

    def test_existential_binary_no_degenerate(self):
        """exists x.R(x, a) with binary R → not degenerate."""
        ext = parse_gold_fol("exists x.(Likes(x, coffee))", nl="test")
        q = ext.formula.quantification
        assert q.quantifier == "existential"
        validate_extraction(ext)

    def test_validates(self):
        ext = parse_gold_fol("exists x.(Cat(x) & Fluffy(x))", nl="test")
        validate_extraction(ext)


# ════════════════════════════════════════════════════════════════════════════
# Category 4: Nested universals
# ════════════════════════════════════════════════════════════════════════════


class TestCategory4NestedUniversal:
    def test_nested_universal_implication(self):
        ext = parse_gold_fol("all x.(all y.((P(x) & Q(y)) -> R(x, y)))", nl="test")
        q = ext.formula.quantification
        assert q.quantifier == "universal"
        validate_extraction(ext)

    def test_all_x_all_y_implication(self):
        fol = "all x.(all y.((Team(x) & Team(y) & MorePoints(x, y)) -> RanksHigher(x, y)))"
        ext = parse_gold_fol(fol, nl="test")
        validate_extraction(ext)


# ════════════════════════════════════════════════════════════════════════════
# Category 5: Nested quantifier in antecedent (inner_quantification)
# ════════════════════════════════════════════════════════════════════════════


class TestCategory5InnerQuantification:
    def test_exists_in_antecedent(self):
        fol = "all x.(exists y.(Contains(x, y) & Feature(y)) -> Software(x))"
        ext = parse_gold_fol(fol, nl="test")
        q = ext.formula.quantification
        assert q.quantifier == "universal"
        assert len(q.inner_quantifications) == 1
        assert q.inner_quantifications[0].quantifier == "existential"
        assert q.inner_quantifications[0].variable == "y"
        # Restrictor should contain atoms from the existential body
        assert len(q.restrictor) >= 2
        validate_extraction(ext)


# ════════════════════════════════════════════════════════════════════════════
# Category 7: Universal without implication
# ════════════════════════════════════════════════════════════════════════════


class TestCategory7UniversalNoImplication:
    def test_universal_disjunction_body(self):
        ext = parse_gold_fol("all x.(P(x) | Q(x))", nl="test")
        q = ext.formula.quantification
        assert q.quantifier == "universal"
        assert q.restrictor == []
        assert q.nucleus.connective == "or"
        validate_extraction(ext)

    def test_universal_conjunction_body(self):
        ext = parse_gold_fol("all x.(P(x) & Q(x))", nl="test")
        q = ext.formula.quantification
        assert q.quantifier == "universal"
        assert q.restrictor == []
        assert q.nucleus.connective == "and"
        validate_extraction(ext)


# ════════════════════════════════════════════════════════════════════════════
# Category 8: Equality
# ════════════════════════════════════════════════════════════════════════════


class TestCategory8Equality:
    def test_simple_equality(self):
        ext = parse_gold_fol("(john = mary)", nl="test")
        assert ext.formula.atomic is not None
        assert ext.formula.atomic.pred == "__eq__"
        assert ext.formula.atomic.args == ["john", "mary"]

    def test_negated_equality(self):
        ext = parse_gold_fol("-(john = mary)", nl="test")
        assert ext.formula.negation is not None
        assert ext.formula.negation.atomic.pred == "__eq__"
        assert ext.formula.negation.atomic.args == ["john", "mary"]

    def test_equality_in_quantified_formula(self):
        fol = "exists x.(exists y.(-(x = y) & P(x) & P(y)))"
        ext = parse_gold_fol(fol, nl="test")
        validate_extraction(ext)

    def test_equality_compiles_infix(self):
        ext = parse_gold_fol("(john = mary)", nl="test")
        compiled = compile_canonical_fol(ext)
        assert "=" in compiled
        assert "__eq__" not in compiled

    def test_predicates_include_equals(self):
        ext = parse_gold_fol("(john = mary)", nl="test")
        pred_names = {p.name for p in ext.predicates}
        assert "__eq__" in pred_names


# ════════════════════════════════════════════════════════════════════════════
# Category 9: Free variables → REJECT
# ════════════════════════════════════════════════════════════════════════════


class TestCategory9FreeVariables:
    def test_rejects_free_indvar(self):
        with pytest.raises(ParseError, match="free individual variables"):
            parse_gold_fol("all x.(P(x) & Q(y))", nl="test")

    def test_rejects_free_x(self):
        with pytest.raises(ParseError, match="free individual variables"):
            parse_gold_fol("P(x)", nl="test")

    def test_constants_not_rejected(self):
        """Multi-char lowercase names are constants, not indvars."""
        ext = parse_gold_fol("P(john)", nl="test")
        assert ext.formula.atomic.args == ["john"]


# ════════════════════════════════════════════════════════════════════════════
# Round-trip tests
# ════════════════════════════════════════════════════════════════════════════


class TestRoundTrip:
    def test_compile_universal(self):
        ext = parse_gold_fol("all x.(P(x) -> Q(x))", nl="test")
        compiled = compile_canonical_fol(ext)
        assert "all" in compiled
        assert "P" in compiled
        assert "Q" in compiled

    def test_compile_ground(self):
        ext = parse_gold_fol("(P(john) & Q(mary))", nl="test")
        compiled = compile_canonical_fol(ext)
        assert "john" in compiled
        assert "mary" in compiled

    def test_compile_existential(self):
        ext = parse_gold_fol("exists x.(Dog(x) & Barks(x))", nl="test")
        compiled = compile_canonical_fol(ext)
        assert "exists" in compiled

    @pytest.mark.parametrize("fol", [
        "all x.(P(x) -> Q(x))",
        "all x.((A(x) & B(x)) -> C(x))",
        "(P(john) & Q(mary))",
        "exists x.(Dog(x) & Cat(x))",
        "all x.(P(x) | Q(x))",
    ])
    def test_validates_and_compiles(self, fol):
        ext = parse_gold_fol(fol, nl="test")
        validate_extraction(ext)
        compiled = compile_canonical_fol(ext)
        assert compiled  # non-empty string


# ════════════════════════════════════════════════════════════════════════════
# Arity > 2
# ════════════════════════════════════════════════════════════════════════════


class TestArityExtension:
    def test_ternary_predicate(self):
        ext = parse_gold_fol("all x.(P(x) -> R(x, coffee, tea))", nl="test")
        pred_dict = {p.name: p.arity for p in ext.predicates}
        assert pred_dict["R"] == 3
        validate_extraction(ext)

    def test_ternary_compiles(self):
        ext = parse_gold_fol("R(john, mary, bob)", nl="test")
        compiled = compile_canonical_fol(ext)
        assert "R(john, mary, bob)" == compiled


# ════════════════════════════════════════════════════════════════════════════
# ParseError cases
# ════════════════════════════════════════════════════════════════════════════


class TestParseErrors:
    def test_empty_string(self):
        with pytest.raises(ParseError):
            parse_gold_fol("", nl="test")

    def test_malformed_syntax(self):
        with pytest.raises(ParseError):
            parse_gold_fol("P(x) & Q(x", nl="test")  # unbalanced parens

    def test_nonsense_string(self):
        with pytest.raises(ParseError):
            parse_gold_fol("not valid fol at all !!!", nl="test")
