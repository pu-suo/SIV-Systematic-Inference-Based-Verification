"""Tests for siv/compiler.py"""
import pytest
from siv.schema import (
    Entity, EntityType, Fact, MacroTemplate,
    ProblemExtraction, SentenceExtraction,
)
from siv.compiler import (
    compile_test_suite,
    _to_camel_case,
    _compile_vocabulary_tests,
    _compile_binding_tests,
    _compile_negative_tests,
)


# ── _to_camel_case ────────────────────────────────────────────────────────────

def test_camel_single_word():
    assert _to_camel_case("tall") == "Tall"

def test_camel_two_words():
    assert _to_camel_case("directed by") == "DirectedBy"

def test_camel_three_words():
    assert _to_camel_case("Harvard student union") == "HarvardStudentUnion"

def test_camel_already_cased():
    assert _to_camel_case("Running") == "Running"

def test_camel_empty():
    assert _to_camel_case("") == ""


# ── Helper fixture builders ───────────────────────────────────────────────────

def _make_problem(
    problem_id="test",
    entity_id="e1",
    entity_surface="tree",
    entity_type=EntityType.EXISTENTIAL,
    pred="tall",
    args=None,
    macro=MacroTemplate.GROUND_POSITIVE,
    extra_facts=None,
):
    if args is None:
        args = [entity_id]
    entities = [Entity(id=entity_id, surface=entity_surface, entity_type=entity_type)]
    facts = [Fact(pred=pred, args=args)]
    if extra_facts:
        facts.extend(extra_facts)
    sentence = SentenceExtraction(
        nl="Test sentence.",
        entities=entities,
        facts=facts,
        macro_template=macro,
    )
    return ProblemExtraction(problem_id=problem_id, sentences=[sentence])


# ── Spec tests from CLAUDE_CODE_SPEC.md ──────────────────────────────────────

def test_unary_fact_generates_existence_test():
    """From spec: 1-arg fact on existential → exists x.Tall(x) + type-binding."""
    extraction = ProblemExtraction(
        problem_id="test",
        sentences=[SentenceExtraction(
            nl="The tall tree.",
            entities=[Entity(id="e1", surface="tree", entity_type=EntityType.EXISTENTIAL)],
            facts=[Fact(pred="tall", args=["e1"])],
            macro_template=MacroTemplate.GROUND_POSITIVE,
        )],
    )
    suite = compile_test_suite(extraction)
    fol_strings = [t.fol_string for t in suite.positive_tests]
    assert "exists x.Tall(x)" in fol_strings, f"vocab test missing; got {fol_strings}"
    assert any("Tree" in f and "Tall" in f for f in fol_strings), (
        f"binding test missing; got {fol_strings}"
    )


def test_universal_entity_generates_all_test():
    """Universal entity type → all x.(Kid(x) -> Young(x)) macro test."""
    extraction = ProblemExtraction(
        problem_id="t2",
        sentences=[SentenceExtraction(
            nl="All kids are young.",
            entities=[Entity(id="e1", surface="kid", entity_type=EntityType.UNIVERSAL)],
            facts=[Fact(pred="kid", args=["e1"]), Fact(pred="young", args=["e1"])],
            macro_template=MacroTemplate.TYPE_A,
        )],
    )
    suite = compile_test_suite(extraction)
    pos = [t.fol_string for t in suite.positive_tests]
    assert any("all x." in f and "Kid" in f and "Young" in f for f in pos), (
        f"TYPE_A macro test missing; got {pos}"
    )


def test_binary_fact_both_constants():
    """2-arg fact with two constants → grounded Pred(c1, c2)."""
    extraction = ProblemExtraction(
        problem_id="t3",
        sentences=[SentenceExtraction(
            nl="Lana directed After Tiller.",
            entities=[
                Entity(id="lana", surface="Lana", entity_type=EntityType.CONSTANT),
                Entity(id="afterTiller", surface="After Tiller", entity_type=EntityType.CONSTANT),
            ],
            facts=[Fact(pred="directed", args=["lana", "afterTiller"])],
            macro_template=MacroTemplate.GROUND_POSITIVE,
        )],
    )
    suite = compile_test_suite(extraction)
    pos = [t.fol_string for t in suite.positive_tests]
    assert any("Directed(lana, afterTiller)" in f or "Directed(lana,afterTiller)" in f
               for f in pos), f"grounded binary test missing; got {pos}"


def test_negative_tests_use_antonym():
    """Negative test for 'tall' should use 'Short' (from perturbation map)."""
    extraction = _make_problem(pred="tall")
    suite = compile_test_suite(extraction)
    neg = [t.fol_string for t in suite.negative_tests]
    assert any("Short" in f for f in neg), f"antonym test missing; got {neg}"


def test_negative_tests_fallback_non_prefix():
    """Predicate not in map → 'Non<Pred>' negative."""
    extraction = _make_problem(pred="xyzpredicate")
    suite = compile_test_suite(extraction)
    neg = [t.fol_string for t in suite.negative_tests]
    assert any("NonXyzpredicate" in f for f in neg), f"Non-prefix test missing; got {neg}"


def test_no_duplicate_positive_tests():
    """Positive tests must be deduplicated by FOL string."""
    extraction = ProblemExtraction(
        problem_id="dedup",
        sentences=[SentenceExtraction(
            nl="The tall tree is tall.",
            entities=[Entity(id="e1", surface="tree", entity_type=EntityType.EXISTENTIAL)],
            facts=[Fact(pred="tall", args=["e1"]), Fact(pred="tall", args=["e1"])],
            macro_template=MacroTemplate.GROUND_POSITIVE,
        )],
    )
    suite = compile_test_suite(extraction)
    fol_strings = [t.fol_string for t in suite.positive_tests]
    assert len(fol_strings) == len(set(fol_strings)), "duplicate positive tests found"


def test_ground_negative_macro():
    """GROUND_NEGATIVE macro should produce negated grounded fact test."""
    extraction = ProblemExtraction(
        problem_id="gneg",
        sentences=[SentenceExtraction(
            nl="Nancy is not happy.",
            entities=[Entity(id="nancy", surface="nancy", entity_type=EntityType.CONSTANT)],
            facts=[Fact(pred="happy", args=["nancy"], negated=True)],
            macro_template=MacroTemplate.GROUND_NEGATIVE,
        )],
    )
    suite = compile_test_suite(extraction)
    pos = [t.fol_string for t in suite.positive_tests]
    assert any("-Happy(nancy)" in f for f in pos), f"negated ground test missing; got {pos}"


def test_type_e_macro():
    """TYPE_E → all x.(Bird(x) -> -Flies(x))."""
    extraction = ProblemExtraction(
        problem_id="te",
        sentences=[SentenceExtraction(
            nl="No bird flies.",
            entities=[Entity(id="e1", surface="bird", entity_type=EntityType.UNIVERSAL)],
            facts=[Fact(pred="bird", args=["e1"]), Fact(pred="flies", args=["e1"])],
            macro_template=MacroTemplate.TYPE_E,
        )],
    )
    suite = compile_test_suite(extraction)
    pos = [t.fol_string for t in suite.positive_tests]
    assert any("all x." in f and "Bird" in f and "-Flies" in f for f in pos), (
        f"TYPE_E macro test missing; got {pos}"
    )


def test_total_tests_nonzero():
    extraction = _make_problem()
    suite = compile_test_suite(extraction)
    assert suite.total_tests > 0
