"""Tests for siv/schema.py"""
import pytest
from siv.schema import (
    Constant, Entity, EntityType, Fact, CompoundAnalysis,
    SentenceExtraction, ProblemExtraction,
    UnitTest, TestSuite, VerificationResult,
    MacroTemplate,
)


def _make_sentence(nl="The tree is tall.", entity_id="e1", entity_surface="tree",
                   pred="tall", macro=MacroTemplate.GROUND_POSITIVE):
    entity = Entity(id=entity_id, surface=entity_surface, entity_type=EntityType.EXISTENTIAL)
    fact = Fact(pred=pred, args=[entity_id])
    return SentenceExtraction(nl=nl, entities=[entity], facts=[fact], macro_template=macro)


# ── Constant ──────────────────────────────────────────────────────────────────

def test_constant_fields():
    c = Constant(id="bonnie", surface="Bonnie")
    assert c.id == "bonnie"
    assert c.surface == "Bonnie"


def test_constant_camelcase_id():
    c = Constant(id="lanaWilson", surface="Lana Wilson")
    assert c.id == "lanaWilson"


def test_sentence_extraction_constants_field():
    c = Constant(id="elizabeth", surface="Elizabeth")
    e = Entity(id="e1", surface="club", entity_type=EntityType.EXISTENTIAL)
    f = Fact(pred="member", args=["elizabeth", "e1"])
    sent = SentenceExtraction(
        nl="Elizabeth is in the club.",
        entities=[e],
        facts=[f],
        macro_template=MacroTemplate.GROUND_POSITIVE,
        constants=[c],
    )
    assert len(sent.constants) == 1
    assert sent.constants[0].id == "elizabeth"


def test_problem_extraction_all_constants():
    c1 = Constant(id="bonnie", surface="Bonnie")
    c2 = Constant(id="bonnie", surface="Bonnie")  # duplicate — should deduplicate
    s1 = SentenceExtraction(
        nl="Bonnie sings.",
        entities=[],
        facts=[Fact(pred="sings", args=["bonnie"])],
        macro_template=MacroTemplate.GROUND_POSITIVE,
        constants=[c1],
    )
    s2 = SentenceExtraction(
        nl="Bonnie dances.",
        entities=[],
        facts=[Fact(pred="dances", args=["bonnie"])],
        macro_template=MacroTemplate.GROUND_POSITIVE,
        constants=[c2],
    )
    prob = ProblemExtraction(problem_id="p1", sentences=[s1, s2])
    assert len(prob.all_constants) == 1
    assert prob.all_constants[0].id == "bonnie"


# ── Entity ────────────────────────────────────────────────────────────────────

def test_entity_fields():
    e = Entity(id="c1", surface="nancy", entity_type=EntityType.CONSTANT)
    assert e.id == "c1"
    assert e.surface == "nancy"
    assert e.entity_type == EntityType.CONSTANT


# ── Fact ──────────────────────────────────────────────────────────────────────

def test_fact_default_not_negated():
    f = Fact(pred="tall", args=["e1"])
    assert f.negated is False


def test_fact_negated():
    f = Fact(pred="tall", args=["e1"], negated=True)
    assert f.negated is True


def test_fact_binary():
    f = Fact(pred="directed by", args=["c1", "c2"])
    assert len(f.args) == 2


# ── ProblemExtraction ─────────────────────────────────────────────────────────

def test_all_entities_deduplicates():
    """Entity appearing in two sentences is returned once."""
    shared = Entity(id="e1", surface="tree", entity_type=EntityType.EXISTENTIAL)
    s1 = SentenceExtraction(
        nl="A tree is tall.",
        entities=[shared],
        facts=[Fact(pred="tall", args=["e1"])],
        macro_template=MacroTemplate.GROUND_POSITIVE,
    )
    s2 = SentenceExtraction(
        nl="The tree grows.",
        entities=[shared],
        facts=[Fact(pred="grows", args=["e1"])],
        macro_template=MacroTemplate.GROUND_POSITIVE,
    )
    prob = ProblemExtraction(problem_id="p1", sentences=[s1, s2])
    assert len(prob.all_entities) == 1
    assert prob.all_entities[0].id == "e1"


def test_all_entities_multiple():
    s1 = _make_sentence(entity_id="e1", entity_surface="tree")
    s2 = _make_sentence(nl="Nancy runs.", entity_id="c1", entity_surface="nancy",
                        pred="runs", macro=MacroTemplate.GROUND_POSITIVE)
    prob = ProblemExtraction(problem_id="p2", sentences=[s1, s2])
    ids = {e.id for e in prob.all_entities}
    assert ids == {"e1", "c1"}


def test_all_facts():
    s1 = _make_sentence(pred="tall")
    s2 = _make_sentence(nl="It grows.", pred="grows")
    prob = ProblemExtraction(problem_id="p3", sentences=[s1, s2])
    preds = [f.pred for f in prob.all_facts]
    assert "tall" in preds
    assert "grows" in preds


# ── TestSuite ─────────────────────────────────────────────────────────────────

def test_test_suite_total():
    pos = [UnitTest(fol_string="exists x.Tall(x)", test_type="vocabulary", is_positive=True)]
    neg = [
        UnitTest(fol_string="exists x.Short(x)", test_type="contrastive", is_positive=False),
        UnitTest(fol_string="exists x.Old(x)", test_type="contrastive", is_positive=False),
    ]
    suite = TestSuite(problem_id="t1", positive_tests=pos, negative_tests=neg)
    assert suite.total_tests == 3


# ── VerificationResult ────────────────────────────────────────────────────────

def test_recall_rate_simple():
    vr = VerificationResult(
        candidate_fol="exists x.Tall(x)",
        syntax_valid=True,
        recall_passed=3,
        recall_total=4,
        precision_passed=2,
        precision_total=2,
        tier1_skips=1,
        tier2_skips=0,
        prover_calls=0,
    )
    assert vr.recall_rate == pytest.approx(0.75)


def test_recall_rate_with_partial_credit():
    vr = VerificationResult(
        candidate_fol="exists x.Tall(x)",
        syntax_valid=True,
        recall_passed=2,
        recall_total=4,
        precision_passed=2,
        precision_total=2,
        tier1_skips=0,
        tier2_skips=0,
        prover_calls=0,
        partial_credits={"test_0": 0.5, "test_1": 0.5},
    )
    # (2 full + 1.0 partial) / 4 = 0.75
    assert vr.recall_rate == pytest.approx(0.75)


def test_precision_rate_perfect():
    vr = VerificationResult(
        candidate_fol="x", syntax_valid=True,
        recall_passed=1, recall_total=1,
        precision_passed=3, precision_total=3,
        tier1_skips=0, tier2_skips=0, prover_calls=0,
    )
    assert vr.precision_rate == pytest.approx(1.0)


def test_precision_rate_zero_total():
    """No negative tests → precision defaults to 1.0."""
    vr = VerificationResult(
        candidate_fol="x", syntax_valid=True,
        recall_passed=1, recall_total=1,
        precision_passed=0, precision_total=0,
        tier1_skips=0, tier2_skips=0, prover_calls=0,
    )
    assert vr.precision_rate == pytest.approx(1.0)


def test_siv_score_f1():
    vr = VerificationResult(
        candidate_fol="x", syntax_valid=True,
        recall_passed=3, recall_total=4,   # recall = 0.75
        precision_passed=2, precision_total=2,  # precision = 1.0
        tier1_skips=0, tier2_skips=0, prover_calls=0,
    )
    expected = 2 * 0.75 * 1.0 / (0.75 + 1.0)
    assert vr.siv_score == pytest.approx(expected)


def test_siv_score_zero_both():
    vr = VerificationResult(
        candidate_fol="x", syntax_valid=False,
        recall_passed=0, recall_total=0,
        precision_passed=0, precision_total=0,
        tier1_skips=0, tier2_skips=0, prover_calls=0,
    )
    assert vr.siv_score == 0.0


# ── MacroTemplate ─────────────────────────────────────────────────────────────

def test_macro_template_values():
    assert MacroTemplate.TYPE_A.value == "universal_affirmative"
    assert MacroTemplate.TYPE_E.value == "universal_negative"
    assert MacroTemplate.TYPE_I.value == "existential_affirmative"
    assert MacroTemplate.TYPE_O.value == "existential_negative"
    assert MacroTemplate.GROUND_POSITIVE.value == "ground_positive"
    assert MacroTemplate.GROUND_NEGATIVE.value == "ground_negative"
    assert MacroTemplate.CONDITIONAL.value == "conditional"
    assert MacroTemplate.BICONDITIONAL.value == "biconditional"


# ── CompoundAnalysis ──────────────────────────────────────────────────────────

def test_compound_analysis_fields():
    ca = CompoundAnalysis(
        modifier="tall",
        noun="tree",
        wordnet_hit=False,
        pmi_score=0.3,
        is_proper_noun=False,
        dep_scope="nsubj",
        recommendation="SPLIT",
        reason="Low PMI; modifier targets subject entity.",
    )
    assert ca.recommendation == "SPLIT"
    assert ca.dep_scope == "nsubj"
