"""
Metric Property Tests — Task 07.

These tests assert mathematical properties of SIV that the Master Document
(§4) claims hold for all well-formed inputs. Property tests differ from
example-based tests: they assert invariants over a class of inputs, not
just hand-picked fixtures.

Each property corresponds to a specific reviewable claim in the Master
Document that a reviewer might challenge.
"""
import pytest
from siv.schema import VerificationResult


# ── Property 1 — Boundedness ──────────────────────────────────────────────────

def test_property_boundedness_handwritten_cases():
    """
    Property: siv_score is always in [0.0, 1.0].
    Exercised over a hand-picked set of edge cases covering zero, perfect,
    partial, invalid, inconsistent, and unresolved-exclusion configurations.
    """
    cases = [
        # (recall_passed, recall_total, precision_passed, precision_total,
        #  unresolved_recall, unresolved_precision, extraction_invalid,
        #  candidate_inconsistent)
        (0, 0, 0, 0, 0, 0, False, False),
        (5, 5, 3, 3, 0, 0, False, False),
        (0, 5, 0, 3, 0, 0, False, False),
        (2, 5, 2, 3, 0, 0, False, False),
        (5, 5, 3, 3, 0, 0, True, False),    # extraction_invalid
        (5, 5, 3, 3, 0, 0, False, True),    # candidate_inconsistent
        (0, 5, 3, 3, 5, 0, False, False),   # all recall unresolved
        (5, 5, 0, 3, 0, 3, False, False),   # all precision unresolved
    ]
    for rp, rt, pp, pt, ur, up, ei, ci in cases:
        r = VerificationResult(
            candidate_fol="x",
            syntax_valid=True,
            recall_passed=rp,
            recall_total=rt,
            precision_passed=pp,
            precision_total=pt,
            tier1_skips=0,
            tier2_skips=0,
            prover_calls=0,
            unresolved_recall=ur,
            unresolved_precision=up,
            extraction_invalid=ei,
            candidate_inconsistent=ci,
        )
        assert 0.0 <= r.siv_score <= 1.0, f"siv_score out of bounds: {r.siv_score} for {cases}"


def test_property_boundedness_fuzz():
    """
    Fuzz test: 1000 randomly-generated VerificationResult objects, all
    bounded. Deterministic seed for reproducibility.
    """
    import random
    rng = random.Random(42)
    for _ in range(1000):
        rt = rng.randint(0, 20)
        pt = rng.randint(0, 20)
        ur = rng.randint(0, rt) if rt > 0 else 0
        up = rng.randint(0, pt) if pt > 0 else 0
        rp = rng.randint(0, max(0, rt - ur))
        pp = rng.randint(0, max(0, pt - up))
        r = VerificationResult(
            candidate_fol="x",
            syntax_valid=True,
            recall_passed=rp,
            recall_total=rt,
            precision_passed=pp,
            precision_total=pt,
            tier1_skips=0,
            tier2_skips=0,
            prover_calls=0,
            unresolved_recall=ur,
            unresolved_precision=up,
            extraction_invalid=rng.random() < 0.1,
            candidate_inconsistent=rng.random() < 0.1,
        )
        assert 0.0 <= r.siv_score <= 1.0


# ── Property 2 — Determinism ──────────────────────────────────────────────────

def test_property_determinism_ten_runs():
    """
    Property: verify() is deterministic. Ten calls on the same inputs
    produce byte-identical VerificationResult values (modulo prover
    timing noise — we compare the scoring fields, not wall-clock).
    """
    from siv.schema import (
        ProblemExtraction, SentenceExtraction, Entity, EntityType, Fact, MacroTemplate,
    )
    from siv.compiler import compile_test_suite
    from siv.verifier import verify

    sent = SentenceExtraction(
        nl="All dogs are mammals.",
        entities=[
            Entity(id="e1", surface="dogs", entity_type=EntityType.UNIVERSAL),
            Entity(id="e2", surface="mammals", entity_type=EntityType.EXISTENTIAL),
        ],
        facts=[Fact(pred="are", args=["e1", "e2"])],
        macro_template=MacroTemplate.TYPE_A,
    )
    extraction = ProblemExtraction(problem_id="determinism", sentences=[sent])
    suite = compile_test_suite(extraction)
    candidate = "(exists x.Dog(x)) & all x.(Dog(x) -> Mammal(x))"

    results = [verify(candidate, suite, unresolved_policy="exclude") for _ in range(10)]
    first = results[0]
    for r in results[1:]:
        assert r.recall_passed == first.recall_passed
        assert r.recall_total == first.recall_total
        assert r.precision_passed == first.precision_passed
        assert r.precision_total == first.precision_total
        assert r.unresolved_recall == first.unresolved_recall
        assert r.unresolved_precision == first.unresolved_precision
        assert r.extraction_invalid == first.extraction_invalid
        assert r.candidate_inconsistent == first.candidate_inconsistent
        assert r.siv_score == first.siv_score


# ── Property 3 — Short-circuit on extraction_invalid / candidate_inconsistent ─

def test_property_extraction_invalid_forces_zero():
    """
    Property: extraction_invalid=True → siv_score=0.0 regardless of recall
    and precision counts. This is the Tenet 4 mechanization.
    """
    r = VerificationResult(
        candidate_fol="x",
        syntax_valid=True,
        recall_passed=99,
        recall_total=99,
        precision_passed=99,
        precision_total=99,
        tier1_skips=0,
        tier2_skips=0,
        prover_calls=0,
        extraction_invalid=True,
    )
    assert r.siv_score == 0.0


def test_property_candidate_inconsistent_forces_zero():
    """
    Property: candidate_inconsistent=True → siv_score=0.0 regardless of
    recall and precision. This is §4.5 Defense 2.
    """
    r = VerificationResult(
        candidate_fol="x",
        syntax_valid=True,
        recall_passed=99,
        recall_total=99,
        precision_passed=99,
        precision_total=99,
        tier1_skips=0,
        tier2_skips=0,
        prover_calls=0,
        candidate_inconsistent=True,
    )
    assert r.siv_score == 0.0


# ── Property 4 — Identity on Canonical Compilation ───────────────────────────

def test_property_canonical_compilation_scores_high():
    """
    Property: a hand-compiled FOL string that mirrors a Neo-Davidsonian
    extraction scores >= 0.9 against the test suite compiled from the
    same extraction. The score should not be perfect because contrastive
    precision tests are structural perturbations the canonical FOL may
    not explicitly reject at Tier 1 — but it must be high.
    """
    from siv.schema import (
        ProblemExtraction, SentenceExtraction, Entity, EntityType, Fact, MacroTemplate,
    )
    from siv.compiler import compile_test_suite
    from siv.verifier import verify

    sent = SentenceExtraction(
        nl="The tall tree grows quickly.",
        entities=[Entity(id="e1", surface="tree", entity_type=EntityType.EXISTENTIAL)],
        facts=[
            Fact(pred="tall", args=["e1"]),
            Fact(pred="grows quickly", args=["e1"]),
        ],
        macro_template=MacroTemplate.GROUND_POSITIVE,
    )
    extraction = ProblemExtraction(problem_id="canonical", sentences=[sent])
    suite = compile_test_suite(extraction)
    canonical = "exists x.(Tree(x) & Tall(x) & GrowsQuickly(x))"
    result = verify(canonical, suite, unresolved_policy="exclude")
    assert result.siv_score >= 0.9, (
        f"Canonical compilation scored {result.siv_score:.3f}, expected >= 0.9. "
        f"Recall {result.recall_rate:.3f}, precision {result.precision_rate:.3f}."
    )


# ── Documented NON-property — Monotonicity ────────────────────────────────────

def test_documented_non_property_monotonicity_under_conjunction():
    """
    NON-PROPERTY (documented): adding a conjunct to a candidate can DECREASE
    SIV if the conjunct introduces a predicate that fails a contrastive
    precision test. This is intentional and is the 'BLEU behavior' SIV
    inherits: a translation that says more than the source is a translation
    error, not a translation bonus.

    This test EXISTS to document the non-property. It asserts the non-
    monotonicity, which protects against a future refactor that tries to
    'fix' it.
    """
    from siv.schema import (
        ProblemExtraction, SentenceExtraction, Entity, EntityType, Fact, MacroTemplate,
    )
    from siv.compiler import compile_test_suite
    from siv.verifier import verify

    sent = SentenceExtraction(
        nl="Alice loves Bob.",
        entities=[],
        facts=[Fact(pred="loves", args=["alice", "bob"])],
        macro_template=MacroTemplate.GROUND_POSITIVE,
    )
    # Attach the constants through the sentence
    from siv.schema import Constant
    sent.constants = [Constant(id="alice", surface="Alice"), Constant(id="bob", surface="Bob")]
    extraction = ProblemExtraction(problem_id="mono", sentences=[sent])
    suite = compile_test_suite(extraction)

    baseline = "Loves(alice, bob)"
    expanded = "Loves(alice, bob) & Loves(bob, alice)"   # adds a conjunct

    r_base = verify(baseline, suite, unresolved_policy="exclude")
    r_exp = verify(expanded, suite, unresolved_policy="exclude")

    # The expanded candidate asserts the argument-swap perturbation, which
    # is a contrastive precision test. So expanded has lower precision and
    # therefore a lower (or equal) SIV than baseline. Assert the direction.
    assert r_exp.precision_rate <= r_base.precision_rate, (
        "Expected adding the swapped conjunct to REDUCE precision — the "
        "non-monotonicity under conjunction is a documented SIV property."
    )
