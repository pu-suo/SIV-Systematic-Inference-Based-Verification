"""
Tests for scripts/siv_score.py — the SIV CLI Evaluator.

All tests use monkeypatching to avoid real API calls:
  - scripts.siv_score._make_frozen_client is patched to return a MagicMock
  - scripts.siv_score.extract_problem is patched to return a hand-built
    ProblemExtraction

The hand-built ProblemExtractions do not go through the LLM; they are
constructed directly from SentenceExtraction dataclasses.

Exit code checks use pytest.raises(SystemExit).
Output checks use capsys.readouterr().
"""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from siv.schema import (
    Entity, EntityType, Fact, MacroTemplate,
    ProblemExtraction, SentenceExtraction,
)

# Import the entry point once at module level (avoids re-import overhead)
from scripts.siv_score import main


# ── Hand-built ProblemExtraction fixtures ─────────────────────────────────────

def _build_simple_extraction(problem_id: str = "test_prob") -> ProblemExtraction:
    """
    Simple valid extraction: 'All dogs are animals.'

    No schema violations. Tier-1 vocabulary checks will resolve all tests
    without reaching Vampire, so no prover is needed.
    """
    sentence = SentenceExtraction(
        nl="All dogs are animals.",
        entities=[
            Entity(id="e1", surface="dogs", entity_type=EntityType.UNIVERSAL),
            Entity(id="e2", surface="animals", entity_type=EntityType.EXISTENTIAL),
        ],
        facts=[Fact(pred="are", args=["e1", "e2"], negated=False)],
        macro_template=MacroTemplate.TYPE_A,
    )
    return ProblemExtraction(problem_id=problem_id, sentences=[sentence])


def _build_invalid_extraction(problem_id: str = "test_invalid") -> ProblemExtraction:
    """
    Extraction with a prepositional_unary violation:
    'No managers work remotely from home.'

    The fact 'work remotely from home(e1)' is a 1-arg predicate containing
    the preposition 'from' — a Tenet 2 / Neo-Davidsonian violation.
    compile_sentence_test_suite will flag this and verify() will return
    extraction_invalid=True.
    """
    sentence = SentenceExtraction(
        nl="No managers work remotely from home.",
        entities=[
            Entity(id="e1", surface="managers", entity_type=EntityType.UNIVERSAL),
        ],
        facts=[Fact(pred="work remotely from home", args=["e1"], negated=True)],
        macro_template=MacroTemplate.TYPE_E,
    )
    return ProblemExtraction(problem_id=problem_id, sentences=[sentence])


# ── Input-file helpers ────────────────────────────────────────────────────────

_SIMPLE_PROBLEMS = [
    {
        "problem_id": "test_prob",
        "premises": ["All dogs are animals."],
        "candidates": {
            "gold": "all x.(Dog(x) -> Animal(x))",
            "model_a": "exists x.(Dog(x) & Animal(x))",
        },
    }
]

_INVALID_PROBLEMS = [
    {
        "problem_id": "test_invalid",
        "premises": ["No managers work remotely from home."],
        "candidates": {
            "gold": "all x.(Manager(x) -> -Work(x,home))",
        },
    }
]


def _write_input(tmp_path: Path, problems: list, filename: str = "input.json") -> str:
    p = tmp_path / filename
    p.write_text(json.dumps(problems))
    return str(p)


# ── Shared patch targets ──────────────────────────────────────────────────────
#
# We always patch _make_frozen_client so the API key check passes without a
# real key.  We patch extract_problem so no LLM call is made.  Both patches
# target the names as bound in the siv_score module's own namespace.

_PATCH_CLIENT = "scripts.siv_score._make_frozen_client"
_PATCH_EXTRACT = "scripts.siv_score.extract_problem"


# ── Test 1: Smoke test — exit code 0 ─────────────────────────────────────────

def test_smoke_exit_code_zero(tmp_path, monkeypatch):
    """
    One problem, two candidates, mocked extractor.
    main() should return normally (implying exit code 0).
    """
    input_file = _write_input(tmp_path, _SIMPLE_PROBLEMS)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with patch(_PATCH_CLIENT, return_value=MagicMock()), \
         patch(_PATCH_EXTRACT, return_value=_build_simple_extraction()):
        main([input_file])   # must not raise


# ── Test 2: JSON output shape ─────────────────────────────────────────────────

def test_json_output_shape(tmp_path, monkeypatch, capsys):
    """
    With --format json the output must parse as JSON and contain the required
    top-level keys: schema_version, problems, grand_total.
    Each premise entry must carry the full set of per-candidate keys.
    """
    input_file = _write_input(tmp_path, _SIMPLE_PROBLEMS)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with patch(_PATCH_CLIENT, return_value=MagicMock()), \
         patch(_PATCH_EXTRACT, return_value=_build_simple_extraction()):
        main([input_file, "--format", "json"])

    data = json.loads(capsys.readouterr().out)

    assert data["schema_version"] == "siv_score_report_v1"
    assert "problems" in data
    assert "grand_total" in data
    assert len(data["problems"]) == 1
    assert data["problems"][0]["problem_id"] == "test_prob"
    assert "summary" in data["problems"][0]

    premise = data["problems"][0]["premises"][0]
    assert premise["premise_index"] == 1
    assert "nl" in premise

    for cand_name in ("gold", "model_a"):
        cand = premise["candidates"][cand_name]
        for key in (
            "siv_score", "recall_rate", "precision_rate",
            "recall_total", "precision_total",
            "unresolved_recall", "unresolved_precision",
            "extraction_invalid",
            "schema_violations",
        ):
            assert key in cand, f"Missing key '{key}' in candidate '{cand_name}'"


# ── Test 3: Human output — problem ID and candidate names present ─────────────

def test_human_output_contains_expected_strings(tmp_path, monkeypatch, capsys):
    """
    With --format human the output must contain the problem ID, both candidate
    names, and the literal string 'SIV ='.
    """
    input_file = _write_input(tmp_path, _SIMPLE_PROBLEMS)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with patch(_PATCH_CLIENT, return_value=MagicMock()), \
         patch(_PATCH_EXTRACT, return_value=_build_simple_extraction()):
        main([input_file, "--format", "human"])

    out = capsys.readouterr().out
    assert "test_prob" in out
    assert "gold" in out
    assert "model_a" in out
    assert "SIV =" in out


# ── Test 4: Missing API key — exits 2 ────────────────────────────────────────

def test_missing_api_key_exits_2(tmp_path, monkeypatch, capsys):
    """
    When OPENAI_API_KEY is not set, the script must exit with code 2 and
    print a message to stderr that references OPENAI_API_KEY.
    """
    input_file = _write_input(tmp_path, _SIMPLE_PROBLEMS)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        main([input_file])

    assert exc_info.value.code == 2
    assert "OPENAI_API_KEY" in capsys.readouterr().err


# ── Test 5: Extraction-invalid — reported in both formats ────────────────────

def test_extraction_invalid_reported(tmp_path, monkeypatch, capsys):
    """
    A premise with a prepositional_unary violation must surface as:
      - JSON: extraction_invalid=True and schema_violations non-empty with
              the correct violation_type.
      - Human: status line containing 'EXTRACTION_INVALID'.
    """
    input_file = _write_input(tmp_path, _INVALID_PROBLEMS)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    invalid_extraction = _build_invalid_extraction()

    # ── JSON format ──
    with patch(_PATCH_CLIENT, return_value=MagicMock()), \
         patch(_PATCH_EXTRACT, return_value=invalid_extraction):
        main([input_file, "--format", "json", "--unresolved-policy", "exclude"])

    data = json.loads(capsys.readouterr().out)
    cand = data["problems"][0]["premises"][0]["candidates"]["gold"]
    assert cand["extraction_invalid"] is True
    assert len(cand["schema_violations"]) >= 1
    assert cand["schema_violations"][0]["violation_type"] == "prepositional_unary"

    # ── Human format ──
    with patch(_PATCH_CLIENT, return_value=MagicMock()), \
         patch(_PATCH_EXTRACT, return_value=invalid_extraction):
        main([input_file, "--format", "human", "--unresolved-policy", "exclude"])

    assert "EXTRACTION_INVALID" in capsys.readouterr().out


# ── Test 6: --problem-id filter ───────────────────────────────────────────────

def test_problem_id_filter(tmp_path, monkeypatch, capsys):
    """
    With --problem-id foo, only that problem must appear in the JSON output.
    The second problem ('bar') must be absent.
    """
    two_problems = [
        {
            "problem_id": "foo",
            "premises": ["All dogs are animals."],
            "candidates": {"gold": "all x.(Dog(x) -> Animal(x))"},
        },
        {
            "problem_id": "bar",
            "premises": ["Some cats are black."],
            "candidates": {"gold": "exists x.(Cat(x) & Black(x))"},
        },
    ]
    input_file = _write_input(tmp_path, two_problems)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    foo_extraction = _build_simple_extraction("foo")

    def _mock_extract(sentences, client=None, problem_id="unknown", **kwargs):
        return _build_simple_extraction(problem_id)

    with patch(_PATCH_CLIENT, return_value=MagicMock()), \
         patch(_PATCH_EXTRACT, side_effect=_mock_extract):
        main([input_file, "--format", "json", "--problem-id", "foo"])

    data = json.loads(capsys.readouterr().out)
    assert len(data["problems"]) == 1
    assert data["problems"][0]["problem_id"] == "foo"


# ── Test 7: Invalid input JSON — exits 2 ─────────────────────────────────────

def test_invalid_input_json_exits_2(tmp_path, monkeypatch):
    """
    A malformed input file must cause SystemExit with code 2.
    No API key or extractor patching needed — the error occurs before either.
    """
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("not valid json {{{")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with pytest.raises(SystemExit) as exc_info:
        main([str(bad_file)])

    assert exc_info.value.code == 2
