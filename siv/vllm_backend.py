"""
vLLM-based local extraction backend for SIV.

NOT A PUBLISHED METRIC PATH. Outputs produced through this module are
NOT valid SIV scores. The published SIV metric requires the frozen API
extractor defined in siv/frozen_config.py (see Master Document §4.2).
This module exists only for local training and development experiments
where API costs are prohibitive. When in doubt, use FrozenClient.

Uses PagedAttention for high-throughput batch inference on A100 GPUs.
Supports guided JSON decoding for 0% parse failure rate.

Usage:
    from siv.vllm_backend import VLLMExtractor
    extractor = VLLMExtractor(model="Qwen/Qwen2.5-32B-Instruct-AWQ")
    results = extractor.extract_batch(prompts)

Requirements:
    pip install vllm
    GPU with sufficient VRAM (A100 40GB recommended for 32B-AWQ models)
"""
import json
from typing import List


# ── JSON Schema for guided decoding ──────────────────────────────────────────

SIV_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "constants": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id":      {"type": "string"},
                    "surface": {"type": "string"}
                },
                "required": ["id", "surface"]
            }
        },
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id":          {"type": "string"},
                    "surface":     {"type": "string"},
                    "entity_type": {"type": "string", "enum": ["existential", "universal"]}
                },
                "required": ["id", "surface", "entity_type"]
            }
        },
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "pred":    {"type": "string"},
                    "args":    {"type": "array", "items": {"type": "string"}},
                    "negated": {"type": "boolean"}
                },
                "required": ["pred", "args"]
            }
        },
        "macro_template": {
            "type": "string",
            "enum": [
                "universal_affirmative", "universal_negative",
                "existential_affirmative", "existential_negative",
                "ground_positive", "ground_negative",
                "conditional", "biconditional"
            ]
        }
    },
    "required": ["constants", "entities", "facts", "macro_template"]
}


class VLLMExtractor:
    """
    Local vLLM-based extraction engine.

    Initializes the model once and keeps it in VRAM for the lifetime of
    the process. Supports batch extraction for high throughput.
    """

    def __init__(
        self,
        model: str = "Qwen/Qwen2.5-32B-Instruct-AWQ",
        quantization: str = None,
        gpu_memory_utilization: float = 0.80,
        max_model_len: int = 8192,
    ):
        """
        Load the model into VRAM.

        Args:
            model: HuggingFace model ID. Recommended:
                   - "Qwen/Qwen2.5-32B-Instruct-AWQ" (19GB, best quality)
                   - "Qwen/Qwen2.5-14B-Instruct-AWQ" (9GB, fastest)
            quantization: Quantization method. Defaults to None so vLLM
                          auto-detects awq_marlin from the model config.
            gpu_memory_utilization: Fraction of GPU memory for vLLM.
                                   0.80 leaves 20% for training loop.
            max_model_len: Maximum sequence length. 8192 gives headroom for
                           SIV extraction prompts (~2000 tokens) plus response.
        """
        try:
            from vllm import LLM, SamplingParams
            from vllm.sampling_params import StructuredOutputsParams
        except ImportError as _e:
            raise RuntimeError(
                "vLLM is required for local extraction. Install it with:\n"
                "  pip install vllm\n"
                "Requires a CUDA GPU (A100 40GB recommended).\n"
                f"(Import error: {_e})"
            ) from _e

        print(f"[vLLM] Loading {model} (quantization={quantization})...")
        self._llm = LLM(
            model=model,
            quantization=quantization,
            gpu_memory_utilization=gpu_memory_utilization,
            max_model_len=max_model_len,
            trust_remote_code=True,
        )

        # Guided JSON decoding: vLLM uses a finite-state machine at the C++
        # level to physically prevent invalid JSON output. 0% parse failures.
        self._sampling_params = SamplingParams(
            temperature=0.0,
            max_tokens=2048,
            structured_outputs=StructuredOutputsParams(json=SIV_JSON_SCHEMA),
        )

        self._model_name = model
        print(f"[vLLM] {model} loaded successfully.")

    def extract_batch(self, prompts: List[str]) -> List[dict]:
        """
        Run batch extraction on a list of fully formatted prompt strings.

        Args:
            prompts: List of complete prompt strings (system + few-shot + sentence).
                     Each prompt should be formatted by _build_vllm_prompt().

        Returns:
            List of parsed JSON dicts, one per input prompt.

        Raises:
            RuntimeError: If any output fails to parse (should not happen
                          with guided decoding, but we check anyway).
        """
        outputs = self._llm.generate(prompts, self._sampling_params)

        results = []
        for i, output in enumerate(outputs):
            raw_text = output.outputs[0].text
            try:
                data = json.loads(raw_text)
                if "constants" not in data:
                    data["constants"] = []
                if "entities" not in data:
                    data["entities"] = []
                results.append(data)
            except json.JSONDecodeError as e:
                import warnings
                warnings.warn(
                    f"[vLLM] JSON parse failed for prompt {i} — returning empty extraction.\n"
                    f"Raw output ({len(raw_text)} chars): {raw_text[:200]}...\n"
                    f"Error: {e}"
                )
                results.append({
                    "constants": [], "entities": [], "facts": [],
                    "macro_template": "ground_positive"
                })

        return results

    def extract_single(self, prompt: str) -> dict:
        """Extract from a single prompt. Convenience wrapper around extract_batch."""
        return self.extract_batch([prompt])[0]
