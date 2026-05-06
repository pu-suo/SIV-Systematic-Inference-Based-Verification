"""
Contrastive generator (SIV.md §6.5, C7).

Produces candidate negative (contrastive) unit tests by mutating a
``SentenceExtraction``'s formula tree with the registered operators, then
filters each mutant through a three-check Vampire protocol:

A. ``unsat(gold ∧ mutant)`` under witness axioms. If unsat, the mutant is
   ``incompatible`` (mutually inconsistent with gold) — admit.
B. ``entails(mutant, gold)``. Must be ``unsat`` (mutant ⊨ gold).
C. ``entails(gold, mutant)``. Must be ``sat`` (gold ⊭ mutant).

If A is sat AND B is unsat AND C is sat, the mutant is *strictly stronger*
than gold (it adds content gold doesn't entail) — admit. All other
combinations (equivalent, strictly weaker, independent, or any
timeout/unknown) are dropped.

Relaxing the gate to admit strictly-stronger mutants lets operators like
``drop_restrictor_conjunct``, ``converse``, and ``scope_swap`` produce
useful contrastives where the prior unsat-only gate dropped them silently.
"""
from __future__ import annotations

import os
from typing import Callable, Dict, List, Optional, Tuple

from siv.compiler import _a_formula
from siv.schema import (
    AtomicFormula,
    Formula,
    SchemaViolation,
    SentenceExtraction,
    TripartiteQuantification,
    UnitTest,
)
from siv.vampire_interface import vampire_check

# Each mutation operator returns a list of (mutated Formula, mutation_kind).
MutantList = List[Tuple[Formula, str]]


def derive_witness_axioms(extraction: SentenceExtraction) -> List[str]:
    """Derive existential-closure axioms from the extraction (§6.5).

    Two levels (complete specification per SIV.md §6.5):

    Per-predicate. For each ``PredicateDecl`` with arity 1 and name ``P``,
    emit ``exists x.P(x)``. For each with arity 2 and name ``R``, emit
    ``exists x.exists y.R(x, y)``.

    Per-quantification-restrictor (B′). For each ``TripartiteQuantification``
    node in the formula tree with a non-empty restrictor, bound variable
    ``x``, and inner-quantification variables ``y_1..y_n``, emit
    ``exists x.exists y_1. ... exists y_n.(⋀restrictor)``. This closes the
    empty-restrictor-combination escape on compound universal conditionals.

    Formalizes the existential import that natural-language restrictor
    domains carry (Barwise & Cooper 1981). Used uniformly in the generator
    (§6.5), scorer (§6.6), and C9b.
    """
    axioms: List[str] = []

    for decl in extraction.predicates:
        if decl.name == "__eq__":
            continue  # Built-in equality needs no witness axiom
        if decl.arity == 1:
            axioms.append(f"exists x.{decl.name}(x)")
        elif decl.arity == 2:
            axioms.append(f"exists x.exists y.{decl.name}(x, y)")
        else:
            vars = [f"v{i}" for i in range(decl.arity)]
            prefix = "".join(f"exists {v}." for v in vars)
            axioms.append(f"{prefix}{decl.name}({', '.join(vars)})")

    # Build an ancestor-scope map keyed by each TripartiteQuantification,
    # listing every enclosing quantifier's bound variable (outer + outer
    # inner-quantifications). Restrictor free variables that are neither
    # `q.variable` nor declared in `q.inner_quantifications` must be bound
    # by some enclosing quantification; their names are prepended to the
    # existential prefix so the axiom is closed.
    enclosing = _collect_enclosing(extraction.formula)

    for q in _walk_quantifications(extraction.formula):
        if not q.restrictor:
            continue
        own_binders = [q.variable] + [iq.variable for iq in q.inner_quantifications]
        free_vars = _restrictor_free_vars(q, extraction)
        extra = [v for v in free_vars if v not in own_binders]
        for v in extra:
            # A free variable not bound by any enclosing quantification would
            # indicate a schema violation that validate_extraction should
            # have caught (C3). Assert rather than silently skipping.
            assert v in enclosing[id(q)], (
                f"witness axiom derivation: restrictor of {q.quantifier}({q.variable!r}) "
                f"references {v!r} which is not bound by any enclosing quantification "
                f"— should have been caught by validate_extraction"
            )
        closure_vars = own_binders + extra
        conj_parts = [_compile_atom(a) for a in q.restrictor]
        conj = conj_parts[0] if len(conj_parts) == 1 else "(" + " & ".join(conj_parts) + ")"
        prefix = "".join(f"exists {v}." for v in closure_vars)
        axioms.append(f"{prefix}{conj}")

    return axioms


def _restrictor_free_vars(q: "TripartiteQuantification", extraction: SentenceExtraction) -> List[str]:
    """Return restrictor-atom argument names that are not declared
    constant/entity ids — i.e., variable names — deduplicated in first-seen
    order."""
    ids = {c.id for c in extraction.constants} | {e.id for e in extraction.entities}
    seen: List[str] = []
    for atom in q.restrictor:
        for a in atom.args:
            if a in ids:
                continue
            if a in seen:
                continue
            seen.append(a)
    return seen


def _collect_enclosing(f: Formula, stack: Optional[List[str]] = None, out: Optional[dict] = None) -> dict:
    """Walk the Formula tree and record, for each TripartiteQuantification,
    the set of variable names bound by enclosing quantifications."""
    if stack is None:
        stack = []
    if out is None:
        out = {}
    if f.quantification is not None:
        q = f.quantification
        out[id(q)] = set(stack)
        deeper = stack + [q.variable] + [iq.variable for iq in q.inner_quantifications]
        _collect_enclosing(q.nucleus, deeper, out)
    if f.negation is not None:
        _collect_enclosing(f.negation, stack, out)
    if f.connective is not None:
        for op in f.operands or []:
            _collect_enclosing(op, stack, out)
    return out


STRUCTURAL_CLASSES = (
    "ground_instance",
    "simple_universal",
    "simple_existential",
    "compound_restrictor_universal",
    "top_level_disjunction",
    "bare_implies_atomic_antecedent",
    "existential_compound_nucleus",
    "other",
)


def classify_structure(extraction: SentenceExtraction) -> str:
    """Classify the top-level structure of an extraction's Formula (§6.5 gate).

    Returns one of the strings in ``STRUCTURAL_CLASSES``. ``"other"`` is
    emitted when the top-level structure does not match any named class;
    such emissions must be surfaced per §15.
    """
    f = extraction.formula

    # Check structurally-weak top-level shapes before the ground check:
    # a disjunction of atomic ground formulas is still classified as
    # a top-level disjunction because that is what makes it weak under
    # the six-operator + witness-axiom regime.
    if f.connective == "or":
        return "top_level_disjunction"

    if f.connective == "implies" and len(f.operands or []) == 2:
        if f.operands[0].atomic is not None:
            return "bare_implies_atomic_antecedent"

    if _is_ground(f):
        return "ground_instance"

    if f.quantification is not None:
        q = f.quantification
        if q.quantifier == "universal":
            if len(q.restrictor) >= 2 or q.inner_quantifications:
                return "compound_restrictor_universal"
            return "simple_universal"
        # existential
        nucleus = q.nucleus
        # Simple existential: singleton restrictor with atomic nucleus (no
        # further compound structure).
        if nucleus.atomic is not None and len(q.restrictor) <= 1 and not q.inner_quantifications:
            return "simple_existential"
        return "existential_compound_nucleus"

    return "other"


def _is_ground(f: Formula) -> bool:
    """A ground formula is atomic or a connective/negation over grounds,
    with no free variables anywhere — every argument is a declared constant.
    Quantifications disqualify the formula from ground-instance class.
    """
    if f.atomic is not None:
        return True
    if f.quantification is not None:
        return False
    if f.negation is not None:
        return _is_ground(f.negation)
    if f.connective is not None:
        return all(_is_ground(op) for op in (f.operands or []))
    return False


def _walk_quantifications(f: Formula):
    """Yield every TripartiteQuantification node in the formula tree."""
    if f.quantification is not None:
        yield f.quantification
        yield from _walk_quantifications(f.quantification.nucleus)
    if f.negation is not None:
        yield from _walk_quantifications(f.negation)
    if f.connective is not None:
        for op in f.operands or []:
            yield from _walk_quantifications(op)


def _compile_atom(a: AtomicFormula) -> str:
    if a.pred == "__eq__" and len(a.args) == 2:
        body = f"({a.args[0]} = {a.args[1]})"
        return f"-{body}" if a.negated else body
    body = f"{a.pred}({', '.join(a.args)})"
    return f"-{body}" if a.negated else body


OPERATOR_NAMES = [
    "negate_atom",
    "swap_binary_args",
    "flip_quantifier",
    "drop_restrictor_conjunct",
    "flip_connective",
    "replace_subformula_with_negation",
    "disjunct_drop",
    "converse",
    "scope_swap",
    "equality_drop",
]


# ════════════════════════════════════════════════════════════════════════════
# Tree rewriting primitives
# ════════════════════════════════════════════════════════════════════════════

def _replace_nucleus(q: TripartiteQuantification, new_nucleus: Formula) -> TripartiteQuantification:
    return q.model_copy(update={"nucleus": new_nucleus})


def _replace_restrictor(
    q: TripartiteQuantification, new_restrictor: List[AtomicFormula]
) -> TripartiteQuantification:
    return q.model_copy(update={"restrictor": new_restrictor})


def _replace_operand(f: Formula, index: int, new_operand: Formula) -> Formula:
    new_ops = list(f.operands or [])
    new_ops[index] = new_operand
    return f.model_copy(update={"operands": new_ops})


# ════════════════════════════════════════════════════════════════════════════
# Operator 1: negate_atom
# ════════════════════════════════════════════════════════════════════════════

def negate_atom(f: Formula) -> List[Formula]:
    mutants: List[Formula] = []

    if f.atomic is not None:
        flipped = f.atomic.model_copy(update={"negated": not f.atomic.negated})
        mutants.append(Formula(atomic=flipped))

    if f.quantification is not None:
        q = f.quantification
        # Flip each restrictor atom in turn.
        for i, atom in enumerate(q.restrictor):
            new_r = list(q.restrictor)
            new_r[i] = atom.model_copy(update={"negated": not atom.negated})
            mutants.append(Formula(quantification=_replace_restrictor(q, new_r)))
        # Recurse into nucleus.
        for sub in negate_atom(q.nucleus):
            mutants.append(Formula(quantification=_replace_nucleus(q, sub)))

    if f.negation is not None:
        for sub in negate_atom(f.negation):
            mutants.append(Formula(negation=sub))

    if f.connective is not None:
        for i, op in enumerate(f.operands or []):
            for sub in negate_atom(op):
                mutants.append(_replace_operand(f, i, sub))

    return mutants


# ════════════════════════════════════════════════════════════════════════════
# Operator 2: swap_binary_args
# ════════════════════════════════════════════════════════════════════════════

def swap_binary_args(f: Formula) -> List[Formula]:
    mutants: List[Formula] = []

    if f.atomic is not None and len(f.atomic.args) == 2:
        swapped = f.atomic.model_copy(update={"args": [f.atomic.args[1], f.atomic.args[0]]})
        mutants.append(Formula(atomic=swapped))

    if f.quantification is not None:
        q = f.quantification
        for i, atom in enumerate(q.restrictor):
            if len(atom.args) == 2:
                new_r = list(q.restrictor)
                new_r[i] = atom.model_copy(update={"args": [atom.args[1], atom.args[0]]})
                mutants.append(Formula(quantification=_replace_restrictor(q, new_r)))
        for sub in swap_binary_args(q.nucleus):
            mutants.append(Formula(quantification=_replace_nucleus(q, sub)))

    if f.negation is not None:
        for sub in swap_binary_args(f.negation):
            mutants.append(Formula(negation=sub))

    if f.connective is not None:
        for i, op in enumerate(f.operands or []):
            for sub in swap_binary_args(op):
                mutants.append(_replace_operand(f, i, sub))

    return mutants


# ════════════════════════════════════════════════════════════════════════════
# Operator 3: flip_quantifier
# ════════════════════════════════════════════════════════════════════════════

def flip_quantifier(f: Formula) -> List[Formula]:
    mutants: List[Formula] = []

    if f.quantification is not None:
        q = f.quantification
        flipped = "existential" if q.quantifier == "universal" else "universal"
        mutants.append(Formula(quantification=q.model_copy(update={"quantifier": flipped})))
        for sub in flip_quantifier(q.nucleus):
            mutants.append(Formula(quantification=_replace_nucleus(q, sub)))

    if f.negation is not None:
        for sub in flip_quantifier(f.negation):
            mutants.append(Formula(negation=sub))

    if f.connective is not None:
        for i, op in enumerate(f.operands or []):
            for sub in flip_quantifier(op):
                mutants.append(_replace_operand(f, i, sub))

    return mutants


# ════════════════════════════════════════════════════════════════════════════
# Operator 4: drop_restrictor_conjunct
# ════════════════════════════════════════════════════════════════════════════

def drop_restrictor_conjunct(f: Formula) -> List[Formula]:
    mutants: List[Formula] = []

    if f.quantification is not None:
        q = f.quantification
        if len(q.restrictor) > 0:
            for i in range(len(q.restrictor)):
                new_r = [a for j, a in enumerate(q.restrictor) if j != i]
                mutants.append(Formula(quantification=_replace_restrictor(q, new_r)))
        for sub in drop_restrictor_conjunct(q.nucleus):
            mutants.append(Formula(quantification=_replace_nucleus(q, sub)))

    if f.negation is not None:
        for sub in drop_restrictor_conjunct(f.negation):
            mutants.append(Formula(negation=sub))

    if f.connective is not None:
        for i, op in enumerate(f.operands or []):
            for sub in drop_restrictor_conjunct(op):
                mutants.append(_replace_operand(f, i, sub))

    return mutants


# ════════════════════════════════════════════════════════════════════════════
# Operator 5: flip_connective
# ════════════════════════════════════════════════════════════════════════════

def flip_connective(f: Formula) -> List[Formula]:
    """Flip a logical connective at one site.

    The implies-swap (``A -> B`` ↦ ``B -> A``) was previously emitted here;
    it now lives in the dedicated ``converse`` operator for cleaner
    telemetry attribution. The iff-flip (``A <-> B`` ↦ ``A -> B``) stays
    here because it is not the converse of an implication."""
    mutants: List[Formula] = []

    if f.connective is not None:
        ops = list(f.operands or [])
        if f.connective == "and":
            mutants.append(Formula(connective="or", operands=ops))
        elif f.connective == "or":
            mutants.append(Formula(connective="and", operands=ops))
        elif f.connective == "implies":
            mutants.append(Formula(connective="iff", operands=ops))
        elif f.connective == "iff":
            mutants.append(Formula(connective="implies", operands=ops))
        # Recurse into each operand.
        for i, op in enumerate(ops):
            for sub in flip_connective(op):
                mutants.append(_replace_operand(f, i, sub))

    if f.quantification is not None:
        q = f.quantification
        for sub in flip_connective(q.nucleus):
            mutants.append(Formula(quantification=_replace_nucleus(q, sub)))

    if f.negation is not None:
        for sub in flip_connective(f.negation):
            mutants.append(Formula(negation=sub))

    return mutants


# ════════════════════════════════════════════════════════════════════════════
# Operator 6: replace_subformula_with_negation
# ════════════════════════════════════════════════════════════════════════════

def replace_subformula_with_negation(f: Formula) -> List[Formula]:
    """For each non-root non-atomic sub-formula, emit a mutant wrapping that
    sub-formula in ``Formula.negation``.
    """
    mutants: List[Formula] = []

    # Top-level: skip the root itself (non-root constraint), but walk into
    # its children and emit a negation wrap when the child is non-atomic.
    def _walk(node: Formula, wrap: Callable[[Formula], Formula]) -> None:
        # Child recursion: at each non-atomic child position, emit wrap
        # of the negation around it; also recurse deeper.
        if node.atomic is not None:
            return
        if node.quantification is not None:
            q = node.quantification
            # Nucleus is a non-root non-atomic sub-formula candidate.
            if q.nucleus.atomic is None:
                replaced = _replace_nucleus(q, Formula(negation=q.nucleus))
                mutants.append(wrap(Formula(quantification=replaced)))
            _walk(q.nucleus, lambda sub, q=q: wrap(Formula(quantification=_replace_nucleus(q, sub))))
            return
        if node.negation is not None:
            inner = node.negation
            if inner.atomic is None:
                mutants.append(wrap(Formula(negation=Formula(negation=inner))))
            _walk(inner, lambda sub: wrap(Formula(negation=sub)))
            return
        if node.connective is not None:
            for i, op in enumerate(node.operands or []):
                if op.atomic is None:
                    new_op = Formula(negation=op)
                    mutants.append(wrap(_replace_operand(node, i, new_op)))
                _walk(op, lambda sub, i=i, node=node: wrap(_replace_operand(node, i, sub)))
            return

    _walk(f, lambda x: x)
    return mutants


# ════════════════════════════════════════════════════════════════════════════
# Operator 7: disjunct_drop  (Stage-2)
# ════════════════════════════════════════════════════════════════════════════

def disjunct_drop(f: Formula) -> List[Formula]:
    """For each ``or``-site, emit one mutant per single disjunct removed.

    The result is strictly stronger than the original (the smaller disjunction
    entails the bigger). Admitted under the relaxed gate. Recurses into all
    composite forms so OR-sites at any depth are eligible."""
    mutants: List[Formula] = []

    if f.connective == "or":
        ops = list(f.operands or [])
        if len(ops) >= 2:
            for i in range(len(ops)):
                rest = [op for j, op in enumerate(ops) if j != i]
                if len(rest) == 1:
                    mutants.append(rest[0])
                else:
                    mutants.append(Formula(connective="or", operands=rest))
        # Recurse into operands too.
        for i, op in enumerate(ops):
            for sub in disjunct_drop(op):
                mutants.append(_replace_operand(f, i, sub))
    elif f.connective is not None:
        for i, op in enumerate(f.operands or []):
            for sub in disjunct_drop(op):
                mutants.append(_replace_operand(f, i, sub))

    if f.quantification is not None:
        q = f.quantification
        for sub in disjunct_drop(q.nucleus):
            mutants.append(Formula(quantification=_replace_nucleus(q, sub)))

    if f.negation is not None:
        for sub in disjunct_drop(f.negation):
            mutants.append(Formula(negation=sub))

    return mutants


# ════════════════════════════════════════════════════════════════════════════
# Operator 8: converse  (Stage-2)
# ════════════════════════════════════════════════════════════════════════════

def converse(f: Formula) -> List[Formula]:
    """For ``A -> B`` emit ``B -> A`` (the converse). Meaning-altering and
    typically incomparable to the original."""
    mutants: List[Formula] = []

    if f.connective == "implies":
        ops = list(f.operands or [])
        if len(ops) == 2:
            mutants.append(
                Formula(connective="implies", operands=[ops[1], ops[0]]),
            )
        for i, op in enumerate(ops):
            for sub in converse(op):
                mutants.append(_replace_operand(f, i, sub))
    elif f.connective is not None:
        for i, op in enumerate(f.operands or []):
            for sub in converse(op):
                mutants.append(_replace_operand(f, i, sub))

    if f.quantification is not None:
        q = f.quantification
        for sub in converse(q.nucleus):
            mutants.append(Formula(quantification=_replace_nucleus(q, sub)))

    if f.negation is not None:
        for sub in converse(f.negation):
            mutants.append(Formula(negation=sub))

    return mutants


# ════════════════════════════════════════════════════════════════════════════
# Operator 9: scope_swap  (Stage-4)
# ════════════════════════════════════════════════════════════════════════════

def scope_swap(f: Formula) -> List[Formula]:
    """For nested quantifier pairs ``∀x.∃y.φ`` and ``∃x.∀y.φ`` whose
    bindings have *different* quantifiers, emit the scope-swapped form.

    ``∀x.∃y.R(x,y)`` and ``∃y.∀x.R(x,y)`` are NOT equivalent: the latter
    asserts a single witness ``y`` that works for every ``x``, while the
    former allows ``y`` to vary with ``x``. The swap is meaning-altering
    and usually strictly stronger (the existential-outer form entails the
    universal-outer form under non-empty domains)."""
    mutants: List[Formula] = []

    if f.quantification is not None:
        q1 = f.quantification
        nucleus = q1.nucleus
        if (
            nucleus.quantification is not None
            and not q1.inner_quantifications
            and not nucleus.quantification.inner_quantifications
            and q1.quantifier != nucleus.quantification.quantifier
        ):
            q2 = nucleus.quantification
            new_inner = q1.model_copy(update={
                "nucleus": q2.nucleus,
            })
            new_outer = q2.model_copy(update={
                "nucleus": Formula(quantification=new_inner),
            })
            mutants.append(Formula(quantification=new_outer))
        # Recurse into nucleus.
        for sub in scope_swap(q1.nucleus):
            mutants.append(Formula(quantification=_replace_nucleus(q1, sub)))

    if f.negation is not None:
        for sub in scope_swap(f.negation):
            mutants.append(Formula(negation=sub))

    if f.connective is not None:
        for i, op in enumerate(f.operands or []):
            for sub in scope_swap(op):
                mutants.append(_replace_operand(f, i, sub))

    return mutants


# ════════════════════════════════════════════════════════════════════════════
# Operator 10: equality_drop  (Stage-4)
# ════════════════════════════════════════════════════════════════════════════

def equality_drop(f: Formula) -> List[Formula]:
    """For a disjunction of equality atoms ``x = a ∨ x = b ∨ ...``, emit
    the negate-all conjunction ``x ≠ a ∧ x ≠ b ∧ ...``. The drop-one
    variant is intentionally not emitted here — ``disjunct_drop`` already
    covers it (and the FOL-string dedup in ``generate_contrastives`` would
    suppress duplicates anyway)."""
    mutants: List[Formula] = []

    if f.connective == "or":
        ops = list(f.operands or [])
        if len(ops) >= 2 and all(_is_positive_equality_atom(op) for op in ops):
            negated_atoms = [
                Formula(atomic=op.atomic.model_copy(update={"negated": True}))
                for op in ops
            ]
            mutants.append(Formula(connective="and", operands=negated_atoms))
        for i, op in enumerate(ops):
            for sub in equality_drop(op):
                mutants.append(_replace_operand(f, i, sub))
    elif f.connective is not None:
        for i, op in enumerate(f.operands or []):
            for sub in equality_drop(op):
                mutants.append(_replace_operand(f, i, sub))

    if f.quantification is not None:
        q = f.quantification
        for sub in equality_drop(q.nucleus):
            mutants.append(Formula(quantification=_replace_nucleus(q, sub)))

    if f.negation is not None:
        for sub in equality_drop(f.negation):
            mutants.append(Formula(negation=sub))

    return mutants


def _is_positive_equality_atom(f: Formula) -> bool:
    return (
        f.atomic is not None
        and f.atomic.pred == "__eq__"
        and not f.atomic.negated
    )


# ════════════════════════════════════════════════════════════════════════════
# generate_contrastives
# ════════════════════════════════════════════════════════════════════════════

def _ast_canonicalize(f: Formula) -> str:
    """Canonical FOL string with sorted AND/OR/IFF operands, sorted
    restrictor atoms, and sorted equality args. Bound variable names are
    preserved (operator-induced mutations don't introduce fresh bound
    variables, so α-renaming adds no dedup value).

    Two Formulas that differ only in commutative-operand order produce the
    same canonical string; the dedup at the top of ``generate_contrastives``
    uses this to suppress operand-reorderings that the raw ``_a_formula``
    dedup would miss."""
    return _canon_str(f)


def _canon_str(f: Formula) -> str:
    if f.atomic is not None:
        a = f.atomic
        if a.pred == "__eq__" and len(a.args) == 2:
            args = sorted(a.args)
            body = "(" + args[0] + " = " + args[1] + ")"
            return "-" + body if a.negated else body
        body = a.pred + "(" + ", ".join(a.args) + ")"
        return "-" + body if a.negated else body
    if f.negation is not None:
        return "-(" + _canon_str(f.negation) + ")"
    if f.connective is not None:
        parts = [_canon_str(op) for op in f.operands or []]
        if f.connective == "and":
            return "(" + " & ".join(sorted(parts)) + ")"
        if f.connective == "or":
            return "(" + " | ".join(sorted(parts)) + ")"
        if f.connective == "iff":
            return "(" + " <-> ".join(sorted(parts)) + ")"
        if f.connective == "implies":
            return "(" + parts[0] + " -> " + parts[1] + ")"
    if f.quantification is not None:
        q = f.quantification
        r_parts = [_canon_str(Formula(atomic=a)) for a in q.restrictor]
        if not r_parts:
            r = None
        elif len(r_parts) == 1:
            r = r_parts[0]
        else:
            r = "(" + " & ".join(sorted(r_parts)) + ")"
        if r is not None:
            for iq in reversed(q.inner_quantifications):
                qk = "all" if iq.quantifier == "universal" else "exists"
                r = qk + " " + iq.variable + ".(" + r + ")"
        nuc = _canon_str(q.nucleus)
        outer = "all" if q.quantifier == "universal" else "exists"
        if r is None:
            return outer + " " + q.variable + ".(" + nuc + ")"
        if q.quantifier == "universal":
            return outer + " " + q.variable + ".(" + r + " -> " + nuc + ")"
        return outer + " " + q.variable + ".(" + r + " & " + nuc + ")"
    return ""


_OPERATORS: Dict[str, Callable[[Formula], List[Formula]]] = {
    "negate_atom": negate_atom,
    "swap_binary_args": swap_binary_args,
    "flip_quantifier": flip_quantifier,
    "drop_restrictor_conjunct": drop_restrictor_conjunct,
    "flip_connective": flip_connective,
    "replace_subformula_with_negation": replace_subformula_with_negation,
    "disjunct_drop": disjunct_drop,
    "converse": converse,
    "scope_swap": scope_swap,
    "equality_drop": equality_drop,
}


# Relation labels emitted by ``classify_mutant_relation``. Two of them
# (``incompatible``, ``strictly_stronger``) are admitted as contrastives;
# the rest are dropped.
_ADMITTED_RELATIONS = ("incompatible", "strictly_stronger")


# Stage 5b — compositional probes. Hard cap on admitted depth-2 mutants per
# premise; the iteration stops once this many are admitted. Locked before
# the v3 regeneration; do not change during a run.
_COMPOSITIONAL_CAP = 10


def _dedupe_units_by_vampire_equivalence(
    units: List[UnitTest], timeout_s: int,
) -> List[UnitTest]:
    """Pairwise FOL equivalence check; keep the smaller-FOL when two are
    equivalent. Quadratic in #units; only run at artifact-regeneration time
    behind ``SIV_DEDUPE_PROBES``."""
    keep: List[UnitTest] = []
    for u in units:
        replaced = False
        for i, kept in enumerate(keep):
            if _are_fol_equivalent(u.fol, kept.fol, timeout_s):
                if len(u.fol) < len(kept.fol):
                    keep[i] = u
                replaced = True
                break
        if not replaced:
            keep.append(u)
    return keep


def _are_fol_equivalent(a: str, b: str, timeout_s: int) -> bool:
    fwd = vampire_check(a, b, check="entails", timeout=timeout_s)
    if fwd != "unsat":
        return False
    bwd = vampire_check(b, a, check="entails", timeout=timeout_s)
    return bwd == "unsat"


def _compose_operators_enabled() -> bool:
    return os.environ.get("SIV_COMPOSE_OPERATORS", "0") == "1"


def _vampire_dedupe_enabled() -> bool:
    return os.environ.get("SIV_DEDUPE_PROBES", "0") == "1"


def classify_mutant_relation(
    gold_fol: str,
    mutant_fol: str,
    witnesses: List[str],
    timeout_s: int = 5,
) -> str:
    """Run the three-check Vampire protocol and return the relation label.

    Returns one of:
      - ``"incompatible"`` — gold ∧ mutant is unsat (Check A).
      - ``"strictly_stronger"`` — mutant ⊨ gold AND gold ⊭ mutant (B+C).
      - ``"equivalent"`` — mutant ⊨ gold AND gold ⊨ mutant.
      - ``"strictly_weaker"`` — mutant ⊭ gold AND gold ⊨ mutant.
      - ``"independent"`` — neither entails the other.
      - ``"timeout"`` — any of the three checks timed out / unknown.

    Only the first two are admitted as contrastives. The two-check
    formulation in the prior generator conflated ``strictly_stronger`` and
    ``independent``; both checks B and C are needed to keep them distinct.
    """
    a = vampire_check(
        gold_fol, mutant_fol, check="unsat",
        timeout=timeout_s, axioms=witnesses,
    )
    if a == "unsat":
        return "incompatible"
    if a in ("timeout", "unknown"):
        return "timeout"

    b = vampire_check(
        mutant_fol, gold_fol, check="entails",
        timeout=timeout_s, axioms=witnesses,
    )
    if b in ("timeout", "unknown"):
        return "timeout"

    c = vampire_check(
        gold_fol, mutant_fol, check="entails",
        timeout=timeout_s, axioms=witnesses,
    )
    if c in ("timeout", "unknown"):
        return "timeout"

    # B unsat ↔ mutant ⊨ gold; C unsat ↔ gold ⊨ mutant.
    if b == "unsat" and c == "sat":
        return "strictly_stronger"
    if b == "unsat" and c == "unsat":
        return "equivalent"
    if b == "sat" and c == "unsat":
        return "strictly_weaker"
    return "independent"


def generate_contrastives(
    extraction: SentenceExtraction,
    timeout_s: int = 5,
) -> Tuple[List[UnitTest], dict]:
    """Generate accepted contrastive unit tests for ``extraction``.

    Returns (accepted_list, telemetry_dict).
    """
    original_fol = _a_formula(extraction.formula)
    witnesses = derive_witness_axioms(extraction)

    _empty_op_bucket = lambda: {
        "generated": 0,
        "accepted_incompatible": 0,
        "accepted_strictly_stronger": 0,
        "dropped_equivalent": 0,
        "dropped_strictly_weaker": 0,
        "dropped_independent": 0,
        "dropped_timeout": 0,
    }
    per_op = {name: _empty_op_bucket() for name in OPERATOR_NAMES}

    accepted: List[UnitTest] = []
    accepted_formulas: List[Tuple[Formula, str]] = []  # for compositional pass
    generated = 0
    totals = {k: 0 for k in _empty_op_bucket() if k != "generated"}

    # Dedup mutants by AST-canonical form (sorts commutative operands so two
    # mutants that differ only in AND/OR/IFF operand order are recognized as
    # the same probe).
    seen_canon = {_ast_canonicalize(extraction.formula)}

    for op_name in OPERATOR_NAMES:
        op = _OPERATORS[op_name]
        for mutant_formula in op(extraction.formula):
            try:
                mutant_fol = _a_formula(mutant_formula)
            except SchemaViolation:
                continue
            mutant_canon = _ast_canonicalize(mutant_formula)
            if mutant_canon in seen_canon:
                continue
            seen_canon.add(mutant_canon)
            generated += 1
            per_op[op_name]["generated"] += 1

            relation = classify_mutant_relation(
                original_fol, mutant_fol, witnesses, timeout_s=timeout_s,
            )

            if relation in _ADMITTED_RELATIONS:
                accepted.append(UnitTest(
                    fol=mutant_fol,
                    kind="contrastive",
                    mutation_kind=op_name,
                    probe_relation=relation,
                ))
                accepted_formulas.append((mutant_formula, op_name))
                bucket = f"accepted_{relation}"
            else:
                bucket = f"dropped_{relation}"
            per_op[op_name][bucket] += 1
            totals[bucket] = totals.get(bucket, 0) + 1

    # Stage 5b — compositional probes (depth-2). Behind SIV_COMPOSE_OPERATORS.
    composed_admitted = 0
    if _compose_operators_enabled() and accepted_formulas:
        for m1_formula, op1 in accepted_formulas:
            if composed_admitted >= _COMPOSITIONAL_CAP:
                break
            for op2_name in OPERATOR_NAMES:
                if composed_admitted >= _COMPOSITIONAL_CAP:
                    break
                op2 = _OPERATORS[op2_name]
                for m12_formula in op2(m1_formula):
                    if composed_admitted >= _COMPOSITIONAL_CAP:
                        break
                    try:
                        m12_fol = _a_formula(m12_formula)
                    except SchemaViolation:
                        continue
                    m12_canon = _ast_canonicalize(m12_formula)
                    if m12_canon in seen_canon:
                        continue
                    seen_canon.add(m12_canon)
                    relation = classify_mutant_relation(
                        original_fol, m12_fol, witnesses, timeout_s=timeout_s,
                    )
                    if relation in _ADMITTED_RELATIONS:
                        accepted.append(UnitTest(
                            fol=m12_fol,
                            kind="contrastive",
                            mutation_kind=f"{op1}+{op2_name}",
                            probe_relation=relation,
                        ))
                        composed_admitted += 1

    # Stage 5c — Vampire-equivalence dedup (off by default; ~2h FOLIO-wide).
    if _vampire_dedupe_enabled() and accepted:
        accepted = _dedupe_units_by_vampire_equivalence(accepted, timeout_s)

    structural_class = classify_structure(extraction)
    structurally_weak = structural_class in (
        "top_level_disjunction",
        "bare_implies_atomic_antecedent",
        "existential_compound_nucleus",
    )
    empty_reason: Optional[str] = None
    if not accepted:
        if structurally_weak:
            empty_reason = "no admissible mutation under B' witness axioms"
        else:
            empty_reason = "no admissible mutation produced (mechanism failure)"

    telemetry = {
        "generated": generated,
        "accepted": len(accepted),
        "accepted_incompatible": totals.get("accepted_incompatible", 0),
        "accepted_strictly_stronger": totals.get("accepted_strictly_stronger", 0),
        "dropped_equivalent": totals.get("dropped_equivalent", 0),
        "dropped_strictly_weaker": totals.get("dropped_strictly_weaker", 0),
        "dropped_independent": totals.get("dropped_independent", 0),
        "dropped_timeout": totals.get("dropped_timeout", 0),
        "unknown_rate": (totals.get("dropped_timeout", 0) / generated) if generated else 0.0,
        "per_operator": per_op,
        "structural_class": structural_class,
        "empty_reason": empty_reason,
    }
    return accepted, telemetry
