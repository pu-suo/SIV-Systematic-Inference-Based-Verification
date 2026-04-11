"""Tests for siv/compiler.py"""
import pytest
from siv.schema import (
    Constant, Entity, EntityType, Fact, MacroTemplate,
    ProblemExtraction, SentenceExtraction,
)
from siv.compiler import (
    compile_test_suite,
    compile_sentence_test_suite,
    validate_neo_davidsonian,
    _to_camel_case,
    _compile_vocabulary_tests,
    _compile_binding_tests,
    _compile_negative_tests,
)
from siv.schema import SchemaViolation


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


# ── compile_sentence_test_suite ───────────────────────────────────────────────

def test_compile_sentence_test_suite_returns_test_suite():
    """compile_sentence_test_suite wraps one sentence and returns a TestSuite."""
    sentence = SentenceExtraction(
        nl="The tall tree grows.",
        entities=[Entity(id="e1", surface="tree", entity_type=EntityType.EXISTENTIAL)],
        facts=[Fact(pred="tall", args=["e1"]), Fact(pred="grows", args=["e1"])],
        macro_template=MacroTemplate.GROUND_POSITIVE,
    )
    suite = compile_sentence_test_suite(sentence, problem_id="s1")
    assert suite.problem_id == "s1"
    assert suite.total_tests > 0


def test_compile_sentence_test_suite_matches_single_sentence_problem():
    """Results from compile_sentence_test_suite == compile_test_suite for one sentence."""
    sentence = SentenceExtraction(
        nl="The cat sleeps.",
        entities=[Entity(id="e1", surface="cat", entity_type=EntityType.EXISTENTIAL)],
        facts=[Fact(pred="sleeps", args=["e1"])],
        macro_template=MacroTemplate.GROUND_POSITIVE,
    )
    suite_sentence = compile_sentence_test_suite(sentence, problem_id="p1")
    wrapped = ProblemExtraction(problem_id="p1", sentences=[sentence])
    suite_problem = compile_test_suite(wrapped)

    pos_s = sorted(t.fol_string for t in suite_sentence.positive_tests)
    pos_p = sorted(t.fol_string for t in suite_problem.positive_tests)
    assert pos_s == pos_p


# ── Constant (new-style) in binding tests ────────────────────────────────────

def test_new_style_constant_unary_binding():
    """New-style Constant in constants list → grounded Pred(const_id) binding test."""
    sentence = SentenceExtraction(
        nl="Bonnie sings.",
        entities=[],
        facts=[Fact(pred="sings", args=["bonnie"])],
        macro_template=MacroTemplate.GROUND_POSITIVE,
        constants=[Constant(id="bonnie", surface="Bonnie")],
    )
    prob = ProblemExtraction(problem_id="t", sentences=[sentence])
    suite = compile_test_suite(prob)
    pos = [t.fol_string for t in suite.positive_tests]
    assert any("Sings(bonnie)" in f for f in pos), f"grounded test missing; got {pos}"


def test_new_style_constant_entity_binary_binding():
    """Pred(const, entity) → exists x.(EntType(x) & Pred(const_id, x))."""
    sentence = SentenceExtraction(
        nl="Lana directed a film.",
        entities=[Entity(id="e1", surface="film", entity_type=EntityType.EXISTENTIAL)],
        facts=[Fact(pred="directed", args=["lana", "e1"])],
        macro_template=MacroTemplate.GROUND_POSITIVE,
        constants=[Constant(id="lana", surface="Lana")],
    )
    prob = ProblemExtraction(problem_id="t", sentences=[sentence])
    suite = compile_test_suite(prob)
    pos = [t.fol_string for t in suite.positive_tests]
    assert any("Film(x)" in f and "lana" in f for f in pos), (
        f"const+entity binding test missing; got {pos}"
    )


def test_new_style_two_constants_binary_binding():
    """Pred(const, const) → grounded Pred(c1, c2) with no quantifiers."""
    sentence = SentenceExtraction(
        nl="Lana directed AfterTiller.",
        entities=[],
        facts=[Fact(pred="directed", args=["lana", "afterTiller"])],
        macro_template=MacroTemplate.GROUND_POSITIVE,
        constants=[
            Constant(id="lana", surface="Lana"),
            Constant(id="afterTiller", surface="After Tiller"),
        ],
    )
    prob = ProblemExtraction(problem_id="t", sentences=[sentence])
    suite = compile_test_suite(prob)
    pos = [t.fol_string for t in suite.positive_tests]
    assert any(
        ("Directed(lana, afterTiller)" in f or "Directed(lana,afterTiller)" in f)
        for f in pos
    ), f"grounded binary test missing; got {pos}"


# ── Fix A: universal-aware binding and vocabulary tests ───────────────────────

def test_fix_A_universal_binary_binding_emits_universal_shape():
    """FIX A: universal subject → all x.(SubjType(x) -> exists y.(ObjType(y) & Pred(x,y)))."""
    sentence = SentenceExtraction(
        nl="All students read books.",
        entities=[
            Entity(id="e1", surface="students", entity_type=EntityType.UNIVERSAL),
            Entity(id="e2", surface="books",    entity_type=EntityType.EXISTENTIAL),
        ],
        facts=[Fact(pred="read", args=["e1", "e2"])],
        macro_template=MacroTemplate.TYPE_A,
    )
    prob = ProblemExtraction(problem_id="fix_a_1", sentences=[sentence])
    suite = compile_test_suite(prob)
    pos = [t.fol_string for t in suite.positive_tests]

    # Must contain a universal-shaped binding test
    assert any(
        "all x." in f and "Students(x) ->" in f and "Books(y)" in f and "Read(x, y)" in f
        for f in pos
    ), f"Expected all x. universal binding test; got {pos}"

    # Must NOT contain a pure existential double-quantified test for this fact
    import re
    assert not any(re.match(r"^exists x\.\(exists y\.\(Students", f) for f in pos), (
        f"Unexpected existential binding for universal subject; got {pos}"
    )


def test_fix_A_existential_binary_binding_unchanged():
    """FIX A no-regression: both existential → exists x.(exists y.(SubjType(x) & ObjType(y) & Pred(x,y)))."""
    sentence = SentenceExtraction(
        nl="A student read a book.",
        entities=[
            Entity(id="e1", surface="students", entity_type=EntityType.EXISTENTIAL),
            Entity(id="e2", surface="books",    entity_type=EntityType.EXISTENTIAL),
        ],
        facts=[Fact(pred="read", args=["e1", "e2"])],
        macro_template=MacroTemplate.GROUND_POSITIVE,
    )
    prob = ProblemExtraction(problem_id="fix_a_2", sentences=[sentence])
    suite = compile_test_suite(prob)
    pos = [t.fol_string for t in suite.positive_tests]

    assert any(
        f.startswith("exists x.(exists y.")
        and "Students(x)" in f
        and "Books(y)" in f
        and "Read(x, y)" in f
        for f in pos
    ), f"Expected existential binding for both-existential case; got {pos}"


def test_fix_A_vocabulary_probe_suppressed_for_universal_fact():
    """FIX A: vocabulary probe must be suppressed for facts with a universal argument."""
    sentence = SentenceExtraction(
        nl="All employees schedule meetings.",
        entities=[
            Entity(id="e1", surface="employees", entity_type=EntityType.UNIVERSAL),
            Entity(id="e2", surface="meetings",  entity_type=EntityType.EXISTENTIAL),
        ],
        facts=[Fact(pred="schedule", args=["e1", "e2"])],
        macro_template=MacroTemplate.TYPE_A,
    )
    prob = ProblemExtraction(problem_id="fix_a_3", sentences=[sentence])
    suite = compile_test_suite(prob)
    vocab_fols = [t.fol_string for t in suite.positive_tests if t.test_type == "vocabulary"]

    assert "exists x.(exists y.Schedule(x,y))" not in vocab_fols, (
        f"Vocabulary probe must be suppressed for universal-scoped fact; got {vocab_fols}"
    )


def test_fix_A_vocabulary_probe_retained_for_mixed_facts():
    """FIX A: if a predicate appears in both universal and non-universal facts, non-universal emits the probe."""
    s_universal = SentenceExtraction(
        nl="All students read books.",
        entities=[
            Entity(id="e1", surface="students", entity_type=EntityType.UNIVERSAL),
            Entity(id="e2", surface="books",    entity_type=EntityType.EXISTENTIAL),
        ],
        facts=[Fact(pred="read", args=["e1", "e2"])],
        macro_template=MacroTemplate.TYPE_A,
    )
    s_existential = SentenceExtraction(
        nl="A student read a book.",
        entities=[
            Entity(id="e3", surface="students", entity_type=EntityType.EXISTENTIAL),
            Entity(id="e4", surface="books",    entity_type=EntityType.EXISTENTIAL),
        ],
        facts=[Fact(pred="read", args=["e3", "e4"])],
        macro_template=MacroTemplate.GROUND_POSITIVE,
    )
    prob = ProblemExtraction(problem_id="fix_a_4", sentences=[s_universal, s_existential])
    suite = compile_test_suite(prob)
    vocab_fols = [t.fol_string for t in suite.positive_tests if t.test_type == "vocabulary"]

    read_probes = [f for f in vocab_fols if "Read" in f]
    assert len(read_probes) == 1, (
        f"Expected exactly one Read vocabulary probe from non-universal appearance; got {read_probes}"
    )


# ── Fix G1: conditional macro template accepts binary facts ───────────────────

def test_fix_G1_conditional_with_binary_facts_emits_macro_test():
    """FIX G1: CONDITIONAL with two binary facts sharing a subject emits one macro test."""
    # Mirrors P4 from the 1208 trace:
    # "If an employee has lunch at home, they are working remotely from home."
    sentence = SentenceExtraction(
        nl="If an employee has lunch at home, they are working remotely from home.",
        entities=[
            Entity(id="e1", surface="employee", entity_type=EntityType.EXISTENTIAL),
            Entity(id="e2", surface="home",     entity_type=EntityType.EXISTENTIAL),
        ],
        facts=[
            Fact(pred="has lunch at",          args=["e1", "e2"]),
            Fact(pred="working remotely from", args=["e1", "e2"]),
        ],
        macro_template=MacroTemplate.CONDITIONAL,
    )
    prob = ProblemExtraction(problem_id="fix_g1_1", sentences=[sentence])
    suite = compile_test_suite(prob)

    entailment_tests = [t for t in suite.positive_tests if t.test_type == "entailment"]
    assert len(entailment_tests) == 1, (
        f"Expected exactly one entailment test from CONDITIONAL macro; got {entailment_tests}"
    )
    fol = entailment_tests[0].fol_string
    assert "all x." in fol, f"Expected universally quantified test; got {fol}"
    assert "HasLunchAt" in fol, f"Expected HasLunchAt in macro test; got {fol}"
    assert "WorkingRemotelyFrom" in fol, f"Expected WorkingRemotelyFrom in macro test; got {fol}"
    assert " -> " in fol, f"Expected implication arrow in macro test; got {fol}"


def test_fix_G1_conditional_without_shared_arg_skipped():
    """FIX G1: CONDITIONAL with no shared argument between facts emits no entailment test."""
    sentence = SentenceExtraction(
        nl="He has something and she likes something.",
        entities=[
            Entity(id="e1", surface="person1", entity_type=EntityType.EXISTENTIAL),
            Entity(id="e2", surface="item1",   entity_type=EntityType.EXISTENTIAL),
            Entity(id="e3", surface="person2", entity_type=EntityType.EXISTENTIAL),
            Entity(id="e4", surface="item2",   entity_type=EntityType.EXISTENTIAL),
        ],
        facts=[
            Fact(pred="has",   args=["e1", "e2"]),
            Fact(pred="likes", args=["e3", "e4"]),
        ],
        macro_template=MacroTemplate.CONDITIONAL,
    )
    prob = ProblemExtraction(problem_id="fix_g1_2", sentences=[sentence])
    suite = compile_test_suite(prob)

    entailment_tests = [t for t in suite.positive_tests if t.test_type == "entailment"]
    assert len(entailment_tests) == 0, (
        f"Expected no entailment test when facts share no argument; got {entailment_tests}"
    )


# ── Fix G2: TYPE_A/TYPE_E/TYPE_I/TYPE_O use entity_type for subject selection ─

def test_fix_G2_type_A_picks_universal_entity_not_first():
    """FIX G2: TYPE_A picks the universal entity even when it is not entities[0]."""
    # Universal entity (students) is second; existential (book) is first.
    # obj_fact is on the EXISTENTIAL entity so the macro FOL won't collide with
    # the binding test (binding: exists x.(Book(x) & Interesting(x));
    # macro new: all x.(Students(x) -> Interesting(x));
    # macro old: all x.(Book(x) -> Interesting(x))).
    # Old code: subj_ent = entities[0] = book → "all x.(Book(x) -> Interesting(x))"   [WRONG]
    # New code: subj_ent = universal_entities[0] = students → "all x.(Students(x) -> Interesting(x))" [CORRECT]
    sentence = SentenceExtraction(
        nl="Students read interesting books.",
        entities=[
            Entity(id="e1", surface="book",     entity_type=EntityType.EXISTENTIAL),  # first, but existential
            Entity(id="e2", surface="students", entity_type=EntityType.UNIVERSAL),    # second, but universal
        ],
        facts=[
            Fact(pred="read",        args=["e2", "e1"]),  # binary fact
            Fact(pred="interesting", args=["e1"]),         # 1-arg fact on EXISTENTIAL → avoids binding collision
        ],
        macro_template=MacroTemplate.TYPE_A,
    )
    prob = ProblemExtraction(problem_id="fix_g2_1", sentences=[sentence])
    suite = compile_test_suite(prob)

    # The macro test (test_type=="entailment") will only be deduplicated by the binding test if
    # they produce the same FOL string. With obj_pred from existential entity, they differ.
    macro_tests = [t for t in suite.positive_tests if t.test_type == "entailment"]
    assert len(macro_tests) >= 1, f"Expected at least one macro entailment test; got {macro_tests}"
    assert any("all x.(Students(x) ->" in t.fol_string for t in macro_tests), (
        f"Expected macro test to bind over Students (universal), not Book; got "
        f"{[t.fol_string for t in macro_tests]}"
    )


def test_fix_G2_type_I_picks_existential():
    """FIX G2: TYPE_I picks the existential entity even when entities[0] is universal."""
    # Universal entity (students) is first; existential (book) is second.
    # obj_fact is on the UNIVERSAL entity so the macro FOL won't collide with the binding test
    # (binding: all x.(Students(x) -> Smart(x));
    # macro new: exists x.(Book(x) & Smart(x));
    # macro old: exists x.(Students(x) & Smart(x))).
    # Old code: subj_ent = entities[0] = students → "exists x.(Students(x) & Smart(x))"  [WRONG]
    # New code: subj_ent = existential_entities[0] = book → "exists x.(Book(x) & Smart(x))" [CORRECT]
    sentence = SentenceExtraction(
        nl="Smart students read books.",
        entities=[
            Entity(id="e1", surface="students", entity_type=EntityType.UNIVERSAL),    # first, but universal
            Entity(id="e2", surface="book",     entity_type=EntityType.EXISTENTIAL),  # second, but existential
        ],
        facts=[
            Fact(pred="read",  args=["e1", "e2"]),  # binary fact
            Fact(pred="smart",  args=["e1"]),        # 1-arg fact on UNIVERSAL entity → avoids binding collision
        ],
        macro_template=MacroTemplate.TYPE_I,
    )
    prob = ProblemExtraction(problem_id="fix_g2_2", sentences=[sentence])
    suite = compile_test_suite(prob)

    # New code: TYPE_I uses existential entity (book) → "exists x.(Book(x) & Smart(x))"
    # which is different from the universal binding test "all x.(Students(x) -> Smart(x))"
    macro_tests = [t for t in suite.positive_tests if t.test_type == "entailment"]
    assert len(macro_tests) >= 1, f"Expected at least one macro entailment test; got {macro_tests}"
    assert any(t.fol_string.startswith("exists x.(Book(x) & ") for t in macro_tests), (
        f"Expected macro test to bind over Book (existential), not Students; got "
        f"{[t.fol_string for t in macro_tests]}"
    )


def test_fix_G2_no_universal_entity_skipped():
    """FIX G2: TYPE_A with all-existential entities emits no macro entailment test."""
    sentence = SentenceExtraction(
        nl="A student reads a book.",
        entities=[
            Entity(id="e1", surface="student", entity_type=EntityType.EXISTENTIAL),
            Entity(id="e2", surface="book",    entity_type=EntityType.EXISTENTIAL),
        ],
        facts=[
            Fact(pred="reads",  args=["e1", "e2"]),
            Fact(pred="studious", args=["e1"]),
        ],
        macro_template=MacroTemplate.TYPE_A,
    )
    prob = ProblemExtraction(problem_id="fix_g2_3", sentences=[sentence])
    suite = compile_test_suite(prob)

    macro_tests = [t for t in suite.positive_tests if t.test_type == "entailment"]
    assert len(macro_tests) == 0, (
        f"Expected no macro test for TYPE_A with no universal entity; got {macro_tests}"
    )


# ── Fix D1 + D2: in-problem structural precision tests ────────────────────────

def test_fix_D1_binary_fact_gets_argument_swap_test():
    """FIX D1: binary fact with two constants → argument-swap contrastive test."""
    sentence = SentenceExtraction(
        nl="Alice likes Bob.",
        entities=[],
        facts=[Fact(pred="likes", args=["alice", "bob"])],
        macro_template=MacroTemplate.GROUND_POSITIVE,
        constants=[
            Constant(id="alice", surface="alice"),
            Constant(id="bob",   surface="bob"),
        ],
    )
    prob = ProblemExtraction(problem_id="fix_d1_1", sentences=[sentence])
    suite = compile_test_suite(prob)
    neg = [t.fol_string for t in suite.negative_tests]
    assert "Likes(bob, alice)" in neg, (
        f"Expected argument-swap test 'Likes(bob, alice)'; got {neg}"
    )


def test_fix_D1_universal_binary_fact_gets_universal_swap_test():
    """FIX D1: binary fact with universal subject → swapped form is universally wrapped."""
    sentence = SentenceExtraction(
        nl="All students read books.",
        entities=[
            Entity(id="e1", surface="students", entity_type=EntityType.UNIVERSAL),
            Entity(id="e2", surface="books",    entity_type=EntityType.EXISTENTIAL),
        ],
        facts=[Fact(pred="read", args=["e1", "e2"])],
        macro_template=MacroTemplate.TYPE_A,
    )
    prob = ProblemExtraction(problem_id="fix_d1_2", sentences=[sentence])
    suite = compile_test_suite(prob)
    neg = [t.fol_string for t in suite.negative_tests]
    # Swapped form: Read(e2, e1) → e2=books existential, e1=students universal
    # e2 is now first arg (existential) and e1 is second arg (universal → x)
    assert any(f.startswith("all x.") and "Read(y, x)" in f for f in neg), (
        f"Expected universally-wrapped swap test containing 'Read(y, x)'; got {neg}"
    )


def test_fix_D2_polarity_flip_emitted():
    """FIX D2: non-negated unary constant fact → polarity-flip contrastive test is -Pred(const)."""
    sentence = SentenceExtraction(
        nl="James is a manager.",
        entities=[],
        facts=[Fact(pred="manager", args=["james"])],
        macro_template=MacroTemplate.GROUND_POSITIVE,
        constants=[Constant(id="james", surface="James")],
    )
    prob = ProblemExtraction(problem_id="fix_d2_1", sentences=[sentence])
    suite = compile_test_suite(prob)
    neg = [t.fol_string for t in suite.negative_tests]
    assert "-Manager(james)" in neg, (
        f"Expected polarity-flip test '-Manager(james)'; got {neg}"
    )


def test_fix_D2_negated_fact_gets_positive_flip():
    """FIX D2: negated unary constant fact → polarity-flip is the positive (un-negated) form."""
    sentence = SentenceExtraction(
        nl="James is not a manager.",
        entities=[],
        facts=[Fact(pred="manager", args=["james"], negated=True)],
        macro_template=MacroTemplate.GROUND_NEGATIVE,
        constants=[Constant(id="james", surface="James")],
    )
    prob = ProblemExtraction(problem_id="fix_d2_2", sentences=[sentence])
    suite = compile_test_suite(prob)
    neg = [t.fol_string for t in suite.negative_tests]
    assert "Manager(james)" in neg, (
        f"Expected positive-flip test 'Manager(james)'; got {neg}"
    )


def test_fix_D1_D2_cross_predicate_substitution():
    """FIX D1+D2: two binary facts → cross-predicate substitution fires at least once."""
    s_a = SentenceExtraction(
        nl="Alice likes Bob.",
        entities=[],
        facts=[Fact(pred="likes", args=["alice", "bob"])],
        macro_template=MacroTemplate.GROUND_POSITIVE,
        constants=[
            Constant(id="alice",   surface="alice"),
            Constant(id="bob",     surface="bob"),
        ],
    )
    s_b = SentenceExtraction(
        nl="Charlie hates Dave.",
        entities=[],
        facts=[Fact(pred="hates", args=["charlie", "dave"])],
        macro_template=MacroTemplate.GROUND_POSITIVE,
        constants=[
            Constant(id="charlie", surface="charlie"),
            Constant(id="dave",    surface="dave"),
        ],
    )
    prob = ProblemExtraction(problem_id="fix_d1d2_3", sentences=[s_a, s_b])
    suite = compile_test_suite(prob)
    neg = [t.fol_string for t in suite.negative_tests]
    # Cross-predicate substitution must have fired at least once
    assert "Hates(alice, bob)" in neg or "Likes(charlie, dave)" in neg, (
        f"Expected cross-predicate substitution in negative tests; got {neg}"
    )


def test_no_antonym_predicates_in_negative_tests():
    """FIX D1+D2 (Tenet 1 trip-wire): every predicate in a negative test also appears in positive tests."""
    from siv.fol_utils import extract_predicates

    sentence = SentenceExtraction(
        nl="All employees schedule meetings with customers.",
        entities=[
            Entity(id="e1", surface="employees", entity_type=EntityType.UNIVERSAL),
            Entity(id="e2", surface="meetings",  entity_type=EntityType.EXISTENTIAL),
            Entity(id="e3", surface="customers", entity_type=EntityType.EXISTENTIAL),
        ],
        facts=[
            Fact(pred="schedule", args=["e1", "e2"]),
            Fact(pred="with",     args=["e2", "e3"]),
        ],
        macro_template=MacroTemplate.TYPE_A,
    )
    prob = ProblemExtraction(problem_id="fix_d_tenet1", sentences=[sentence])
    suite = compile_test_suite(prob)

    positive_preds: set = set()
    for t in suite.positive_tests:
        positive_preds |= extract_predicates(t.fol_string)

    for t in suite.negative_tests:
        neg_preds = extract_predicates(t.fol_string)
        foreign = neg_preds - positive_preds
        assert not foreign, (
            f"Foreign predicates in negative test '{t.fol_string}': {foreign}. "
            "Every predicate must come from the problem's own vocabulary."
        )


def test_no_Non_predicate_anywhere():
    """Permanent guard: no test in positive or negative list contains a 'Non<Pred>' pattern."""
    import re as _re
    sentence = SentenceExtraction(
        nl="All students read interesting books.",
        entities=[
            Entity(id="e1", surface="students", entity_type=EntityType.UNIVERSAL),
            Entity(id="e2", surface="books",    entity_type=EntityType.EXISTENTIAL),
        ],
        facts=[
            Fact(pred="read",        args=["e1", "e2"]),
            Fact(pred="interesting", args=["e2"]),
        ],
        macro_template=MacroTemplate.TYPE_A,
    )
    prob = ProblemExtraction(problem_id="fix_d_non_guard", sentences=[sentence])
    suite = compile_test_suite(prob)

    all_tests = suite.positive_tests + suite.negative_tests
    for t in all_tests:
        assert not _re.search(r"Non[A-Z]", t.fol_string), (
            f"Forbidden 'Non<Pred>' pattern found in test: '{t.fol_string}'"
        )


def test_perturbation_map_not_loaded():
    """FIX D1+D2: compiler module must not contain antonym-map symbols or the deleted file."""
    import importlib
    import siv.compiler as compiler_mod

    for forbidden_name in ("_PERTURBATION_MAP", "_load_perturbation_map", "_get_perturbation"):
        assert not hasattr(compiler_mod, forbidden_name), (
            f"Deleted symbol '{forbidden_name}' still present in siv.compiler"
        )

    from pathlib import Path
    map_path = Path(importlib.util.find_spec("siv").submodule_search_locations[0]).parent / "data" / "perturbation_map.json"
    assert not map_path.exists(), (
        f"data/perturbation_map.json still exists at {map_path}; it must be deleted"
    )


# ── Fix C1: Neo-Davidsonian schema validator ──────────────────────────────────

def _make_problem_with_fact(
    pred: str,
    args,
    entity_type=EntityType.EXISTENTIAL,
    negated: bool = False,
):
    """Helper: one-sentence problem with the given fact and one entity per arg."""
    entities = [
        Entity(id=a, surface=a, entity_type=entity_type)
        for a in args
        if not any(c.isdigit() for c in a[:1])  # skip constants; use all ids as entities
    ]
    entities = [Entity(id=f"e{i+1}", surface=f"e{i+1}", entity_type=entity_type)
                for i in range(len(args))]
    fact = Fact(pred=pred, args=[f"e{i+1}" for i in range(len(args))], negated=negated)
    sentence = SentenceExtraction(
        nl="Test sentence.",
        entities=entities,
        facts=[fact],
        macro_template=MacroTemplate.GROUND_POSITIVE,
    )
    return ProblemExtraction(problem_id="test_c1", sentences=[sentence])


def test_fix_C1_prepositional_unary_detected():
    """FIX C1: 1-arg fact with preposition 'from' in predicate → prepositional_unary violation."""
    prob = _make_problem_with_fact("work remotely from home", ["e1"])
    violations = validate_neo_davidsonian(prob)
    assert len(violations) == 1, f"Expected 1 violation; got {violations}"
    assert violations[0].violation_type == "prepositional_unary", (
        f"Expected prepositional_unary; got {violations[0].violation_type}"
    )
    assert "from" in violations[0].message, (
        f"Expected 'from' in violation message; got {violations[0].message}"
    )


def test_fix_C1_clean_unary_not_flagged():
    """FIX C1: 1-arg fact with no preposition → no violation."""
    prob = _make_problem_with_fact("tall", ["e1"])
    violations = validate_neo_davidsonian(prob)
    assert violations == [], f"Expected no violations for clean unary; got {violations}"


def test_fix_C1_binary_with_preposition_in_pred_not_flagged():
    """FIX C1: 2-arg fact with preposition in predicate name → no violation (correctly decomposed)."""
    # 'lunch in' has a preposition but arity is 2 — the preposition IS the relation name.
    # The prepositional_unary rule only fires for arity == 1.
    prob = _make_problem_with_fact("lunch in", ["e1", "e2"])
    violations = validate_neo_davidsonian(prob)
    assert violations == [], (
        f"Expected no violations for binary fact with preposition in predicate; got {violations}"
    )


def test_fix_C1_high_arity_detected():
    """FIX C1: 3-arg fact → high_arity violation."""
    prob = _make_problem_with_fact("schedule", ["e1", "e2", "e3"])
    violations = validate_neo_davidsonian(prob)
    assert any(v.violation_type == "high_arity" for v in violations), (
        f"Expected high_arity violation for 3-arg fact; got {violations}"
    )


def test_fix_C1_compile_attaches_violations():
    """FIX C1: compile_test_suite attaches violations to TestSuite.violations."""
    prob = _make_problem_with_fact("work remotely from home", ["e1"])
    suite = compile_test_suite(prob)
    assert suite.has_violations is True, "Expected suite.has_violations to be True"
    assert len(suite.violations) >= 1, f"Expected at least 1 violation; got {suite.violations}"


def test_fix_C1_verify_short_circuits_on_invalid_extraction():
    """FIX C1: verifier short-circuits on invalid extraction → extraction_invalid=True, prover_calls=0."""
    from siv.verifier import verify
    prob = _make_problem_with_fact("work remotely from home", ["e1"])
    suite = compile_test_suite(prob)
    result = verify("exists x.WorkRemotelyFromHome(x)", suite, unresolved_policy="exclude")
    assert result.extraction_invalid is True, (
        f"Expected extraction_invalid=True; got {result.extraction_invalid}"
    )
    assert result.siv_score == 0.0, (
        f"Expected siv_score=0.0 for invalid extraction; got {result.siv_score}"
    )
    assert result.prover_calls == 0, (
        f"Expected prover_calls=0 (short-circuited); got {result.prover_calls}"
    )


def test_fix_C1_clean_extraction_unaffected():
    """FIX C1: fully valid extraction → extraction_invalid=False, normal pipeline runs."""
    from siv.verifier import verify
    sentence = SentenceExtraction(
        nl="All students read books.",
        entities=[
            Entity(id="e1", surface="students", entity_type=EntityType.UNIVERSAL),
            Entity(id="e2", surface="books",    entity_type=EntityType.EXISTENTIAL),
        ],
        facts=[Fact(pred="read", args=["e1", "e2"])],
        macro_template=MacroTemplate.TYPE_A,
    )
    prob = ProblemExtraction(problem_id="clean_c1", sentences=[sentence])
    suite = compile_test_suite(prob)
    assert suite.has_violations is False, (
        f"Expected no violations for clean extraction; got {suite.violations}"
    )
    result = verify("all x.(Students(x) -> exists y.(Books(y) & Read(x, y)))", suite,
                    unresolved_policy="exclude")
    assert result.extraction_invalid is False, (
        f"Expected extraction_invalid=False for clean extraction; got {result.extraction_invalid}"
    )


# ── Dedup preserves highest-priority test_type ────────────────────────────────

def test_dedup_preserves_entailment_tag():
    """When binding and entailment paths produce the same FOL string,
    the resulting UnitTest must have test_type=='entailment'."""
    # A TYPE_A sentence with a single 1-arg universal entity and two facts:
    # binding test for 'young' and macro test both produce all x.(Kid(x) -> Young(x)).
    # The dedup must keep the entailment tag.
    sentence = SentenceExtraction(
        nl="All kids are young.",
        entities=[Entity(id="e1", surface="kid", entity_type=EntityType.UNIVERSAL)],
        facts=[Fact(pred="kid", args=["e1"]), Fact(pred="young", args=["e1"])],
        macro_template=MacroTemplate.TYPE_A,
    )
    prob = ProblemExtraction(problem_id="dedup_tag", sentences=[sentence])
    suite = compile_test_suite(prob)

    target_fol = "all x.(Kid(x) -> Young(x))"
    matching = [t for t in suite.positive_tests if t.fol_string == target_fol]
    assert len(matching) == 1, (
        f"Expected exactly one test with the macro FOL string; got {[t.fol_string for t in suite.positive_tests]}"
    )
    assert matching[0].test_type == "entailment", (
        f"Expected test_type='entailment' after dedup; got '{matching[0].test_type}'"
    )
