"""
Generator output invariants.

The Master Document §5.2 specifies five invariants that every Generator
output must satisfy. This module implements each as a pure function over
(generated_fol, sentence_extraction). A Generator output that fails any
invariant is treated as a post-call refusal by the Generator module.
"""
import re
from typing import List, Optional, Tuple

from siv.schema import (
    SentenceExtraction, Entity, EntityType, Constant, ProblemExtraction,
    TestSuite,
)
from siv.fol_utils import is_valid_fol, extract_predicates
from siv.compiler import compile_sentence_test_suite, _to_camel_case
from siv.verifier import verify

_SELF_CONSISTENCY_THRESHOLD = 0.8


def check_syntactic_validity(fol_string: str) -> Tuple[bool, Optional[str]]:
    """Invariant 1: the output is valid NLTK FOL."""
    if is_valid_fol(fol_string):
        return (True, None)
    return (False, f"Output is not valid NLTK FOL: {fol_string!r}")


def check_vocabulary_containment(
    fol_string: str,
    extraction: SentenceExtraction,
) -> Tuple[bool, Optional[str]]:
    """
    Invariant 2: every predicate in the output appears in the extraction's
    facts, using the CamelCase of the fact's surface pred.
    """
    allowed = {_to_camel_case(f.pred) for f in extraction.facts}
    # Also allow entity type predicates (the CamelCase of each entity's surface)
    allowed |= {_to_camel_case(e.surface) for e in extraction.entities}
    found = extract_predicates(fol_string)
    extras = found - allowed
    if extras:
        return (False, f"Output uses predicates not in extraction: {sorted(extras)}")
    return (True, None)


def check_constant_containment(
    fol_string: str,
    extraction: SentenceExtraction,
) -> Tuple[bool, Optional[str]]:
    """
    Invariant 3: every constant in the output appears in the extraction's
    constants list by id.
    """
    allowed = {c.id for c in extraction.constants}
    # Extract constants from the FOL — non-variable lowercase atoms inside argument lists
    found = _extract_constants(fol_string)
    extras = found - allowed
    if extras:
        return (False, f"Output uses constants not in extraction: {sorted(extras)}")
    return (True, None)


def _extract_constants(fol_string: str) -> set:
    """
    Return the set of lowercase identifiers that appear as arguments but
    are not bound variables. Bound variables in NLTK format are single
    lowercase letters (x, y, z, a, b, ...) bound by 'exists' or 'all'.
    """
    # Find all arguments inside parentheses: 'Pred(arg1, arg2)'
    args = set()
    for match in re.finditer(r'[A-Z][A-Za-z0-9]*\(([^()]*)\)', fol_string):
        for raw in match.group(1).split(','):
            token = raw.strip()
            if token and token[0].islower() and len(token) > 1:
                args.add(token)
    return args


def check_quantifier_correspondence(
    fol_string: str,
    extraction: SentenceExtraction,
) -> Tuple[bool, Optional[str]]:
    """
    Invariant 4: the count of 'all x.' quantifiers in the output equals the
    count of UNIVERSAL entities in the extraction. Existential quantifiers
    are unconstrained in count because the compiler introduces fresh
    existentials during reification.
    """
    expected = sum(1 for e in extraction.entities if e.entity_type == EntityType.UNIVERSAL)
    actual = len(re.findall(r'\ball\s+\w+\.', fol_string))
    if expected != actual:
        return (False, (
            f"Universal quantifier count mismatch: expected {expected} "
            f"(from {expected} UNIVERSAL entities), got {actual}."
        ))
    return (True, None)


def check_self_consistency(
    fol_string: str,
    extraction: SentenceExtraction,
    problem_id: str = "generator_self_check",
    threshold: float = _SELF_CONSISTENCY_THRESHOLD,
) -> Tuple[bool, Optional[str]]:
    """
    Invariant 5: when the generator's output is re-scored through SIV
    against the test suite compiled from the same extraction, it must
    achieve a recall rate >= threshold (default 0.8).
    """
    suite = compile_sentence_test_suite(extraction, problem_id=problem_id)
    if suite.has_violations:
        # If the extraction has schema violations, self-consistency is moot —
        # the Generator should have refused at the pre-call stage.
        return (False, "Self-consistency check run on invalid extraction (Generator should have refused pre-call).")
    result = verify(fol_string, suite, unresolved_policy="exclude")
    if result.recall_rate < threshold:
        return (False, (
            f"Self-consistency recall {result.recall_rate:.3f} below "
            f"threshold {threshold:.2f}."
        ))
    return (True, None)


def check_all_invariants(
    fol_string: str,
    extraction: SentenceExtraction,
) -> List[str]:
    """
    Run all five invariants. Returns a list of failure reasons (empty list
    means all invariants passed).
    """
    failures = []
    for check in (
        check_syntactic_validity,
        lambda fol: check_vocabulary_containment(fol, extraction),
        lambda fol: check_constant_containment(fol, extraction),
        lambda fol: check_quantifier_correspondence(fol, extraction),
        lambda fol: check_self_consistency(fol, extraction),
    ):
        # The first check has a different signature
        if check is check_syntactic_validity:
            passed, reason = check(fol_string)
        else:
            passed, reason = check(fol_string)
        if not passed:
            failures.append(reason or "unknown failure")
    return failures
