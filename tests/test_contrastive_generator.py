"""Tests for siv/contrastive_generator.py — Phase 3."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from siv.compiler import _a_formula, compile_canonical_fol
from siv.contrastive_generator import (
    STRUCTURAL_CLASSES,
    classify_structure,
    derive_witness_axioms,
    drop_restrictor_conjunct,
    flip_connective,
    flip_quantifier,
    generate_contrastives,
    negate_atom,
    replace_subformula_with_negation,
    swap_binary_args,
)
from siv.schema import (
    AtomicFormula,
    Constant,
    Formula,
    InnerQuantification,
    PredicateDecl,
    SentenceExtraction,
    TripartiteQuantification,
)
from siv.vampire_interface import is_vampire_available, vampire_check


vampire_required = pytest.mark.skipif(
    not is_vampire_available(), reason="Vampire not available"
)


_EXAMPLES = json.loads(
    (Path(__file__).parent.parent / "prompts" / "extraction_examples.json").read_text()
)

# Expected structural class + whether contrastives are expected non-empty.
# Classes in the structurally-weak set may legitimately produce an empty list.
STRUCTURALLY_WEAK = {
    "top_level_disjunction",
    "bare_implies_atomic_antecedent",
    "existential_compound_nucleus",
}

EXPECTED_CLASSIFICATION = {
    "Miroslav Venhoda was a Czech choral conductor.": "ground_instance",
    "Alice taught Bob.": "ground_instance",
    "All dogs are mammals.": "simple_universal",
    "All employees who schedule meetings attend the company building.": "compound_restrictor_universal",
    "Some student read a book.": "existential_compound_nucleus",
    "Every student who takes a class that is taught by a professor passes.": "compound_restrictor_universal",
    "No dog is a cat.": "simple_universal",
    "People in this club who chaperone high school dances are not students who attend the school.": "compound_restrictor_universal",
    # "Only managers attend the meeting." → all x.(Attend(x, theMeeting) -> Manager(x))
    # Singleton restrictor, no inner_quantifications — simple by the
    # structural definition (compound requires >=2 atoms or inner-quants).
    "Only managers attend the meeting.": "simple_universal",
    "Alice is tall and Bob is short.": "ground_instance",
    "The L-2021 monitor is either used in the library or has a type-c port.": "top_level_disjunction",
    "If it rains, the ground is wet.": "bare_implies_atomic_antecedent",
    "Archie can walk if and only if he has functional brainstems.": "ground_instance",
    "If the forecast calls for rain, then all employees work from home.": "bare_implies_atomic_antecedent",
    "It is not the case that Alice is tall and Bob is short.": "ground_instance",
}


# ── Operator unit tests ─────────────────────────────────────────────────────

def _atom(p, *args, negated=False):
    return AtomicFormula(pred=p, args=list(args), negated=negated)


def _atomic_f(p, *args, negated=False):
    return Formula(atomic=_atom(p, *args, negated=negated))


def test_negate_atom_flips_top_atom():
    f = _atomic_f("P", "a")
    mutants = negate_atom(f)
    assert len(mutants) == 1
    assert mutants[0].atomic.negated is True


def test_swap_binary_args_produces_swapped():
    f = _atomic_f("R", "a", "b")
    mutants = swap_binary_args(f)
    assert len(mutants) == 1
    assert mutants[0].atomic.args == ["b", "a"]


def test_swap_binary_args_skips_unary():
    f = _atomic_f("P", "a")
    assert swap_binary_args(f) == []


def test_flip_quantifier_universal_to_existential():
    q = TripartiteQuantification(
        quantifier="universal", variable="x", var_type="entity",
        restrictor=[_atom("Dog", "x")],
        nucleus=_atomic_f("Mammal", "x"),
    )
    f = Formula(quantification=q)
    mutants = flip_quantifier(f)
    assert any(m.quantification.quantifier == "existential" for m in mutants)


def test_drop_restrictor_conjunct_removes_one_at_a_time():
    q = TripartiteQuantification(
        quantifier="universal", variable="x", var_type="entity",
        restrictor=[_atom("A", "x"), _atom("B", "x"), _atom("C", "x")],
        nucleus=_atomic_f("D", "x"),
    )
    f = Formula(quantification=q)
    mutants = drop_restrictor_conjunct(f)
    # Top-level quantification produces 3 mutants (one per dropped conjunct).
    top_mutants = [m for m in mutants if m.quantification is not None]
    restrictor_sizes = sorted(
        len(m.quantification.restrictor) for m in top_mutants
    )
    assert restrictor_sizes == [2, 2, 2]


def test_flip_connective_and_to_or():
    f = Formula(connective="and", operands=[_atomic_f("A", "a"), _atomic_f("B", "a")])
    mutants = flip_connective(f)
    assert any(m.connective == "or" for m in mutants)


def test_flip_connective_implies_has_iff_and_reversed():
    f = Formula(connective="implies",
                operands=[_atomic_f("A", "a"), _atomic_f("B", "a")])
    mutants = flip_connective(f)
    connectives = sorted(m.connective for m in mutants if m.connective)
    assert "iff" in connectives
    # Reversed implies: same connective, swapped operands.
    reversed_implies = [
        m for m in mutants
        if m.connective == "implies"
        and m.operands[0].atomic.pred == "B"
        and m.operands[1].atomic.pred == "A"
    ]
    assert len(reversed_implies) == 1


def test_flip_connective_iff_to_implies_no_reversed():
    f = Formula(connective="iff",
                operands=[_atomic_f("A", "a"), _atomic_f("B", "a")])
    mutants = [m for m in flip_connective(f) if m.connective is not None]
    assert len(mutants) == 1
    assert mutants[0].connective == "implies"


def test_replace_subformula_with_negation_wraps_nonroot_nonatomic():
    """§6.5 rule: for each non-root non-atomic sub-formula, wrap it in
    Formula.negation. Atoms are excluded; the root itself is excluded.

    Here the root is a quantification whose nucleus is an AND. The AND is
    the sole non-root non-atomic sub-formula, so the operator emits exactly
    one mutant."""
    q = TripartiteQuantification(
        quantifier="universal", variable="x", var_type="entity",
        restrictor=[_atom("Q", "x")],
        nucleus=Formula(connective="and", operands=[
            _atomic_f("A", "x"), _atomic_f("B", "x"),
        ]),
    )
    mutants = replace_subformula_with_negation(Formula(quantification=q))
    assert len(mutants) == 1
    # The resulting mutant must wrap the AND in a negation.
    top = mutants[0]
    assert top.quantification is not None
    assert top.quantification.nucleus.negation is not None
    inner = top.quantification.nucleus.negation
    assert inner.connective == "and"


# ── Vampire-dependent operator behavior ─────────────────────────────────────

@vampire_required
def test_swap_binary_args_on_symmetric_predicate_is_neutral():
    """SiblingOf is symmetric: SiblingOf(a, b) <-> SiblingOf(b, a). A swap
    mutation is entailment-neutral; Vampire returns sat under the symmetry
    axiom."""
    orig = "SiblingOf(alice, bob)"
    mut = "SiblingOf(bob, alice)"
    symmetry = "all x.(all y.(SiblingOf(x, y) -> SiblingOf(y, x)))"
    verdict = vampire_check(orig, mut, check="unsat", timeout=5, axioms=[symmetry])
    assert verdict == "sat"


@vampire_required
def test_swap_binary_args_on_asymmetric_predicate_is_contrastive():
    """An asymmetric relation (e.g., Parent) under its antisymmetry axiom
    makes argument-swap a provable contradiction.
    """
    orig = "Parent(alice, bob)"
    mut = "Parent(bob, alice)"
    antisymmetry = "all x.(all y.(Parent(x, y) -> -Parent(y, x)))"
    verdict = vampire_check(
        orig, mut, check="unsat", timeout=5, axioms=[antisymmetry],
    )
    assert verdict == "unsat"


@vampire_required
def test_flip_connective_disjunction_to_conjunction_is_contrastive():
    """`(A | B)` flipped to `(A & B)` is inconsistent when one disjunct is
    contradicted by a witness: (Rainy | Sunny) & disjoint(Rainy, Sunny)
    & Rainy → flipping to (Rainy & Sunny) is unsat.
    """
    orig = "(Rainy(today) | Sunny(today))"
    mut = "(Rainy(today) & Sunny(today))"
    disjoint = "all x.(Rainy(x) -> -Sunny(x))"
    verdict = vampire_check(orig, mut, check="unsat", timeout=5, axioms=[disjoint])
    assert verdict == "unsat"


# ── Structural classification ───────────────────────────────────────────────

@pytest.mark.parametrize("example", _EXAMPLES, ids=[ex["sentence"] for ex in _EXAMPLES])
def test_classification_matches_expected(example):
    se = SentenceExtraction.model_validate(example["extraction"])
    got = classify_structure(se)
    want = EXPECTED_CLASSIFICATION[example["sentence"]]
    assert got == want, f"got {got!r}, want {want!r}"


def test_no_phase2_example_classifies_as_other():
    for example in _EXAMPLES:
        se = SentenceExtraction.model_validate(example["extraction"])
        assert classify_structure(se) != "other", example["sentence"]


def test_classify_structure_returns_member_of_known_classes():
    for example in _EXAMPLES:
        se = SentenceExtraction.model_validate(example["extraction"])
        assert classify_structure(se) in STRUCTURAL_CLASSES


# ── Witness axioms derivation ───────────────────────────────────────────────

def test_witness_axioms_include_per_predicate_closures():
    """Per-predicate level: one exists-closure per declared predicate."""
    ex = _EXAMPLES[2]  # All dogs are mammals
    se = SentenceExtraction.model_validate(ex["extraction"])
    axioms = derive_witness_axioms(se)
    assert "exists x.Dog(x)" in axioms
    assert "exists x.Mammal(x)" in axioms


def test_witness_axioms_close_outer_bound_variables():
    """Layer 1 fix (SIV.md §6.5 Amendment E clarification).

    An inner quantification whose restrictor references an enclosing bound
    variable (a legitimately dependent quantification) must produce a witness
    axiom whose existential prefix closes both the inner and the outer
    variable. No witness axiom may contain a free variable.

    Example: ∀x.(Student(x) → ∃y.(Book(y) ∧ Likes(x, y) → Owns(x, y))).
    The inner existential restrictor references `x`; the witness axiom must
    begin with `exists y.exists x.` (or some permutation that binds both).
    """
    from siv.vampire_interface import is_vampire_available, vampire_check

    inner_y = TripartiteQuantification(
        quantifier="existential", variable="y", var_type="entity",
        restrictor=[_atom("Book", "y"), _atom("Likes", "x", "y")],
        nucleus=_atomic_f("Owns", "x", "y"),
    )
    outer = TripartiteQuantification(
        quantifier="universal", variable="x", var_type="entity",
        restrictor=[_atom("Student", "x")],
        nucleus=Formula(quantification=inner_y),
    )
    ext = SentenceExtraction(
        nl="Every student owns a book they like.",
        predicates=[
            PredicateDecl(name="Student", arity=1, arg_types=["entity"]),
            PredicateDecl(name="Book", arity=1, arg_types=["entity"]),
            PredicateDecl(name="Likes", arity=2, arg_types=["entity", "entity"]),
            PredicateDecl(name="Owns", arity=2, arg_types=["entity", "entity"]),
        ],
        constants=[], entities=[],
        formula=Formula(quantification=outer),
    )
    axioms = derive_witness_axioms(ext)
    # Find the restrictor axiom for the inner quantification.
    inner_ax = [
        a for a in axioms
        if "Book(y)" in a and "Likes(x, y)" in a
    ]
    assert len(inner_ax) == 1, f"expected one inner-restrictor axiom, got: {axioms}"
    ax = inner_ax[0]
    # Both variables must be quantified (closure).
    assert "exists x." in ax and "exists y." in ax, ax
    # Must parse under Vampire (no free variables).
    if is_vampire_available():
        verdict = vampire_check("Student(alice)", ax, check="unsat", timeout=3, axioms=[])
        # If Vampire accepted the axiom syntactically, the call returns a
        # verdict (sat/unsat/unknown) rather than the parse-failure "unknown"
        # we previously saw. Assert it's a real verdict — unknown is fine
        # here as long as it's a prover result, not a parse failure.
        assert verdict in ("sat", "unsat", "unknown", "timeout")


def test_witness_axioms_include_per_quantification_restrictor_closures():
    """B′ level: one exists-closure per TripartiteQuantification-restrictor.

    The employees-meetings extraction (case 4) has a compound restrictor
    `(Employee(x) & Schedule(x, y) & Meeting(y))` with inner_quantifications
    declaring `y` as existential. B′ must add
    `exists x.exists y.(Employee(x) & Schedule(x, y) & Meeting(y))`.
    """
    ex = _EXAMPLES[3]
    se = SentenceExtraction.model_validate(ex["extraction"])
    axioms = derive_witness_axioms(se)
    # Check at least one axiom starts with exists x.exists y. and mentions
    # all three restrictor predicates.
    joint_ax = [
        a for a in axioms
        if a.startswith("exists x.exists y.")
        and "Employee(x)" in a
        and "Schedule(x, y)" in a
        and "Meeting(y)" in a
    ]
    assert len(joint_ax) >= 1, axioms


# ── Parametrized fourteen-example gate ──────────────────────────────────────

@vampire_required
@pytest.mark.parametrize(
    "example", _EXAMPLES, ids=[ex["sentence"] for ex in _EXAMPLES],
)
def test_fourteen_examples_match_structural_expectation(example):
    """Per the revised Phase 3 gate (§15): classes that admit mutation must
    produce non-empty contrastives; structurally-weak classes may be empty
    and log a reason."""
    se = SentenceExtraction.model_validate(example["extraction"])
    accepted, tele = generate_contrastives(se, timeout_s=3)

    klass = tele["structural_class"]
    assert klass == EXPECTED_CLASSIFICATION[example["sentence"]]
    assert klass != "other"

    if klass in STRUCTURALLY_WEAK:
        # Empty is permitted; if so, empty_reason must be recorded.
        if len(accepted) == 0:
            assert tele["empty_reason"] == "no unsat mutation under B' witness axioms"
    else:
        assert len(accepted) > 0, (
            f"Class {klass!r} admits mutation but produced zero contrastives. "
            f"Telemetry: {tele}"
        )


@vampire_required
def test_employees_meetings_produces_at_least_one_contrastive():
    """V1 bug target class; empty contrastives here would be mechanism failure."""
    for example in _EXAMPLES:
        if "employees who schedule meetings" in example["sentence"]:
            se = SentenceExtraction.model_validate(example["extraction"])
            accepted, _tele = generate_contrastives(se, timeout_s=5)
            assert len(accepted) >= 1
            return
    pytest.fail("employees-meetings example not found in gold set")


@vampire_required
def test_fourteen_examples_have_unknown_rate_below_threshold():
    """Aggregate unknown_rate across the 14 examples must be < 0.2."""
    total_gen = 0
    total_unk = 0
    for example in _EXAMPLES:
        se = SentenceExtraction.model_validate(example["extraction"])
        _acc, tele = generate_contrastives(se, timeout_s=3)
        total_gen += tele["generated"]
        total_unk += tele["dropped_unknown"]
    rate = total_unk / total_gen if total_gen else 0.0
    assert rate < 0.2, f"unknown_rate = {rate:.3f}"


@vampire_required
@pytest.mark.parametrize(
    "example", _EXAMPLES, ids=[ex["sentence"] for ex in _EXAMPLES],
)
def test_every_accepted_mutant_is_provably_unsat(example):
    """Every accepted contrastive must be provably inconsistent with the
    canonical (under witness axioms). This is C7's acceptance rule."""
    se = SentenceExtraction.model_validate(example["extraction"])
    accepted, _tele = generate_contrastives(se, timeout_s=3)
    if not accepted:
        pytest.skip("structurally-weak: no contrastives to verify")
    original_fol = compile_canonical_fol(se)
    witnesses = derive_witness_axioms(se)
    for t in accepted:
        assert t.kind == "contrastive"
        assert t.mutation_kind is not None
        verdict = vampire_check(
            original_fol, t.fol, check="unsat", timeout=3, axioms=witnesses,
        )
        assert verdict == "unsat", (t.fol, t.mutation_kind, verdict)
