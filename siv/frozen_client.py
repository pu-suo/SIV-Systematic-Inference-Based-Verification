"""
FrozenClient: a wrapper around an OpenAI-compatible client that guarantees
every extraction call uses the pinned snapshot, seed, temperature, and
JSON Schema binding, and logs the system_fingerprint for drift detection.

Usage:
    from openai import OpenAI
    from siv.frozen_client import FrozenClient

    client = FrozenClient(OpenAI(api_key="sk-..."))
    response_dict = client.extract(
        system_prompt=SYSTEM_PROMPT,
        few_shot_messages=[...],
        user_content="COMPOUND ANALYSIS: ...\n\nSENTENCE: ...",
    )

The returned dict is already JSON-parsed and schema-conformant (due to
the JSON Schema response_format binding). Callers never see raw text.
"""
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from siv.frozen_config import (
    PRIMARY_MODEL,
    TEMPERATURE,
    SEED,
    MAX_TOKENS,
    CACHE_DIR,
    CACHE_FILE,
    get_extraction_json_schema,
    get_generation_json_schema,
)

logger = logging.getLogger("siv.frozen_client")


@dataclass
class FrozenCallMetadata:
    model: str
    system_fingerprint: Optional[str]
    cached: bool
    cache_key: str


class FrozenClient:
    def __init__(self, openai_client, model: str = PRIMARY_MODEL):
        self._client = openai_client
        self._model = model
        self._baseline_fingerprint: Optional[str] = None
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def extract(
        self,
        system_prompt: str,
        few_shot_messages: List[dict],
        user_content: str,
    ) -> tuple:
        """
        Make a frozen extraction call. Returns (parsed_dict, metadata).

        - Looks up cache first via SHA256 of (model, system_prompt,
          serialized few_shots, user_content).
        - On cache miss, calls the API with the pinned snapshot, seed,
          temperature, max_tokens, and the JSON Schema response_format.
        - Logs the system_fingerprint; warns on drift from baseline.
        - Writes the response to the cache before returning.
        """
        cache_key = self._cache_key(system_prompt, few_shot_messages, user_content)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached, FrozenCallMetadata(
                model=self._model,
                system_fingerprint=None,
                cached=True,
                cache_key=cache_key,
            )

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(few_shot_messages)
        messages.append({"role": "user", "content": user_content})

        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=TEMPERATURE,
            seed=SEED,
            max_tokens=MAX_TOKENS,
            response_format={"type": "json_schema", "json_schema": get_extraction_json_schema()},
        )

        fingerprint = getattr(response, "system_fingerprint", None)
        self._check_fingerprint_drift(fingerprint)

        raw = response.choices[0].message.content
        data = json.loads(raw)  # JSON Schema binding guarantees valid JSON

        self._cache_put(cache_key, data)
        return data, FrozenCallMetadata(
            model=self._model,
            system_fingerprint=fingerprint,
            cached=False,
            cache_key=cache_key,
        )

    def generate(
        self,
        system_prompt: str,
        few_shot_messages: List[dict],
        user_content: str,
    ) -> tuple:
        """
        Make a frozen generation call. Returns (parsed_dict, metadata) where
        parsed_dict has keys 'fol' (str or None) and 'refusal_reason' (str or None).

        Uses the generation JSON schema, not the extraction schema.
        Uses a separate cache namespace (prefix "gen:") so generation calls do not
        collide with extraction calls that happen to have the same input text.
        """
        raw_key = self._cache_key(system_prompt, few_shot_messages, user_content)
        cache_key = f"gen:{raw_key}"

        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached, FrozenCallMetadata(
                model=self._model,
                system_fingerprint=None,
                cached=True,
                cache_key=cache_key,
            )

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(few_shot_messages)
        messages.append({"role": "user", "content": user_content})

        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=TEMPERATURE,
            seed=SEED,
            max_tokens=MAX_TOKENS,
            response_format={"type": "json_schema", "json_schema": get_generation_json_schema()},
        )

        fingerprint = getattr(response, "system_fingerprint", None)
        self._check_fingerprint_drift(fingerprint)

        raw = response.choices[0].message.content
        data = json.loads(raw)  # JSON Schema binding guarantees valid JSON

        self._cache_put(cache_key, data)
        return data, FrozenCallMetadata(
            model=self._model,
            system_fingerprint=fingerprint,
            cached=False,
            cache_key=cache_key,
        )

    # ── Cache management ────────────────────────────────────────────────────

    def _cache_key(self, system_prompt, few_shot_messages, user_content) -> str:
        payload = json.dumps({
            "model": self._model,
            "system_prompt": system_prompt,
            "few_shots": few_shot_messages,
            "user_content": user_content,
        }, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str) -> Optional[dict]:
        if not CACHE_FILE.exists():
            return None
        with open(CACHE_FILE, "r") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("key") == key:
                    return entry.get("response")
        return None

    def _cache_put(self, key: str, response: dict) -> None:
        with open(CACHE_FILE, "a") as f:
            f.write(json.dumps({"key": key, "response": response}) + "\n")

    # ── Fingerprint drift detection ─────────────────────────────────────────

    def _check_fingerprint_drift(self, fingerprint: Optional[str]) -> None:
        if fingerprint is None:
            return
        if self._baseline_fingerprint is None:
            self._baseline_fingerprint = fingerprint
            logger.info("FrozenClient fingerprint baseline: %s", fingerprint)
            return
        if fingerprint != self._baseline_fingerprint:
            logger.warning(
                "FrozenClient fingerprint drift detected: baseline=%s current=%s. "
                "Reproducibility across the current session is not guaranteed.",
                self._baseline_fingerprint, fingerprint,
            )
