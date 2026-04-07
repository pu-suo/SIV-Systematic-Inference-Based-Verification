"""
Stage 3: Deterministic FOL Test Compilation

Takes a ProblemExtraction (constants + entities + facts + templates) and
generates positive and negative FOL unit tests in NLTK format.

Compilation matrix by argument type:
  Pred(const, const)      → Pred(const_id, const_id)          (zero quantifiers)
  Pred(const, entity)     → exists x.(EntType(x) & Pred(const_id, x))
  Pred(entity, const)     → exists x.(EntType(x) & Pred(x, const_id))
  Pred(entity, entity)    → exists x.(exists y.(SubjType(x) & ObjType(y) & Pred(x,y)))
  Pred(entity)            → exists x.(EntType(x) & Pred(x))   (or universal wrapper)

Negative tests: in-problem structural perturbations using only predicates and
entity types drawn from the same ProblemExtraction (Tenet 1: no foreign vocabulary).
Strategies: argument-order swap, polarity flip, cross-predicate substitution.

All FOL strings use NLTK-compatible ASCII format:
  exists x.(P(x) & Q(x))
  all x.(P(x) -> Q(x))
  -P(x)
"""
import re
from typing import Dict, List, Optional, Tuple

from siv.schema import (
    Entity, EntityType, Fact, MacroTemplate,
    ProblemExtraction, SchemaViolation, SentenceExtraction, TestSuite, UnitTest,
)

# ── String helpers ────────────────────────────────────────────────────────────

def _to_camel_case(surface: str) -> str:
    """
    Convert a surface-form string to CamelCase FOL predicate.

    "directed by"    → "DirectedBy"
    "Harvard student"→ "HarvardStudent"
    "tall"           → "Tall"
    "running"        → "Running"
    """
    if not surface:
        return ""
    return "".join(w.capitalize() for w in re.split(r"[\s_\-]+", surface.strip()))


def _entity_pred(entity: Entity) -> str:
    """Return the CamelCase predicate name for an entity's surface type."""
    return _to_camel_case(entity.surface)


def _fact_pred(fact: Fact) -> str:
    """Return the CamelCase predicate name for a fact."""
    return _to_camel_case(fact.pred)


def _to_fol_string(pred: str, args: List[str], negated: bool = False) -> str:
    """Build NLTK-compatible FOL atom: Pred(a, b, …) or -Pred(a, b, …)."""
    atom = f"{pred}({', '.join(args)})"
    return f"-{atom}" if negated else atom


# ── ID lookup ─────────────────────────────────────────────────────────────────

# Each entry is ('const', surface_str) or ('entity', Entity)
_IdEntry = Tuple[str, object]


def _build_id_map(extraction: ProblemExtraction) -> Dict[str, _IdEntry]:
    """
    Build a unified lookup dict:  id → ('const', surface) | ('entity', Entity)

    Sources (in priority order):
      1. New-style Constant objects from sentence.constants
      2. Old-style Entity objects with EntityType.CONSTANT (backward compat)
      3. All other Entity objects
    """
    result: Dict[str, _IdEntry] = {}

    # New-style constants
    for c in extraction.all_constants:
        result[c.id] = ("const", c.id)   # term used in FOL = the id itself

    # Entities (includes old-style CONSTANT entities for backward compat)
    for e in extraction.all_entities:
        if e.entity_type == EntityType.CONSTANT:
            # Old-style: use entity id as the FOL term
            if e.id not in result:
                result[e.id] = ("const", e.id)
        else:
            result[e.id] = ("entity", e)

    return result


def _is_const(arg_id: str, id_map: Dict[str, _IdEntry]) -> bool:
    entry = id_map.get(arg_id)
    return entry is not None and entry[0] == "const"


def _const_term(arg_id: str, id_map: Dict[str, _IdEntry]) -> str:
    """Return the FOL term string for a constant argument."""
    entry = id_map.get(arg_id)
    if entry and entry[0] == "const":
        return str(entry[1])
    return arg_id   # fallback


# ── Vocabulary tests ──────────────────────────────────────────────────────────

def _compile_vocabulary_tests(extraction: ProblemExtraction) -> List[UnitTest]:
    """
    For every unique predicate in the extraction, generate an existence test:
      exists x.Pred(x)     (arity-1)
      exists x.(exists y.Pred(x,y))   (arity-2)
    These are the cheapest tests — resolved at Tier 1 (vocabulary check).
    """
    id_map = _build_id_map(extraction)

    # FIX A: skip existential probe when fact is universally bound; binding test covers it
    def _has_universal_arg(fact: Fact) -> bool:
        for a in fact.args:
            entry = id_map.get(a)
            if entry and entry[0] == "entity" and entry[1].entity_type == EntityType.UNIVERSAL:
                return True
        return False

    seen: set = set()
    tests: List[UnitTest] = []

    for fact in extraction.all_facts:
        pred = _fact_pred(fact)
        # FIX A: skip existential probe when fact is universally bound; binding test covers it
        if _has_universal_arg(fact):
            # Do NOT add pred to seen — a later non-universal appearance may still emit the probe
            continue
        if pred in seen:
            continue
        seen.add(pred)

        arity = len(fact.args)
        if arity == 1:
            fol = f"exists x.{pred}(x)"
        elif arity == 2:
            fol = f"exists x.(exists y.{pred}(x,y))"
        else:
            # arity 3+
            vars_ = ["x", "y", "z"][:arity]
            inner = _to_fol_string(pred, vars_)
            fol = " ".join(f"exists {v}.(" for v in vars_[:-1]) + inner + ")" * (arity - 1)

        tests.append(UnitTest(
            fol_string=fol,
            test_type="vocabulary",
            is_positive=True,
            source_fact=fact,
        ))

    return tests


# ── Binding tests ─────────────────────────────────────────────────────────────

def _compile_binding_tests(extraction: ProblemExtraction) -> List[UnitTest]:
    """
    For each fact, generate tests that the predicate applies to the correct
    entity / constant using the compilation matrix:

      Pred(c, c)      → Pred(c_id, c_id)
      Pred(c, e)      → exists x.(EntType(x) & Pred(c_id, x))
      Pred(e, c)      → exists x.(EntType(x) & Pred(x, c_id))
      Pred(e, e)      → exists x.(exists y.(SubjType(x) & ObjType(y) & Pred(x,y)))
      Pred(e)  exist  → exists x.(EntType(x) & Pred(x))
      Pred(e)  univ   → all x.(EntType(x) -> Pred(x))
      Pred(c)         → Pred(c_id)
    """
    id_map = _build_id_map(extraction)
    tests: List[UnitTest] = []

    for sent in extraction.sentences:
        for fact in sent.facts:
            pred = _fact_pred(fact)
            args = fact.args
            arity = len(args)

            if arity == 1:
                arg = args[0]
                if _is_const(arg, id_map):
                    # Grounded: Pred(const_id)
                    fol = _to_fol_string(pred, [_const_term(arg, id_map)], fact.negated)
                    tests.append(UnitTest(fol_string=fol, test_type="binding",
                                          is_positive=True, source_fact=fact))
                else:
                    entry = id_map.get(arg)
                    if entry and entry[0] == "entity":
                        ent: Entity = entry[1]  # type: ignore[assignment]
                        ent_pred = _entity_pred(ent)
                        if ent.entity_type == EntityType.UNIVERSAL:
                            inner = f"all x.({ent_pred}(x) -> {_to_fol_string(pred, ['x'], fact.negated)})"
                        else:
                            inner = (
                                f"exists x.({ent_pred}(x) & "
                                f"{_to_fol_string(pred, ['x'], fact.negated)})"
                            )
                        tests.append(UnitTest(fol_string=inner, test_type="binding",
                                              is_positive=True, source_fact=fact))

            elif arity == 2:
                subj_id, obj_id = args[0], args[1]
                subj_const = _is_const(subj_id, id_map)
                obj_const  = _is_const(obj_id, id_map)

                if subj_const and obj_const:
                    # Both constants: Pred(c1, c2)
                    fol = _to_fol_string(
                        pred,
                        [_const_term(subj_id, id_map), _const_term(obj_id, id_map)],
                        fact.negated,
                    )
                    tests.append(UnitTest(fol_string=fol, test_type="binding",
                                          is_positive=True, source_fact=fact))

                elif subj_const and not obj_const:
                    # Const + entity: exists x.(ObjType(x) & Pred(const, x))
                    obj_entry = id_map.get(obj_id)
                    if obj_entry and obj_entry[0] == "entity":
                        obj_ent: Entity = obj_entry[1]  # type: ignore[assignment]
                        obj_ent_pred = _entity_pred(obj_ent)
                        atom = _to_fol_string(
                            pred, [_const_term(subj_id, id_map), "x"], fact.negated
                        )
                        fol = f"exists x.({obj_ent_pred}(x) & {atom})"
                        tests.append(UnitTest(fol_string=fol, test_type="binding",
                                              is_positive=True, source_fact=fact))

                elif not subj_const and obj_const:
                    # Entity + const: exists x.(SubjType(x) & Pred(x, const))
                    subj_entry = id_map.get(subj_id)
                    if subj_entry and subj_entry[0] == "entity":
                        subj_ent: Entity = subj_entry[1]  # type: ignore[assignment]
                        subj_ent_pred = _entity_pred(subj_ent)
                        atom = _to_fol_string(
                            pred, ["x", _const_term(obj_id, id_map)], fact.negated
                        )
                        fol = f"exists x.({subj_ent_pred}(x) & {atom})"
                        tests.append(UnitTest(fol_string=fol, test_type="binding",
                                              is_positive=True, source_fact=fact))

                else:
                    # FIX A: universal entities require universal-quantified binding test, not existential
                    subj_entry = id_map.get(subj_id)
                    obj_entry  = id_map.get(obj_id)
                    subj_is_universal = (
                        subj_entry is not None
                        and subj_entry[0] == "entity"
                        and subj_entry[1].entity_type == EntityType.UNIVERSAL  # type: ignore[union-attr]
                    )
                    if subj_is_universal:
                        # FIX A: all x.(SubjType(x) -> exists y.(ObjType(y) & Pred(x, y)))
                        subj_ent: Entity = subj_entry[1]  # type: ignore[assignment]
                        subj_ent_pred = _entity_pred(subj_ent)
                        inner_parts = []
                        if obj_entry and obj_entry[0] == "entity":
                            inner_parts.append(f"{_entity_pred(obj_entry[1])}(y)")  # type: ignore[arg-type]
                        inner_parts.append(_to_fol_string(pred, ["x", "y"], fact.negated))
                        inner = f"exists y.({' & '.join(inner_parts)})"
                        fol = f"all x.({subj_ent_pred}(x) -> {inner})"
                    else:
                        # Both entities, neither is universal: exists x.(exists y.(SubjType(x) & ObjType(y) & Pred(x,y)))
                        parts = []
                        if subj_entry and subj_entry[0] == "entity":
                            parts.append(f"{_entity_pred(subj_entry[1])}(x)")  # type: ignore[arg-type]
                        if obj_entry and obj_entry[0] == "entity":
                            parts.append(f"{_entity_pred(obj_entry[1])}(y)")  # type: ignore[arg-type]
                        parts.append(_to_fol_string(pred, ["x", "y"], fact.negated))
                        fol = f"exists x.(exists y.({' & '.join(parts)}))"
                    tests.append(UnitTest(fol_string=fol, test_type="binding",
                                          is_positive=True, source_fact=fact))

    return tests


# ── Macro template tests ──────────────────────────────────────────────────────

# FIX G1: helper for binary-fact conditional macro templates
def _fact_to_macro_shape(
    fact: "Fact",
    shared_arg: str,
    id_map: Dict[str, "_IdEntry"],
    var_prefix: str,
) -> Optional[str]:
    """
    Render a single fact as an FOL fragment where `shared_arg` is replaced
    by the bound variable `x` and every other argument is introduced as
    a fresh existential with the correct entity type.

    Returns a string like:
      "exists a1.(Home(a1) & HasLunchAt(x, a1))"
    or None if the fact is malformed.
    """
    pred = _fact_pred(fact)
    if not fact.args:
        return None

    fresh_counter = 0
    type_constraints: List[str] = []
    var_map: Dict[str, str] = {}
    for arg in fact.args:
        if arg == shared_arg:
            var_map[arg] = "x"
            continue
        entry = id_map.get(arg)
        if entry and entry[0] == "const":
            # A constant argument — substitute the literal term
            var_map[arg] = _const_term(arg, id_map)
        else:
            # Fresh variable for this argument
            fresh = f"{var_prefix}{fresh_counter}"
            fresh_counter += 1
            var_map[arg] = fresh
            if entry and entry[0] == "entity":
                type_constraints.append(f"{_entity_pred(entry[1])}({fresh})")  # type: ignore[arg-type]

    # Build atom with substituted args
    substituted_args = [var_map[a] for a in fact.args]
    atom = _to_fol_string(pred, substituted_args, fact.negated)

    # Wrap fresh existentials around it
    fresh_vars = [v for a, v in var_map.items()
                  if a != shared_arg and v.startswith(var_prefix)]
    if not fresh_vars:
        return atom

    inner = " & ".join(type_constraints + [atom])
    result = inner
    for v in reversed(fresh_vars):
        result = f"exists {v}.({result})"
    return result


def _compile_macro_tests(extraction: ProblemExtraction) -> List[UnitTest]:
    """
    For each sentence whose macro_template is informative, generate a
    structural FOL test matching the Aristotelian form.
    """
    id_map = _build_id_map(extraction)
    tests: List[UnitTest] = []

    for sent in extraction.sentences:
        mt = sent.macro_template
        facts = sent.facts
        entities = sent.entities

        if not entities or not facts:
            continue

        # FIX G2: macro subject must be selected by entity_type, not array index.
        # TYPE_A / TYPE_E: the universally quantified entity.
        # TYPE_I / TYPE_O: the existentially quantified entity (first one if multiple).
        universal_entities   = [e for e in entities if e.entity_type == EntityType.UNIVERSAL]
        existential_entities = [e for e in entities if e.entity_type == EntityType.EXISTENTIAL]

        if mt in (MacroTemplate.TYPE_A, MacroTemplate.TYPE_E):
            if not universal_entities:
                continue  # malformed extraction — universal template with no universal entity
            subj_ent = universal_entities[0]
        elif mt in (MacroTemplate.TYPE_I, MacroTemplate.TYPE_O):
            if not existential_entities:
                continue
            subj_ent = existential_entities[0]
        else:
            # GROUND_*, CONDITIONAL, BICONDITIONAL — keep existing subject-picking behavior
            subj_ent = entities[0] if entities else None

        # Guard: if subj_ent is None for non-categorical templates, skip
        if subj_ent is None:
            continue
        subj_pred = _entity_pred(subj_ent)

        # 1-arg facts used by TYPE_*, BICONDITIONAL, and GROUND_* branches
        prop_facts = [f for f in facts if len(f.args) == 1]

        if mt == MacroTemplate.TYPE_A:
            # FIX G2: subj_ent now correctly bound to universal entity above
            if not prop_facts:
                continue
            obj_fact = prop_facts[-1]
            obj_pred = _fact_pred(obj_fact)
            fol = f"all x.({subj_pred}(x) -> {obj_pred}(x))"
            tests.append(UnitTest(fol_string=fol, test_type="entailment",
                                  is_positive=True, source_fact=obj_fact))

        elif mt == MacroTemplate.TYPE_E:
            # FIX G2: subj_ent now correctly bound to universal entity above
            if not prop_facts:
                continue
            obj_fact = prop_facts[-1]
            obj_pred = _fact_pred(obj_fact)
            fol = f"all x.({subj_pred}(x) -> -{obj_pred}(x))"
            tests.append(UnitTest(fol_string=fol, test_type="entailment",
                                  is_positive=True, source_fact=obj_fact))

        elif mt == MacroTemplate.TYPE_I:
            # FIX G2: subj_ent now correctly bound to existential entity above
            if not prop_facts:
                continue
            obj_fact = prop_facts[-1]
            obj_pred = _fact_pred(obj_fact)
            fol = f"exists x.({subj_pred}(x) & {obj_pred}(x))"
            tests.append(UnitTest(fol_string=fol, test_type="entailment",
                                  is_positive=True, source_fact=obj_fact))

        elif mt == MacroTemplate.TYPE_O:
            # FIX G2: subj_ent now correctly bound to existential entity above
            if not prop_facts:
                continue
            obj_fact = prop_facts[-1]
            obj_pred = _fact_pred(obj_fact)
            fol = f"exists x.({subj_pred}(x) & -{obj_pred}(x))"
            tests.append(UnitTest(fol_string=fol, test_type="entailment",
                                  is_positive=True, source_fact=obj_fact))

        elif mt == MacroTemplate.GROUND_POSITIVE:
            for fact in prop_facts:
                eid = fact.args[0]
                if _is_const(eid, id_map):
                    fol = _to_fol_string(_fact_pred(fact), [_const_term(eid, id_map)])
                    tests.append(UnitTest(fol_string=fol, test_type="entailment",
                                          is_positive=True, source_fact=fact))

        elif mt == MacroTemplate.GROUND_NEGATIVE:
            for fact in prop_facts:
                eid = fact.args[0]
                if _is_const(eid, id_map):
                    fol = _to_fol_string(_fact_pred(fact), [_const_term(eid, id_map)],
                                         negated=True)
                    tests.append(UnitTest(fol_string=fol, test_type="entailment",
                                          is_positive=True, source_fact=fact))

        elif mt == MacroTemplate.CONDITIONAL:
            # FIX G1: accept binary facts in conditional clauses, not just unary.
            # Antecedent = first fact in sentence order; consequent = second fact.
            # The two facts must share at least one argument; we universally bind
            # on that shared argument.
            if len(sent.facts) < 2:
                continue
            ant_fact = sent.facts[0]
            con_fact = sent.facts[1]
            shared_args = set(ant_fact.args) & set(con_fact.args)
            if not shared_args:
                # No shared argument — skip rather than emit a malformed test
                continue

            # Pick the shared argument to universally bind. Prefer an entity (over
            # a constant) if both options exist.
            shared_arg = None
            for a in shared_args:
                entry = id_map.get(a)
                if entry and entry[0] == "entity":
                    shared_arg = a
                    break
            if shared_arg is None:
                shared_arg = next(iter(shared_args))

            # Build the antecedent and consequent shapes with the shared arg
            # replaced by x and other args replaced by fresh existentials.
            ant_shape = _fact_to_macro_shape(ant_fact, shared_arg, id_map, var_prefix="a")
            con_shape = _fact_to_macro_shape(con_fact, shared_arg, id_map, var_prefix="c")
            if ant_shape is None or con_shape is None:
                continue

            # Wrap the subject entity type, if the shared arg is an entity
            shared_entry = id_map.get(shared_arg)
            if shared_entry and shared_entry[0] == "entity":
                subj_type = _entity_pred(shared_entry[1])  # type: ignore[arg-type]
                body = f"({subj_type}(x) & {ant_shape}) -> {con_shape}"
            else:
                body = f"{ant_shape} -> {con_shape}"

            fol = f"all x.({body})"
            tests.append(UnitTest(fol_string=fol, test_type="entailment",
                                  is_positive=True, source_fact=con_fact))

        elif mt == MacroTemplate.BICONDITIONAL and len(prop_facts) >= 2:
            ant_pred = _fact_pred(prop_facts[0])
            con_pred = _fact_pred(prop_facts[1])
            fol = f"all x.({ant_pred}(x) <-> {con_pred}(x))"
            tests.append(UnitTest(fol_string=fol, test_type="entailment",
                                  is_positive=True, source_fact=prop_facts[1]))

    return tests


# ── Negative (contrastive) tests ──────────────────────────────────────────────

# FIX D1 + D2: helpers for in-problem structural perturbations.

def _fact_has_universal_arg(fact: "Fact", id_map: Dict[str, "_IdEntry"]) -> bool:
    # FIX D1 + D2: check whether any argument of this fact is a universal entity.
    for a in fact.args:
        entry = id_map.get(a)
        if entry and entry[0] == "entity" and entry[1].entity_type == EntityType.UNIVERSAL:  # type: ignore[union-attr]
            return True
    return False


def _render_binding_atom(
    pred: str,
    args: List[str],
    id_map: Dict[str, "_IdEntry"],
    negated: bool,
    universal_wrap: bool,
) -> Optional[str]:
    """
    FIX D1 + D2: Render a single predicate-application as a closed FOL formula
    using the same universal/existential rules as the positive binding tests.
    Returns None if the rendering is ill-formed (e.g., zero arguments).
    """
    if not args:
        return None

    # All constants → ground formula
    if all(_is_const(a, id_map) for a in args):
        terms = [_const_term(a, id_map) for a in args]
        return _to_fol_string(pred, terms, negated)

    # Find the universal entity (at most one — we use the first found)
    univ_idx: Optional[int] = None
    for i, a in enumerate(args):
        entry = id_map.get(a)
        if entry and entry[0] == "entity" and entry[1].entity_type == EntityType.UNIVERSAL:  # type: ignore[union-attr]
            univ_idx = i
            break

    var_map: Dict[str, str] = {}
    type_constraints: List[str] = []
    fresh_counter = 0
    used_x = False
    rendered_args: List[str] = []

    for i, a in enumerate(args):
        if i == univ_idx:
            var_map[a] = "x"
            used_x = True
            rendered_args.append("x")
            continue
        if _is_const(a, id_map):
            rendered_args.append(_const_term(a, id_map))
            continue
        # Existential entity: assign a fresh variable
        fresh = f"y{fresh_counter}" if fresh_counter > 0 or used_x else "y"
        fresh_counter += 1
        var_map[a] = fresh
        entry = id_map.get(a)
        if entry and entry[0] == "entity":
            type_constraints.append(f"{_entity_pred(entry[1])}({fresh})")  # type: ignore[arg-type]
        rendered_args.append(fresh)

    atom = _to_fol_string(pred, rendered_args, negated)
    inner_parts = type_constraints + [atom]
    inner = " & ".join(inner_parts) if len(inner_parts) > 1 else inner_parts[0]

    # Wrap fresh variables in existentials (innermost first → reversed)
    fresh_vars = [v for a, v in var_map.items() if v != "x"]
    wrapped = inner
    for v in reversed(fresh_vars):
        wrapped = f"exists {v}.({wrapped})"

    if universal_wrap and univ_idx is not None:
        subj_entry = id_map.get(args[univ_idx])
        subj_type = _entity_pred(subj_entry[1])  # type: ignore[index,arg-type]
        return f"all x.({subj_type}(x) -> {wrapped})"

    return wrapped


def _compile_negative_tests(extraction: ProblemExtraction) -> List[UnitTest]:
    """
    FIX D1 + D2: Contrastive precision tests are generated by three
    in-problem structural perturbations. No foreign vocabulary is
    introduced (Tenet 1: strict lexical faithfulness).

    Strategy 1 — Argument swap (binary facts only):
      Pred(a, b)  →  negative test asserts Pred(b, a) is entailed.
      The candidate must NOT entail the swapped form.

    Strategy 2 — Polarity flip (any fact):
      For a non-negated fact P(...), the negative test is -P(...).
      For a negated fact -P(...), the negative test is P(...).
      The candidate must NOT entail the flipped form.

    Strategy 3 — Cross-predicate substitution (binary facts only):
      Given Pred(a, b), substitute one other binary predicate Other from the
      same extraction and test Other(a, b) must NOT be entailed. This catches
      translations that collapse distinct relations into a single predicate.
    """
    tests: List[UnitTest] = []
    seen_fols: set = set()
    id_map = _build_id_map(extraction)

    def _add(fol: str, source_fact: Fact) -> None:
        if fol in seen_fols:
            return
        seen_fols.add(fol)
        tests.append(UnitTest(
            fol_string=fol,
            test_type="contrastive",
            is_positive=False,
            source_fact=source_fact,
        ))

    # Collect all binary predicates across the problem for Strategy 3
    # (insertion order preserves first-seen for determinism)
    binary_preds_seen: Dict[str, Fact] = {}
    for f in extraction.all_facts:
        if len(f.args) == 2:
            p = _fact_pred(f)
            if p not in binary_preds_seen:
                binary_preds_seen[p] = f

    for fact in extraction.all_facts:
        pred = _fact_pred(fact)
        args = fact.args
        arity = len(args)
        has_univ = _fact_has_universal_arg(fact, id_map)

        # ── Strategy 1: argument swap (binary only) ──
        if arity == 2:
            swapped = _render_binding_atom(
                pred, [args[1], args[0]], id_map,
                negated=fact.negated,
                universal_wrap=_fact_has_universal_arg(
                    Fact(pred=fact.pred, args=[args[1], args[0]], negated=fact.negated),
                    id_map,
                ),
            )
            if swapped is not None:
                _add(swapped, fact)

        # ── Strategy 2: polarity flip (any arity) ──
        flipped = _render_binding_atom(
            pred, args, id_map,
            negated=(not fact.negated),
            universal_wrap=has_univ,
        )
        if flipped is not None:
            _add(flipped, fact)

        # ── Strategy 3: cross-predicate substitution (binary only) ──
        if arity == 2:
            for other_pred, _other_fact in binary_preds_seen.items():
                if other_pred == pred:
                    continue
                subst = _render_binding_atom(
                    other_pred, args, id_map,
                    negated=fact.negated,
                    universal_wrap=has_univ,
                )
                if subst is not None:
                    _add(subst, fact)
                # Only ONE alternative predicate per fact to keep the suite manageable
                break

    return tests


# ── Internal compile helper ───────────────────────────────────────────────────

def _compile_from_extraction(extraction: ProblemExtraction) -> TestSuite:
    """Internal: compile all test types from a ProblemExtraction."""
    vocab_tests   = _compile_vocabulary_tests(extraction)
    binding_tests = _compile_binding_tests(extraction)
    macro_tests   = _compile_macro_tests(extraction)
    neg_tests     = _compile_negative_tests(extraction)

    # Deduplicate positive tests by FOL string
    seen_pos: set = set()
    positive: List[UnitTest] = []
    for t in vocab_tests + binding_tests + macro_tests:
        if t.fol_string not in seen_pos:
            seen_pos.add(t.fol_string)
            positive.append(t)

    seen_neg: set = set()
    negative: List[UnitTest] = []
    for t in neg_tests:
        if t.fol_string not in seen_neg:
            seen_neg.add(t.fol_string)
            negative.append(t)

    return TestSuite(
        problem_id=extraction.problem_id,
        positive_tests=positive,
        negative_tests=negative,
    )


# ── Neo-Davidsonian validator ─────────────────────────────────────────────────

# FIX C1: Neo-Davidsonian schema validator.
# Tenet 2 requires that all facts decompose into unary properties or binary
# relations. A 1-arg fact whose predicate surface contains a preposition is
# a symptom that the extractor welded a second argument into the verb
# instead of reifying it as a separate entity + binary edge. Under Tenet 4
# we do not tolerate this — we flag the extraction as invalid and let the
# score propagate to SIV=0.
_PREPOSITION_TOKENS = frozenset({
    "from", "to", "in", "at", "on", "by", "with", "into",
    "onto", "of", "for", "about", "over", "under", "through",
    "across", "between", "among", "against", "toward", "towards",
})


def validate_neo_davidsonian(extraction: ProblemExtraction) -> List[SchemaViolation]:
    """
    Scan an extraction for Neo-Davidsonian violations. Returns a list of
    SchemaViolation objects; an empty list means the extraction is valid.

    Current rules:
      1. A 1-arg fact whose predicate surface contains any preposition
         token is a 'prepositional_unary' violation — the second argument
         should have been reified.
      2. A fact with arity > 2 is a 'high_arity' violation — Neo-Davidsonian
         form permits only unary and binary predicates.

    # FIX C1: see Tenet 2 (Neo-Davidsonian Imperative) and Tenet 4 (A Standard,
    # Not a Safety Net) in refactor/SIV_REFACTOR_CONTEXT.md.
    """
    violations: List[SchemaViolation] = []
    for sent in extraction.sentences:
        for fact in sent.facts:
            arity = len(fact.args)

            # Rule 1: prepositional unary
            # FIX C1: 1-arg predicate containing a preposition token means a
            # second argument was welded into the verb (e.g. "work remotely from
            # home(e1)"). Only fires for arity == 1; arity == 2 with a preposition
            # in the predicate name is already correctly decomposed.
            if arity == 1:
                pred_tokens = {
                    tok.lower()
                    for tok in re.split(r"[\s_\-]+", fact.pred.strip())
                    if tok
                }
                offending = pred_tokens & _PREPOSITION_TOKENS
                if offending:
                    violations.append(SchemaViolation(
                        sentence_nl=sent.nl,
                        fact_pred=fact.pred,
                        fact_args=list(fact.args),
                        violation_type="prepositional_unary",
                        message=(
                            f"1-arg fact '{fact.pred}({fact.args[0]})' contains "
                            f"preposition(s) {sorted(offending)}, indicating a "
                            f"second argument should be reified as a separate "
                            f"entity and binary edge (Neo-Davidsonian form)."
                        ),
                    ))

            # Rule 2: high arity
            # FIX C1: ternary+ predicates trap entities inside verbs and break
            # downstream knowledge-graph ingestion.
            if arity > 2:
                violations.append(SchemaViolation(
                    sentence_nl=sent.nl,
                    fact_pred=fact.pred,
                    fact_args=list(fact.args),
                    violation_type="high_arity",
                    message=(
                        f"Fact '{fact.pred}' has arity {arity}; Neo-Davidsonian "
                        f"form permits only unary and binary predicates. "
                        f"Ternary+ predicates trap entities inside verbs and "
                        f"break downstream knowledge-graph ingestion."
                    ),
                ))

    return violations


# ── Public API ────────────────────────────────────────────────────────────────

def compile_test_suite(extraction: ProblemExtraction) -> TestSuite:
    """
    Generate the full test suite from a ProblemExtraction.

    Returns a TestSuite with positive tests (recall) and negative tests (precision).
    All FOL strings are in NLTK-compatible format.

    If the extraction violates the Neo-Davidsonian schema, the returned TestSuite
    carries the violations in suite.violations (suite.has_violations == True).
    The verifier will short-circuit to extraction_invalid=True when it sees this.
    """
    violations = validate_neo_davidsonian(extraction)  # FIX C1
    suite = _compile_from_extraction(extraction)
    suite.violations = violations  # FIX C1
    return suite


def compile_sentence_test_suite(
    sentence: SentenceExtraction,
    problem_id: str,
) -> TestSuite:
    """
    Generate a TestSuite from a single SentenceExtraction.

    Wraps the sentence in a temporary ProblemExtraction with one sentence
    and delegates to compile_test_suite.  Use this for sentence-level
    evaluation where each premise is scored against its own test suite.
    """
    wrapped = ProblemExtraction(problem_id=problem_id, sentences=[sentence])
    violations = validate_neo_davidsonian(wrapped)  # FIX C1
    suite = _compile_from_extraction(wrapped)
    suite.violations = violations  # FIX C1
    return suite
