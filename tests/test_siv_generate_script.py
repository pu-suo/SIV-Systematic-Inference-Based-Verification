"""
Tests for scripts/siv_generate.py — the SIV CLI Generator.

All tests use monkeypatching to avoid real API calls:
  - scripts.siv_generate._make_frozen_client is patched to return a MagicMock
  - scripts.siv_generate.extract_problem is patched to return a hand-built extraction
  - scripts.siv_generate.generate_problem is patched to return a hand-built report

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
from siv.generator import GenerationResult, BatchGenerationReport

from scripts.siv_generate import main


# ── Input problems ────────────────────────────────────────────────────────────

_SIMPLE_PROBLEMS = [
    {
        "problem_id": "test_prob",
        "premises": ["All dogs are animals."],
        "candidates": {
            "gold": "(exists x.Dogs(x)) & all x.(Dogs(x) -> Animals(x))",
        },
    }
]

_PATCH_CLIENT = "scripts.siv_generate._make_frozen_client"
_PATCH_EXTRACT = "scripts.siv_generate.extract_problem"
_PATCH_GENERATE = "scripts.siv_generate.generate_problem"


# ── Hand-built fixtures ───────────────────────────────────────────────────────

def _build_simple_extraction(problem_id: str = "test_prob") -> ProblemExtraction:
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


def _build_successful_report(problem_id: str = "test_prob") -> BatchGenerationReport:
    return BatchGenerationReport(
        problem_id=problem_id,
        results=[
            GenerationResult(
                sentence_nl="All dogs are animals.",
                fol="(exists x.Dogs(x)) & all x.(Dogs(x) -> Animals(x))",
                refused=False,
                refusal_reason=None,
                refusal_stage=None,
            )
        ],
        num_generated=1,
        num_refused_pre_call=0,
        num_refused_post_call=0,
    )


def _build_pre_call_refusal_report(problem_id: str = "test_prob") -> BatchGenerationReport:
    return BatchGenerationReport(
        problem_id=problem_id,
        results=[
            GenerationResult(
                sentence_nl="All dogs are animals.",
                fol=None,
                refused=True,
                refusal_reason="Extraction has 1 Neo-Davidsonian violation(s): ['high_arity']",
                refusal_stage="pre_call",
            )
        ],
        num_generated=0,
        num_refused_pre_call=1,
        num_refused_post_call=0,
    )


def _build_post_call_refusal_report(problem_id: str = "test_prob") -> BatchGenerationReport:
    return BatchGenerationReport(
        problem_id=problem_id,
        results=[
            GenerationResult(
                sentence_nl="All dogs are animals.",
                fol=None,
                refused=True,
                refusal_reason="invariant_failure",
                refusal_stage="post_call",
                invariant_failures=["Output uses predicates not in extraction: ['Hairy']"],
            )
        ],
        num_generated=0,
        num_refused_pre_call=0,
        num_refused_post_call=1,
    )


def _write_input(tmp_path: Path, problems: list, filename: str = "input.json") -> str:
    p = tmp_path / filename
    p.write_text(json.dumps(problems))
    return str(p)


# ── Test 1: Smoke test — exit code 0 ─────────────────────────────────────────

def test_smoke_exit_code_zero(tmp_path, monkeypatch):
    """
    One problem, mocked extractor and generator.
    main() should return normally (implying exit code 0).
    """
    input_file = _write_input(tmp_path, _SIMPLE_PROBLEMS)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with patch(_PATCH_CLIENT, return_value=MagicMock()), \
         patch(_PATCH_EXTRACT, return_value=_build_simple_extraction()), \
         patch(_PATCH_GENERATE, return_value=_build_successful_report()):
        main([input_file])  # must not raise


# ── Test 2: JSON output shape ─────────────────────────────────────────────────

def test_json_output_shape(tmp_path, monkeypatch, capsys):
    """
    With --format json (the default) the output must parse as JSON and
    contain the required top-level keys: schema_version, problems.
    Each premise entry must carry fol, refused, refusal_reason, etc.
    """
    input_file = _write_input(tmp_path, _SIMPLE_PROBLEMS)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with patch(_PATCH_CLIENT, return_value=MagicMock()), \
         patch(_PATCH_EXTRACT, return_value=_build_simple_extraction()), \
         patch(_PATCH_GENERATE, return_value=_build_successful_report()):
        main([input_file, "--format", "json"])

    data = json.loads(capsys.readouterr().out)

    assert data["schema_version"] == "siv_generate_report_v1"
    assert "problems" in data
    assert len(data["problems"]) == 1
    assert data["problems"][0]["problem_id"] == "test_prob"

    premise = data["problems"][0]["premises"][0]
    assert premise["premise_index"] == 1
    assert "nl" in premise
    assert "fol" in premise
    assert "refused" in premise
    assert "refusal_reason" in premise
    assert "refusal_stage" in premise
    assert "invariant_failures" in premise
    assert premise["refused"] is False
    assert premise["fol"] is not None


# ── Test 3: Pre-call refusal reported correctly ───────────────────────────────

def test_pre_call_refusal_reported(tmp_path, monkeypatch, capsys):
    """
    A pre-call refusal must appear in JSON output with refused=True,
    refusal_stage='pre_call', and fol=null.
    """
    input_file = _write_input(tmp_path, _SIMPLE_PROBLEMS)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with patch(_PATCH_CLIENT, return_value=MagicMock()), \
         patch(_PATCH_EXTRACT, return_value=_build_simple_extraction()), \
         patch(_PATCH_GENERATE, return_value=_build_pre_call_refusal_report()):
        main([input_file, "--format", "json"])

    data = json.loads(capsys.readouterr().out)
    premise = data["problems"][0]["premises"][0]
    assert premise["refused"] is True
    assert premise["refusal_stage"] == "pre_call"
    assert premise["fol"] is None


# ── Test 4: Post-call refusal reported correctly ──────────────────────────────

def test_post_call_refusal_reported(tmp_path, monkeypatch, capsys):
    """
    A post-call invariant failure must appear in JSON output with
    refused=True, refusal_stage='post_call', and a non-empty
    invariant_failures list.
    """
    input_file = _write_input(tmp_path, _SIMPLE_PROBLEMS)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with patch(_PATCH_CLIENT, return_value=MagicMock()), \
         patch(_PATCH_EXTRACT, return_value=_build_simple_extraction()), \
         patch(_PATCH_GENERATE, return_value=_build_post_call_refusal_report()):
        main([input_file, "--format", "json"])

    data = json.loads(capsys.readouterr().out)
    premise = data["problems"][0]["premises"][0]
    assert premise["refused"] is True
    assert premise["refusal_stage"] == "post_call"
    assert len(premise["invariant_failures"]) >= 1


# ── Test 5: --compare-to-gold produces head-to-head report ───────────────────

def test_compare_to_gold_produces_head_to_head(tmp_path, monkeypatch, capsys):
    """
    --compare-to-gold gold must produce a JSON output where each premise
    entry contains both generated_siv and gold_siv score blocks.
    """
    input_file = _write_input(tmp_path, _SIMPLE_PROBLEMS)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with patch(_PATCH_CLIENT, return_value=MagicMock()), \
         patch(_PATCH_EXTRACT, return_value=_build_simple_extraction()), \
         patch(_PATCH_GENERATE, return_value=_build_successful_report()):
        main([input_file, "--format", "json", "--compare-to-gold", "gold"])

    data = json.loads(capsys.readouterr().out)
    premise = data["problems"][0]["premises"][0]

    # Both score blocks must be present
    assert "generated_siv" in premise, "Missing generated_siv score block"
    assert "gold_siv" in premise, "Missing gold_siv score block"

    for block_key in ("generated_siv", "gold_siv"):
        block = premise[block_key]
        assert "siv_score" in block
        assert "recall_rate" in block
        assert "precision_rate" in block


# ── Test 6: Exit code 2 on missing API key ────────────────────────────────────

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
