import json
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from siv.frozen_client import FrozenClient
from siv.frozen_config import PRIMARY_MODEL, SEED, TEMPERATURE


@dataclass
class _StubChoice:
    message: object


@dataclass
class _StubMessage:
    content: str


@dataclass
class _StubResponse:
    choices: list
    system_fingerprint: str = "fp_test_baseline"


def _make_stub_client(response_json: dict, fingerprint: str = "fp_test_baseline"):
    stub = MagicMock()
    stub.chat.completions.create.return_value = _StubResponse(
        choices=[_StubChoice(message=_StubMessage(content=json.dumps(response_json)))],
        system_fingerprint=fingerprint,
    )
    return stub


def _minimal_response():
    """Minimal SentenceExtraction-shaped response stub.

    FrozenClient does not validate the response against the schema; it only
    parses JSON and caches. Shape just needs to be JSON-parseable.
    """
    return {
        "nl": "Alice is tall.",
        "predicates": [{"name": "Tall", "arity": 1, "arg_types": ["entity"]}],
        "entities": [],
        "constants": [{"id": "alice", "surface": "Alice", "type": "entity"}],
        "formula": {
            "atomic": {"pred": "Tall", "args": ["alice"], "negated": False},
            "quantification": None,
            "negation": None,
            "connective": None,
            "operands": None,
        },
    }


def test_frozen_client_pins_model_seed_temperature(tmp_path, monkeypatch):
    monkeypatch.setattr("siv.frozen_client.CACHE_FILE", tmp_path / "cache.jsonl")
    monkeypatch.setattr("siv.frozen_client.CACHE_DIR", tmp_path)

    stub = _make_stub_client(_minimal_response())
    fc = FrozenClient(stub)
    data, meta = fc.extract("sys", [], "user content")

    call_kwargs = stub.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == PRIMARY_MODEL
    assert call_kwargs["seed"] == SEED
    assert call_kwargs["temperature"] == TEMPERATURE
    assert call_kwargs["response_format"]["type"] == "json_schema"
    assert meta.cached is False
    assert meta.model == PRIMARY_MODEL


def test_frozen_client_cache_hit_skips_api(tmp_path, monkeypatch):
    monkeypatch.setattr("siv.frozen_client.CACHE_FILE", tmp_path / "cache.jsonl")
    monkeypatch.setattr("siv.frozen_client.CACHE_DIR", tmp_path)

    stub = _make_stub_client(_minimal_response())
    fc = FrozenClient(stub)

    _, meta1 = fc.extract("sys", [], "user content")
    assert meta1.cached is False
    assert stub.chat.completions.create.call_count == 1

    _, meta2 = fc.extract("sys", [], "user content")
    assert meta2.cached is True
    assert stub.chat.completions.create.call_count == 1  # not called again


def test_frozen_client_cache_miss_on_different_user_content(tmp_path, monkeypatch):
    monkeypatch.setattr("siv.frozen_client.CACHE_FILE", tmp_path / "cache.jsonl")
    monkeypatch.setattr("siv.frozen_client.CACHE_DIR", tmp_path)

    stub = _make_stub_client(_minimal_response())
    fc = FrozenClient(stub)
    fc.extract("sys", [], "content A")
    fc.extract("sys", [], "content B")
    assert stub.chat.completions.create.call_count == 2


def test_frozen_client_logs_fingerprint_drift(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr("siv.frozen_client.CACHE_FILE", tmp_path / "cache.jsonl")
    monkeypatch.setattr("siv.frozen_client.CACHE_DIR", tmp_path)

    stub = MagicMock()
    responses = [
        _StubResponse(
            choices=[_StubChoice(message=_StubMessage(content=json.dumps(_minimal_response())))],
            system_fingerprint="fp_original",
        ),
        _StubResponse(
            choices=[_StubChoice(message=_StubMessage(content=json.dumps(_minimal_response())))],
            system_fingerprint="fp_drifted",
        ),
    ]
    stub.chat.completions.create.side_effect = responses
    fc = FrozenClient(stub)
    with caplog.at_level("WARNING", logger="siv.frozen_client"):
        fc.extract("sys", [], "content A")
        fc.extract("sys", [], "content B")
    assert any("drift detected" in r.message for r in caplog.records)


def test_frozen_config_has_no_aliases():
    """Task 05: the primary model must be a snapshot, not an alias."""
    from siv.frozen_config import PRIMARY_MODEL
    # Snapshots contain a date; aliases don't.
    assert "-20" in PRIMARY_MODEL, (
        f"PRIMARY_MODEL={PRIMARY_MODEL} looks like an alias, not a snapshot. "
        "Pin a dated snapshot."
    )
