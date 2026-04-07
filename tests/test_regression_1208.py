"""
Regression harness for FOLIO Problem 1208.

This file is the anchor for the entire SIV refactor sequence. It hard-codes
the seven premises of FOLIO Problem 1208 exactly as described in section 5 of
refactor/SIV_REFACTOR_CONTEXT.md. Every subsequent task must leave these tests
passing (possibly with updated expected values when a bug is intentionally fixed).

Pre-existing test suite state before Task 01 started:
  - 105 passed, 0 failed (3 PytestCollectionWarning for TestSuite dataclass)
  - No failures to document. Clean baseline.
"""
from siv.schema import (
    Constant, Entity, EntityType, Fact, MacroTemplate,
    ProblemExtraction, SentenceExtraction,
)
from siv.compiler import compile_sentence_test_suite, compile_test_suite
from siv.verifier import verify


# ── Gold FOL strings (as a competent human would write them) ──────────────────

GOLD_FOLS = [
    # P1
    "all x.((Employee(x) & Schedule(x,meeting,customers)) -> AppearIn(x,company))",
    # P2
    "all x.((Employee(x) & HasLunch(x,company)) -> Schedule(x,meeting,customers))",
    # P3
    "all x.(Employee(x) -> ((HasLunch(x,company) | HasLunch(x,home)) & -(HasLunch(x,company) & HasLunch(x,home))))",
    # P4
    "all x.((Employee(x) & HasLunch(x,home)) -> Work(x,home))",
    # P5
    "all x.((Employee(x) & -In(x,homecountry)) -> Work(x,home))",
    # P6
    "all x.(Manager(x) -> -Work(x,home))",
    # P7
    "-((Manager(james) | AppearIn(james,company)) & -(Manager(james) & AppearIn(james,company)))",
]


# ── Problem builder ───────────────────────────────────────────────────────────

def build_problem_1208() -> ProblemExtraction:
    """
    Return a fresh ProblemExtraction for FOLIO Problem 1208.

    Each sentence is built with explicit Entity, Fact, Constant, and
    MacroTemplate values — no helper DSL. The structure mirrors section 5 of
    refactor/SIV_REFACTOR_CONTEXT.md exactly.
    """
    # P1: "All employees who schedule a meeting with their customers
    #       will go to the company building today."
    p1 = SentenceExtraction(
        nl="All employees who schedule a meeting with their customers will go to the company building today.",
        entities=[
            Entity(id="e1", surface="employees",       entity_type=EntityType.UNIVERSAL),
            Entity(id="e2", surface="meeting",         entity_type=EntityType.EXISTENTIAL),
            Entity(id="e3", surface="customers",       entity_type=EntityType.EXISTENTIAL),
            Entity(id="e4", surface="company building", entity_type=EntityType.EXISTENTIAL),
        ],
        facts=[
            Fact(pred="schedule", args=["e1", "e2"]),
            Fact(pred="with",     args=["e2", "e3"]),
            Fact(pred="go to",    args=["e1", "e4"]),
        ],
        macro_template=MacroTemplate.TYPE_A,
    )

    # P2: "Everyone who has lunch in the company building schedules meetings
    #       with their customers."
    p2 = SentenceExtraction(
        nl="Everyone who has lunch in the company building schedules meetings with their customers.",
        entities=[
            Entity(id="e1", surface="everyone",        entity_type=EntityType.UNIVERSAL),
            Entity(id="e2", surface="lunch",           entity_type=EntityType.EXISTENTIAL),
            Entity(id="e3", surface="company building", entity_type=EntityType.EXISTENTIAL),
            Entity(id="e4", surface="meetings",        entity_type=EntityType.EXISTENTIAL),
            Entity(id="e5", surface="customers",       entity_type=EntityType.EXISTENTIAL),
        ],
        facts=[
            Fact(pred="has",       args=["e1", "e2"]),
            Fact(pred="in",        args=["e2", "e3"]),
            Fact(pred="schedules", args=["e1", "e4"]),
            Fact(pred="with",      args=["e4", "e5"]),
        ],
        macro_template=MacroTemplate.TYPE_A,
    )

    # P3: "Employees have lunch either in the company building or at home."
    p3 = SentenceExtraction(
        nl="Employees have lunch either in the company building or at home.",
        entities=[
            Entity(id="e1", surface="employees",       entity_type=EntityType.UNIVERSAL),
            Entity(id="e2", surface="company building", entity_type=EntityType.EXISTENTIAL),
            Entity(id="e3", surface="home",            entity_type=EntityType.EXISTENTIAL),
        ],
        facts=[
            Fact(pred="have lunch", args=["e1", "e2"]),
            Fact(pred="have lunch", args=["e1", "e3"]),
        ],
        macro_template=MacroTemplate.TYPE_A,
    )

    # P4: "If an employee has lunch at home, they are working remotely from home."
    p4 = SentenceExtraction(
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

    # P5: "All employees who are in other countries work remotely from home."
    p5 = SentenceExtraction(
        nl="All employees who are in other countries work remotely from home.",
        entities=[
            Entity(id="e1", surface="employees",      entity_type=EntityType.UNIVERSAL),
            Entity(id="e2", surface="other countries", entity_type=EntityType.EXISTENTIAL),
            Entity(id="e3", surface="home",           entity_type=EntityType.EXISTENTIAL),
        ],
        facts=[
            Fact(pred="in",                args=["e1", "e2"]),
            Fact(pred="work remotely from", args=["e1", "e3"]),
        ],
        macro_template=MacroTemplate.TYPE_A,
    )

    # P6: "No managers work remotely from home."
    #     C1 schema violation: 1-arg predicate containing prepositions.
    p6 = SentenceExtraction(
        nl="No managers work remotely from home.",
        entities=[
            Entity(id="e1", surface="managers", entity_type=EntityType.UNIVERSAL),
        ],
        facts=[
            # Post-FIX-C1: P6 is now flagged as extraction_invalid — Tenet 2 violation.
            # "work remotely from home" is a 1-arg predicate containing preposition
            # "from" — the second argument should have been reified as a separate
            # entity and binary edge. See test_p6_extraction_invalid below.
            Fact(pred="work remotely from home", args=["e1"], negated=True),
        ],
        macro_template=MacroTemplate.TYPE_E,
    )

    # P7: "James will appear in the company today if and only if he is a manager."
    p7 = SentenceExtraction(
        nl="James will appear in the company today if and only if he is a manager.",
        constants=[
            Constant(id="james", surface="James"),
        ],
        entities=[
            Entity(id="e1", surface="company", entity_type=EntityType.EXISTENTIAL),
        ],
        facts=[
            Fact(pred="appear in", args=["james", "e1"]),
            Fact(pred="manager",   args=["james"]),
        ],
        macro_template=MacroTemplate.BICONDITIONAL,
    )

    return ProblemExtraction(
        problem_id="1208",
        sentences=[p1, p2, p3, p4, p5, p6, p7],
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_baseline_matches_diagnostic_trace():
    """
    Verify each Gold FOL against its sentence's compiled test suite and confirm
    the recall/precision totals match the pre-refactor diagnostic trace.

    These are the BROKEN baseline numbers — not what we want, but what the code
    currently produces. If these numbers change without a deliberate fix, a
    regression has been introduced.

    Expected (post-FIX-D1-D2):
      P1: recall_total=4,  recall_passed=0, precision_total=9   # Post-FIX-D1-D2: was 0, now 9  (3 strategies × 3 binary facts; deduped)
      P2: recall_total=6,  recall_passed=0, precision_total=12  # Post-FIX-D1-D2: was 0, now 12 (3 strategies × 4 binary facts; deduped)
      P3: recall_total=2,  recall_passed=0, precision_total=4   # Post-FIX-D1-D2: was 0, now 4  (swap+flip × 2 HaveLunch facts; cross-pred deduped)
      P4: recall_total=5,  recall_passed=0, precision_total=6   # Post-FIX-D1-D2: was 0, now 6  (3 strategies × 2 binary facts; 1 swap dup removed)
      P5: recall_total=2,  recall_passed=0, precision_total=6   # Post-FIX-D1-D2: was 0, now 6  (3 strategies × 2 binary facts)
      P6: recall_total=1,  recall_passed=0, precision_total=1   # Post-FIX-D1-D2: was 1, unchanged (1-arg negated; polarity flip only)
      P7: recall_total=4,  recall_passed=0, precision_total=3   # Post-FIX-D1-D2: was 1, now 3  (swap+flip+cross for appear_in binary; -Manager flip)
    """
    problem = build_problem_1208()

    # (recall_total, recall_passed, precision_total)
    expected = [
        (4, 0, 9),   # P1  Post-FIX-D1-D2: was 0, now 9
        (6, 0, 12),  # P2  Post-FIX-D1-D2: was 0, now 12
        (2, 0, 4),   # P3  Post-FIX-D1-D2: was 0, now 4
        (5, 0, 6),   # P4  Post-FIX-D1-D2: was 0, now 6
        (2, 0, 6),   # P5  Post-FIX-D1-D2: was 0, now 6
        (1, 0, 1),   # P6  Post-FIX-D1-D2: was 1, unchanged
        (4, 0, 3),   # P7  Post-FIX-D1-D2: was 1, now 3
    ]

    for idx, (sent, gold_fol, (exp_rt, exp_rp, exp_pt)) in enumerate(
        zip(problem.sentences, GOLD_FOLS, expected), start=1
    ):
        suite = compile_sentence_test_suite(sent, problem_id=f"1208_p{idx}")
        result = verify(gold_fol, suite, prover_timeout=1, strict_mode=False)

        assert result.recall_total == exp_rt, (
            f"P{idx} recall_total: got {result.recall_total}, expected {exp_rt}"
        )
        assert result.recall_passed == exp_rp, (
            f"P{idx} recall_passed: got {result.recall_passed}, expected {exp_rp}"
        )
        assert result.precision_total == exp_pt, (
            f"P{idx} precision_total: got {result.precision_total}, expected {exp_pt}"
        )


def test_p6_extraction_invalid():
    """
    Post-FIX-C1: P6 ("No managers work remotely from home") must be flagged as
    extraction_invalid because its sole fact 'work remotely from home(e1)' is a
    1-arg predicate containing the preposition 'from' — a Tenet 2 violation.

    # Post-FIX-C1: P6 is now flagged as extraction_invalid — Tenet 2 violation.
    """
    problem = build_problem_1208()
    p6 = problem.sentences[5]  # zero-indexed: P1=0 … P6=5
    suite = compile_sentence_test_suite(p6, problem_id="1208_p6_c1")

    assert suite.has_violations is True, (
        f"Expected suite.has_violations=True for P6; got violations={suite.violations}"
    )

    result = verify(GOLD_FOLS[5], suite, prover_timeout=1, strict_mode=False)

    assert result.extraction_invalid is True, (
        f"P6 expected extraction_invalid=True; got {result.extraction_invalid}"
    )
    assert result.siv_score == 0.0, (
        f"P6 expected siv_score=0.0; got {result.siv_score}"
    )
    assert len(result.schema_violations) >= 1, (
        f"P6 expected at least 1 schema_violation; got {result.schema_violations}"
    )
    assert result.schema_violations[0].violation_type == "prepositional_unary", (
        f"P6 expected prepositional_unary violation; got "
        f"{result.schema_violations[0].violation_type}"
    )


def test_final_state_siv_scores_per_premise():
    """
    Task 08: End-to-end regression on all seven premises of FOLIO Problem 1208.

    Asserts the exact post-refactor pipeline state: correct test counts, fix flags,
    and structural invariants. Failures here mean the pipeline has drifted from spec.

    Pre-refactor recall_total baselines (before Fix A suppressed vocabulary probes
    for universal-bound facts):
      P1=6, P2=8, P3=4, P4=4, P5=4, P6=1, P7=4

    Pre-refactor precision_total baselines (before Fix D1+D2 replaced antonym tests
    with structural perturbation tests; from test-file annotations):
      P1=0, P2=0, P3=0, P4=0, P5=0, P6=1, P7=1
    """
    from siv.scorer import aggregate_sentence_scores

    problem = build_problem_1208()

    results = []
    suites = []
    for idx, (sent, gold) in enumerate(zip(problem.sentences, GOLD_FOLS), 1):
        suite = compile_sentence_test_suite(sent, problem_id=f"1208_p{idx}")
        result = verify(gold, suite, prover_timeout=1, strict_mode=False)
        results.append(result)
        suites.append(suite)

    # ── P1: universal affirmative, no violations ──────────────────────────────
    r1 = results[0]
    # Fix A suppressed vocabulary probes for facts with a universal arg;
    # pre-refactor had 6 recall tests (4 now + 2 suppressed vocabulary tests).
    assert r1.extraction_invalid is False, "P1 must not be extraction_invalid"
    assert r1.recall_total > 0,           "P1 must have at least one recall test"
    assert r1.recall_total < 6,           "P1 recall_total must be < pre-refactor baseline of 6 (Fix A)"
    # Fix D1+D2: in-problem perturbation tests replaced vacuous antonym tests.
    # Pre-refactor baseline was 0 precision tests for binary facts.
    assert r1.precision_total > 0,        "P1 must have at least one precision test (Fix D1+D2)"

    # ── P2: universal affirmative ─────────────────────────────────────────────
    r2 = results[1]
    assert r2.extraction_invalid is False
    assert r2.recall_total > 0
    assert r2.recall_total < 8,           "P2 recall_total must be < pre-refactor baseline of 8 (Fix A)"
    assert r2.precision_total > 0,        "P2 must have precision tests (Fix D1+D2)"

    # ── P3: universal affirmative (XOR disjunction — flattened per Tenet 3) ──
    r3 = results[2]
    assert r3.extraction_invalid is False
    assert r3.recall_total > 0
    assert r3.recall_total < 4,           "P3 recall_total must be < pre-refactor baseline of 4 (Fix A)"
    assert r3.precision_total > 0,        "P3 must have precision tests (Fix D1+D2)"

    # ── P4: conditional with binary facts ─────────────────────────────────────
    r4 = results[3]
    s4 = suites[3]
    assert r4.extraction_invalid is False
    # Fix G1: CONDITIONAL branch must accept binary facts and emit an entailment test.
    entailment_types = [t.test_type for t in s4.positive_tests]
    assert "entailment" in entailment_types, (
        f"P4 must contain at least one entailment-type test (Fix G1); got {entailment_types}"
    )
    assert r4.precision_total > 0,        "P4 must have precision tests (Fix D1+D2)"

    # ── P5: universal affirmative ─────────────────────────────────────────────
    r5 = results[4]
    assert r5.extraction_invalid is False
    assert r5.recall_total > 0
    assert r5.recall_total < 4,           "P5 recall_total must be < pre-refactor baseline of 4 (Fix A)"
    assert r5.precision_total > 0,        "P5 must have precision tests (Fix D1+D2)"

    # ── P6: extraction_invalid (C1 Neo-Davidsonian violation) ────────────────
    r6 = results[5]
    # FIX C1: "work remotely from home" is a 1-arg predicate containing "from".
    assert r6.extraction_invalid is True, (
        f"P6 must be extraction_invalid; got extraction_invalid={r6.extraction_invalid}"
    )
    assert r6.siv_score == 0.0, (
        f"P6 siv_score must be 0.0; got {r6.siv_score}"
    )
    assert len(r6.schema_violations) >= 1, (
        f"P6 must carry at least one schema_violation; got {r6.schema_violations}"
    )
    assert r6.schema_violations[0].violation_type == "prepositional_unary", (
        f"P6 violation_type must be 'prepositional_unary'; "
        f"got {r6.schema_violations[0].violation_type}"
    )
    assert r6.prover_calls == 0, (
        f"P6 must make zero prover calls (extraction_invalid short-circuit); "
        f"got prover_calls={r6.prover_calls}"
    )

    # ── P7: biconditional with constant ──────────────────────────────────────
    r7 = results[6]
    assert r7.extraction_invalid is False
    # Fix D1+D2: the binary appear_in fact must generate polarity-flip and
    # argument-swap precision tests.  Pre-refactor baseline was 1.
    assert r7.precision_total >= 1, (
        f"P7 must have at least one precision test; got {r7.precision_total}"
    )
    assert r7.precision_total > 1, (
        f"P7 precision_total must exceed pre-refactor baseline of 1 (Fix D1+D2); "
        f"got {r7.precision_total}"
    )

    # ── Aggregate ─────────────────────────────────────────────────────────────
    agg = aggregate_sentence_scores(results)
    assert agg["num_invalid"] == 1, (
        f"Exactly one premise (P6) should be extraction_invalid; "
        f"got num_invalid={agg['num_invalid']}"
    )
    # P6 (siv_score=0) is included in the denominator → aggregate SIV is 0.
    assert agg["siv"] == 0.0, (
        f"Aggregate SIV must be 0.0 (all premises score 0 against this gold); "
        f"got {agg['siv']}"
    )


def test_partial_credit_has_no_canonicalization():
    """
    Trip-wire: confirm that siv.partial_credit has NOT re-introduced any
    Tenet-1-violating normalization. If any of these names appear in the
    module namespace, a later task silently introduced lemmatization/stemming.
    """
    import siv.partial_credit as pc

    forbidden = ["canonicalize_predicate", "canonicalize_set", "_light_stem"]
    for name in forbidden:
        assert not hasattr(pc, name), (
            f"Tenet-1 violation: siv.partial_credit exposes '{name}'. "
            "Remove it before proceeding."
        )
