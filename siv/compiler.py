"""
Stage 3: Deterministic FOL Test Compilation

Takes a ProblemExtraction (entities + facts + templates) and generates
positive and negative FOL unit tests in NLTK format.

Test generation rules by arity:
  1-arg fact → exists x.Pred(x)  +  exists x.(EntityType(x) & Pred(x))
  2-arg fact → Pred(c1, c2)  (if both are constants)  or
               exists x.(exists y.(SubjType(x) & ObjType(y) & Pred(x,y)))
  3-arg fact → Pred(c1, c2, c3)  or  exists x.(Pred(x, c2, c3))

Negative tests: substitute each 1-arg predicate with its antonym from the
perturbation map (or a synthetic "Non<Pred>" if absent).

All FOL strings use NLTK-compatible ASCII format:
  exists x.(P(x) & Q(x))
  all x.(P(x) -> Q(x))
  -P(x)
"""
import json
import re
from pathlib import Path
from typing import List, Optional

from siv.schema import (
    Entity, EntityType, Fact, MacroTemplate,
    ProblemExtraction, SentenceExtraction, TestSuite, UnitTest,
)

# ── Perturbation map ──────────────────────────────────────────────────────────

_DATA_DIR = Path(__file__).parent.parent / "data"
_PERTURBATION_MAP: Optional[dict] = None


def _load_perturbation_map() -> dict:
    global _PERTURBATION_MAP
    if _PERTURBATION_MAP is not None:
        return _PERTURBATION_MAP
    path = _DATA_DIR / "perturbation_map.json"
    if path.exists():
        with open(path) as f:
            _PERTURBATION_MAP = json.load(f)
    else:
        _PERTURBATION_MAP = {}
    return _PERTURBATION_MAP


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


def _get_perturbation(pred_camel: str) -> str:
    """Return the antonym CamelCase predicate, or 'Non<Pred>' if unknown."""
    pm = _load_perturbation_map()
    return pm.get(pred_camel, f"Non{pred_camel}")


# ── Entity lookup helpers ─────────────────────────────────────────────────────

def _id_to_entity(extraction: ProblemExtraction) -> dict:
    """Return a dict mapping entity id → Entity."""
    return {e.id: e for e in extraction.all_entities}


def _is_constant(eid: str, id_map: dict) -> bool:
    ent = id_map.get(eid)
    return ent is not None and ent.entity_type == EntityType.CONSTANT


# ── Vocabulary tests ──────────────────────────────────────────────────────────

def _compile_vocabulary_tests(extraction: ProblemExtraction) -> List[UnitTest]:
    """
    For every unique predicate in the extraction, generate an existence test:
      exists x.Pred(x)     (arity-1)
      exists x.(exists y.Pred(x,y))   (arity-2)
    These are the cheapest tests — resolved at Tier 1 (vocabulary check).
    """
    seen: set = set()
    tests: List[UnitTest] = []

    for fact in extraction.all_facts:
        pred = _fact_pred(fact)
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
    For each fact, generate tests that the predicate applies to the
    correct entity / constant.

    1-arg fact on existential entity e1 (type="tree", pred="tall"):
      → exists x.(Tree(x) & Tall(x))

    1-arg fact on constant c1 (pred="queen"):
      → Queen(nancy)   (grounded)

    2-arg fact both constants (pred="directed", args=["lanaWilson","afterTiller"]):
      → Directed(lanaWilson, afterTiller)
      → exists x.(exists y.Directed(x,y))

    2-arg fact with at least one existential:
      → exists x.(exists y.(SubjType(x) & ObjType(y) & Pred(x,y)))
    """
    id_map = _id_to_entity(extraction)
    tests: List[UnitTest] = []

    for sent in extraction.sentences:
        sent_entity_ids = {e.id for e in sent.entities}

        for fact in sent.facts:
            pred = _fact_pred(fact)
            args = fact.args
            arity = len(args)

            if arity == 1:
                eid = args[0]
                if _is_constant(eid, id_map):
                    # Grounded: Pred(constant)
                    fol = _to_fol_string(pred, [eid], fact.negated)
                    tests.append(UnitTest(fol_string=fol, test_type="binding",
                                          is_positive=True, source_fact=fact))
                else:
                    ent = id_map.get(eid)
                    if ent:
                        ent_pred = _entity_pred(ent)
                        if ent.entity_type == EntityType.UNIVERSAL:
                            # all x.(EntType(x) -> Pred(x))
                            inner = f"all x.({ent_pred}(x) -> {_to_fol_string(pred, ['x'], fact.negated)})"
                        else:
                            # exists x.(EntType(x) & Pred(x))
                            inner = (
                                f"exists x.({ent_pred}(x) & "
                                f"{_to_fol_string(pred, ['x'], fact.negated)})"
                            )
                        tests.append(UnitTest(fol_string=inner, test_type="binding",
                                              is_positive=True, source_fact=fact))

            elif arity == 2:
                subj_id, obj_id = args[0], args[1]
                if _is_constant(subj_id, id_map) and _is_constant(obj_id, id_map):
                    fol = _to_fol_string(pred, [subj_id, obj_id], fact.negated)
                    tests.append(UnitTest(fol_string=fol, test_type="binding",
                                          is_positive=True, source_fact=fact))
                else:
                    subj_ent = id_map.get(subj_id)
                    obj_ent  = id_map.get(obj_id)
                    parts = []
                    if subj_ent:
                        parts.append(f"{_entity_pred(subj_ent)}(x)")
                    if obj_ent:
                        parts.append(f"{_entity_pred(obj_ent)}(y)")
                    parts.append(_to_fol_string(pred, ["x", "y"], fact.negated))
                    conjunction = " & ".join(parts)
                    fol = f"exists x.(exists y.({conjunction}))"
                    tests.append(UnitTest(fol_string=fol, test_type="binding",
                                          is_positive=True, source_fact=fact))

    return tests


# ── Macro template tests ──────────────────────────────────────────────────────

def _compile_macro_tests(extraction: ProblemExtraction) -> List[UnitTest]:
    """
    For each sentence whose macro_template is informative, generate a
    structural FOL test matching the Aristotelian form.
    """
    id_map = _id_to_entity(extraction)
    tests: List[UnitTest] = []

    for sent in extraction.sentences:
        mt = sent.macro_template
        facts = sent.facts
        entities = sent.entities

        if not entities or not facts:
            continue

        # Pick the first entity as the "subject" for the macro
        subj_ent = entities[0]
        subj_pred = _entity_pred(subj_ent)

        # For TYPE_A / TYPE_E we need a second predicate (the "predicate" of the rule)
        prop_facts = [f for f in facts if len(f.args) == 1]
        if not prop_facts:
            continue
        obj_fact = prop_facts[-1]   # last 1-arg fact as the "consequent"
        obj_pred = _fact_pred(obj_fact)

        if mt == MacroTemplate.TYPE_A:
            fol = f"all x.({subj_pred}(x) -> {obj_pred}(x))"
            tests.append(UnitTest(fol_string=fol, test_type="entailment",
                                  is_positive=True, source_fact=obj_fact))

        elif mt == MacroTemplate.TYPE_E:
            fol = f"all x.({subj_pred}(x) -> -{obj_pred}(x))"
            tests.append(UnitTest(fol_string=fol, test_type="entailment",
                                  is_positive=True, source_fact=obj_fact))

        elif mt == MacroTemplate.TYPE_I:
            fol = f"exists x.({subj_pred}(x) & {obj_pred}(x))"
            tests.append(UnitTest(fol_string=fol, test_type="entailment",
                                  is_positive=True, source_fact=obj_fact))

        elif mt == MacroTemplate.TYPE_O:
            fol = f"exists x.({subj_pred}(x) & -{obj_pred}(x))"
            tests.append(UnitTest(fol_string=fol, test_type="entailment",
                                  is_positive=True, source_fact=obj_fact))

        elif mt == MacroTemplate.GROUND_POSITIVE:
            for fact in prop_facts:
                eid = fact.args[0]
                if _is_constant(eid, id_map):
                    fol = _to_fol_string(_fact_pred(fact), [eid])
                    tests.append(UnitTest(fol_string=fol, test_type="entailment",
                                          is_positive=True, source_fact=fact))

        elif mt == MacroTemplate.GROUND_NEGATIVE:
            for fact in prop_facts:
                eid = fact.args[0]
                if _is_constant(eid, id_map):
                    fol = _to_fol_string(_fact_pred(fact), [eid], negated=True)
                    tests.append(UnitTest(fol_string=fol, test_type="entailment",
                                          is_positive=True, source_fact=fact))

        elif mt == MacroTemplate.CONDITIONAL and len(prop_facts) >= 2:
            ant_pred = _fact_pred(prop_facts[0])
            con_pred = _fact_pred(prop_facts[1])
            fol = f"all x.({ant_pred}(x) -> {con_pred}(x))"
            tests.append(UnitTest(fol_string=fol, test_type="entailment",
                                  is_positive=True, source_fact=prop_facts[1]))

        elif mt == MacroTemplate.BICONDITIONAL and len(prop_facts) >= 2:
            ant_pred = _fact_pred(prop_facts[0])
            con_pred = _fact_pred(prop_facts[1])
            fol = f"all x.({ant_pred}(x) <-> {con_pred}(x))"
            tests.append(UnitTest(fol_string=fol, test_type="entailment",
                                  is_positive=True, source_fact=prop_facts[1]))

    return tests


# ── Negative (contrastive) tests ──────────────────────────────────────────────

def _compile_negative_tests(extraction: ProblemExtraction) -> List[UnitTest]:
    """
    Contrastive precision tests.

    For each 1-arg property fact, generate a test using the antonym predicate.
    The candidate FOL must NOT entail these (otherwise it hallucinates).
    """
    id_map = _id_to_entity(extraction)
    tests: List[UnitTest] = []
    seen: set = set()

    for fact in extraction.all_facts:
        if len(fact.args) != 1:
            continue
        pred = _fact_pred(fact)
        perturbed = _get_perturbation(pred)
        if perturbed in seen:
            continue
        seen.add(perturbed)

        eid = fact.args[0]
        ent = id_map.get(eid)
        if ent is None:
            continue
        ent_pred = _entity_pred(ent)

        if ent.entity_type == EntityType.UNIVERSAL:
            fol = f"all x.({ent_pred}(x) -> {perturbed}(x))"
        else:
            fol = f"exists x.({ent_pred}(x) & {perturbed}(x))"

        tests.append(UnitTest(fol_string=fol, test_type="contrastive",
                              is_positive=False, source_fact=fact))

    return tests


# ── Public API ────────────────────────────────────────────────────────────────

def compile_test_suite(extraction: ProblemExtraction) -> TestSuite:
    """
    Generate the full test suite from a ProblemExtraction.

    Returns a TestSuite with positive tests (recall) and negative tests (precision).
    All FOL strings are in NLTK-compatible format.
    """
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
