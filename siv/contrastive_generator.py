"""
Contrastive generator (SIV.md §6.5, C7).

Produces candidate negative (contrastive) unit tests by mutating a
``SentenceExtraction``'s formula tree with six exhaustive operators, then
filters each mutant through Vampire. A mutant is accepted iff
``(original ∧ mutant)`` is proved unsatisfiable — i.e., provably
inconsistent, not merely different.
"""
from __future__ import annotations

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
    mutants: List[Formula] = []

    if f.connective is not None:
        ops = list(f.operands or [])
        if f.connective == "and":
            mutants.append(Formula(connective="or", operands=ops))
        elif f.connective == "or":
            mutants.append(Formula(connective="and", operands=ops))
        elif f.connective == "implies":
            mutants.append(Formula(connective="iff", operands=ops))
            mutants.append(Formula(connective="implies", operands=[ops[1], ops[0]]))
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
# generate_contrastives
# ════════════════════════════════════════════════════════════════════════════

_OPERATORS: Dict[str, Callable[[Formula], List[Formula]]] = {
    "negate_atom": negate_atom,
    "swap_binary_args": swap_binary_args,
    "flip_quantifier": flip_quantifier,
    "drop_restrictor_conjunct": drop_restrictor_conjunct,
    "flip_connective": flip_connective,
    "replace_subformula_with_negation": replace_subformula_with_negation,
}


def generate_contrastives(
    extraction: SentenceExtraction,
    timeout_s: int = 5,
) -> Tuple[List[UnitTest], dict]:
    """Generate accepted contrastive unit tests for ``extraction``.

    Returns (accepted_list, telemetry_dict).
    """
    original_fol = _a_formula(extraction.formula)
    witnesses = derive_witness_axioms(extraction)

    per_op = {name: {"generated": 0, "accepted": 0, "dropped_neutral": 0, "dropped_unknown": 0}
              for name in OPERATOR_NAMES}

    accepted: List[UnitTest] = []
    generated = 0
    dropped_neutral = 0
    dropped_unknown = 0

    # Dedup mutants by compiled FOL string (prevents e.g. double-counting a
    # structurally-identical mutant emitted via two paths).
    seen_fol = {original_fol}

    for op_name in OPERATOR_NAMES:
        op = _OPERATORS[op_name]
        for mutant_formula in op(extraction.formula):
            try:
                mutant_fol = _a_formula(mutant_formula)
            except SchemaViolation:
                continue
            if mutant_fol in seen_fol:
                continue
            seen_fol.add(mutant_fol)
            generated += 1
            per_op[op_name]["generated"] += 1

            verdict = vampire_check(
                original_fol, mutant_fol, check="unsat",
                timeout=timeout_s, axioms=witnesses,
            )
            if verdict == "unsat":
                accepted.append(UnitTest(
                    fol=mutant_fol,
                    kind="contrastive",
                    mutation_kind=op_name,
                ))
                per_op[op_name]["accepted"] += 1
            elif verdict == "sat":
                dropped_neutral += 1
                per_op[op_name]["dropped_neutral"] += 1
            else:  # timeout or unknown
                dropped_unknown += 1
                per_op[op_name]["dropped_unknown"] += 1

    structural_class = classify_structure(extraction)
    structurally_weak = structural_class in (
        "top_level_disjunction",
        "bare_implies_atomic_antecedent",
        "existential_compound_nucleus",
    )
    empty_reason: Optional[str] = None
    if not accepted:
        if structurally_weak:
            empty_reason = "no unsat mutation under B' witness axioms"
        else:
            empty_reason = "no unsat mutation produced (mechanism failure)"

    telemetry = {
        "generated": generated,
        "accepted": len(accepted),
        "dropped_neutral": dropped_neutral,
        "dropped_unknown": dropped_unknown,
        "unknown_rate": (dropped_unknown / generated) if generated else 0.0,
        "per_operator": per_op,
        "structural_class": structural_class,
        "empty_reason": empty_reason,
    }
    return accepted, telemetry
