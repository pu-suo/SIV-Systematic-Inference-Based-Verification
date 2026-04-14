"""Tests for siv/extractor.py — mocked LLM client (no API required)."""
from __future__ import annotations

import copy
from typing import List

import pytest

from siv.extractor import _walk_formula, extract_sentence
from siv.schema import (
    AtomicFormula,
    Formula,
    SchemaViolation,
)


# ── Mock client ─────────────────────────────────────────────────────────────

class MockClient:
    """Mimics FrozenClient.extract(): returns queued extraction dicts."""

    def __init__(self, responses: List[dict]):
        self._responses = list(responses)
        self.calls: List[dict] = []

    def extract(self, system_prompt, few_shot_messages, user_content):
        self.calls.append({
            "system_prompt": system_prompt,
            "few_shot_messages": few_shot_messages,
            "user_content": user_content,
        })
        if not self._responses:
            raise RuntimeError("MockClient ran out of queued responses")
        data = self._responses.pop(0)
        return data, None


# ── Fixtures: extraction dicts ─────────────────────────────────────────────

def _good_atomic_extraction(nl="Miroslav Venhoda was a Czech choral conductor."):
    return {
        "nl": nl,
        "predicates": [{"name": "CzechChoralConductor", "arity": 1, "arg_types": ["entity"]}],
        "entities": [],
        "constants": [{"id": "miroslav", "surface": "Miroslav Venhoda", "type": "entity"}],
        "formula": {
            "atomic": {"pred": "CzechChoralConductor", "args": ["miroslav"], "negated": False},
            "quantification": None, "negation": None, "connective": None, "operands": None,
        },
    }


def _restrictor_extraction():
    return {
        "nl": "All employees who schedule meetings attend the company building.",
        "predicates": [
            {"name": "Employee", "arity": 1, "arg_types": ["entity"]},
            {"name": "Meeting", "arity": 1, "arg_types": ["entity"]},
            {"name": "Schedule", "arity": 2, "arg_types": ["entity", "entity"]},
            {"name": "Attend", "arity": 2, "arg_types": ["entity", "entity"]},
            {"name": "CompanyBuilding", "arity": 1, "arg_types": ["entity"]},
        ],
        "entities": [],
        "constants": [],
        "formula": {
            "atomic": None,
            "quantification": {
                "quantifier": "universal", "variable": "x", "var_type": "entity",
                "restrictor": [
                    {"pred": "Employee", "args": ["x"], "negated": False},
                    {"pred": "Schedule", "args": ["x", "y"], "negated": False},
                    {"pred": "Meeting", "args": ["y"], "negated": False},
                ],
                "nucleus": {
                    "atomic": None,
                    "quantification": {
                        "quantifier": "existential", "variable": "z", "var_type": "entity",
                        "restrictor": [{"pred": "CompanyBuilding", "args": ["z"], "negated": False}],
                        "nucleus": {
                            "atomic": {"pred": "Attend", "args": ["x", "z"], "negated": False},
                            "quantification": None, "negation": None, "connective": None, "operands": None,
                        },
                        "inner_quantifications": [],
                    },
                    "negation": None, "connective": None, "operands": None,
                },
                "inner_quantifications": [
                    {"quantifier": "existential", "variable": "y", "var_type": "entity"},
                ],
            },
            "negation": None, "connective": None, "operands": None,
        },
    }


def _empty_restrictor_universal_bad():
    """Universal over Dog(x) with compound nucleus — no restrictor, fails tripwire."""
    return {
        "nl": "All employees who schedule meetings attend the company building.",
        "predicates": [
            {"name": "Employee", "arity": 1, "arg_types": ["entity"]},
            {"name": "Attend", "arity": 1, "arg_types": ["entity"]},
        ],
        "entities": [],
        "constants": [],
        "formula": {
            "atomic": None,
            "quantification": {
                "quantifier": "universal", "variable": "x", "var_type": "entity",
                "restrictor": [],
                "nucleus": {
                    "atomic": None, "quantification": None, "negation": None,
                    "connective": "implies",
                    "operands": [
                        {"atomic": {"pred": "Employee", "args": ["x"], "negated": False},
                         "quantification": None, "negation": None, "connective": None, "operands": None},
                        {"atomic": {"pred": "Attend", "args": ["x"], "negated": False},
                         "quantification": None, "negation": None, "connective": None, "operands": None},
                    ],
                },
                "inner_quantifications": [],
            },
            "negation": None, "connective": None, "operands": None,
        },
    }


def _no_negation_extraction():
    """For 'No dog is a cat.' — a valid extraction that lacks any negation."""
    return {
        "nl": "No dog is a cat.",
        "predicates": [
            {"name": "Dog", "arity": 1, "arg_types": ["entity"]},
            {"name": "Cat", "arity": 1, "arg_types": ["entity"]},
        ],
        "entities": [],
        "constants": [],
        "formula": {
            "atomic": None,
            "quantification": {
                "quantifier": "universal", "variable": "x", "var_type": "entity",
                "restrictor": [{"pred": "Dog", "args": ["x"], "negated": False}],
                "nucleus": {
                    "atomic": {"pred": "Cat", "args": ["x"], "negated": False},  # NOT negated — tripwire miss
                    "quantification": None, "negation": None, "connective": None, "operands": None,
                },
                "inner_quantifications": [],
            },
            "negation": None, "connective": None, "operands": None,
        },
    }


def _with_negation_added(base: dict) -> dict:
    """Flip the nucleus atom's negated flag to True."""
    new = copy.deepcopy(base)
    new["formula"]["quantification"]["nucleus"]["atomic"]["negated"] = True
    return new


def _malformed_two_cases():
    """A Formula with two cases populated — should fail validate_extraction."""
    return {
        "nl": "Alice is tall.",
        "predicates": [{"name": "Tall", "arity": 1, "arg_types": ["entity"]}],
        "entities": [],
        "constants": [{"id": "alice", "surface": "Alice", "type": "entity"}],
        "formula": {
            "atomic": {"pred": "Tall", "args": ["alice"], "negated": False},
            "quantification": None,
            "negation": {
                "atomic": {"pred": "Tall", "args": ["alice"], "negated": False},
                "quantification": None, "negation": None, "connective": None, "operands": None,
            },
            "connective": None, "operands": None,
        },
    }


# ── Success path ────────────────────────────────────────────────────────────

def test_extract_simple_success_no_retry():
    client = MockClient([_good_atomic_extraction()])
    extraction = extract_sentence(
        "Miroslav Venhoda was a Czech choral conductor.", client
    )
    assert extraction.formula.atomic.pred == "CzechChoralConductor"
    assert len(client.calls) == 1


# ── Retry-once on validation failure ───────────────────────────────────────

def test_validation_failure_triggers_one_retry():
    bad = _malformed_two_cases()
    good = _good_atomic_extraction(nl="Alice is tall.")
    good["predicates"] = [{"name": "Tall", "arity": 1, "arg_types": ["entity"]}]
    good["constants"] = [{"id": "alice", "surface": "Alice", "type": "entity"}]
    good["formula"]["atomic"] = {"pred": "Tall", "args": ["alice"], "negated": False}
    client = MockClient([bad, good])
    extraction = extract_sentence("Alice is tall.", client)
    assert extraction.formula.atomic.pred == "Tall"
    assert len(client.calls) == 2
    # Retry prompt must include the violation context.
    assert "RETRY" in client.calls[1]["system_prompt"]


# ── Retry-once on tripwire failure ─────────────────────────────────────────

def test_restrictor_tripwire_failure_triggers_one_retry():
    bad = _empty_restrictor_universal_bad()
    good = _restrictor_extraction()
    client = MockClient([bad, good])
    extraction = extract_sentence(
        "All employees who schedule meetings attend the company building.", client,
    )
    assert extraction.formula.quantification is not None
    assert len(extraction.formula.quantification.restrictor) > 0
    assert len(client.calls) == 2


def test_negation_tripwire_failure_triggers_one_retry():
    bad = _no_negation_extraction()
    good = _with_negation_added(bad)
    client = MockClient([bad, good])
    extraction = extract_sentence("No dog is a cat.", client)
    # Confirm negation is now present in the tree.
    assert extraction.formula.quantification.nucleus.atomic.negated is True
    assert len(client.calls) == 2


# ── Both attempts fail → raise ─────────────────────────────────────────────

def test_both_retries_fail_raises_schema_violation():
    bad = _empty_restrictor_universal_bad()
    client = MockClient([bad, bad])
    with pytest.raises(SchemaViolation):
        extract_sentence(
            "All employees who schedule meetings attend the company building.", client,
        )
    assert len(client.calls) == 2


def test_no_third_retry_even_when_responses_available():
    bad = _empty_restrictor_universal_bad()
    client = MockClient([bad, bad, bad])
    with pytest.raises(SchemaViolation):
        extract_sentence(
            "All employees who schedule meetings attend the company building.", client,
        )
    # Exactly two calls — no third attempt.
    assert len(client.calls) == 2


# ── Tripwire tree-walk covers all Formula cases ────────────────────────────

def test_tripwire_finds_negation_inside_connective():
    """requires_negation must walk into connective operands."""
    # "Students are not diligent or teachers are lazy." triggers requires_negation.
    # We construct an extraction whose negation lives inside an `and`/`or`.
    data = {
        "nl": "Students are not diligent or teachers are lazy.",
        "predicates": [
            {"name": "Diligent", "arity": 1, "arg_types": ["entity"]},
            {"name": "Lazy", "arity": 1, "arg_types": ["entity"]},
        ],
        "entities": [],
        "constants": [
            {"id": "students", "surface": "students", "type": "entity"},
            {"id": "teachers", "surface": "teachers", "type": "entity"},
        ],
        "formula": {
            "atomic": None, "quantification": None, "negation": None,
            "connective": "or",
            "operands": [
                {"atomic": {"pred": "Diligent", "args": ["students"], "negated": True},
                 "quantification": None, "negation": None, "connective": None, "operands": None},
                {"atomic": {"pred": "Lazy", "args": ["teachers"], "negated": False},
                 "quantification": None, "negation": None, "connective": None, "operands": None},
            ],
        },
    }
    client = MockClient([data])
    extraction = extract_sentence(
        "Students are not diligent or teachers are lazy.", client,
    )
    # Pre-analyzer flagged requires_negation (lemma "not" / neg dep), and the
    # extraction satisfies it because the tripwire walker descended into the
    # `or` operand. Single call; no retry.
    assert len(client.calls) == 1
    assert extraction.formula.connective == "or"


def test_tripwire_finds_negation_inside_quantification_restrictor():
    """requires_negation tree-walker must descend into restrictor atoms."""
    data = {
        "nl": "No student who has not studied passes.",
        "predicates": [
            {"name": "Student", "arity": 1, "arg_types": ["entity"]},
            {"name": "Studied", "arity": 1, "arg_types": ["entity"]},
            {"name": "Passes", "arity": 1, "arg_types": ["entity"]},
        ],
        "entities": [],
        "constants": [],
        "formula": {
            "atomic": None,
            "quantification": {
                "quantifier": "universal", "variable": "x", "var_type": "entity",
                "restrictor": [
                    {"pred": "Student", "args": ["x"], "negated": False},
                    {"pred": "Studied", "args": ["x"], "negated": True},  # negation deep in restrictor
                ],
                "nucleus": {
                    "atomic": {"pred": "Passes", "args": ["x"], "negated": False},
                    "quantification": None, "negation": None, "connective": None, "operands": None,
                },
                "inner_quantifications": [],
            },
            "negation": None, "connective": None, "operands": None,
        },
    }
    client = MockClient([data])
    extract_sentence("No student who has not studied passes.", client)
    assert len(client.calls) == 1


# ── _walk_formula visits every subtree ─────────────────────────────────────

def test_walk_formula_visits_every_node():
    atom_a = AtomicFormula(pred="A", args=["x"], negated=False)
    atom_b = AtomicFormula(pred="B", args=["x"], negated=False)
    f = Formula(connective="and", operands=[
        Formula(atomic=atom_a),
        Formula(negation=Formula(atomic=atom_b)),
    ])
    seen = []
    _walk_formula(f, lambda n: seen.append(n))
    kinds = [
        "root",
        "op0-atom" if seen[1].atomic is not None else "op0-other",
        "op1-negation" if seen[2].negation is not None else "op1-other",
        "op1-inner-atom" if seen[3].atomic is not None else "op1-other",
    ]
    assert kinds == ["root", "op0-atom", "op1-negation", "op1-inner-atom"]
