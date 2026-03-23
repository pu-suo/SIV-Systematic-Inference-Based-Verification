"""
Stage 2: Enriched LLM Extraction

Takes a sentence + the Stage 1 compound analyses and calls an LLM to extract
entities and facts into the minimal JSON schema defined in schema.py.

The compound analyses are injected into the prompt as structured context,
guiding the LLM's split/keep decisions with objective evidence.

The LLM also identifies the macro_template (one of the 8 Aristotelian forms).

Exactly one backend must be provided per call:
  - client: an OpenAI-compatible API client (OpenAI, DeepSeek, Together AI)
  - vllm_extractor: a VLLMExtractor instance for local GPU batch inference

No fallbacks. If neither backend is provided, a RuntimeError is raised.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List

from siv.schema import (
    CompoundAnalysis, Constant, Entity, EntityType, Fact,
    MacroTemplate, ProblemExtraction, SentenceExtraction,
)
from siv.pre_analyzer import analyze_sentence, format_analyses_for_prompt

# ── Paths ─────────────────────────────────────────────────────────────────────

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


# ── Prompt construction ───────────────────────────────────────────────────────

def _load_system_prompt() -> str:
    path = _PROMPTS_DIR / "extraction_system.txt"
    if path.exists():
        return path.read_text()
    return (
        "Extract entities and facts from the sentence into JSON with keys: "
        "constants (list of {id, surface}), "
        "entities (list of {id, surface, entity_type}), "
        "facts (list of {pred, args, negated}), macro_template. "
        "Output JSON only."
    )


def _load_examples() -> List[dict]:
    path = _PROMPTS_DIR / "extraction_examples.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []


# Cache prompt files once at module load — avoids N disk reads per problem
_SYSTEM_PROMPT: str = _load_system_prompt()
_EXAMPLES: List[dict] = _load_examples()


def _build_prompt(
    sentence: str,
    compound_analyses: List[CompoundAnalysis],
) -> List[dict]:
    """
    Build the chat messages list for the LLM call.

    Structure (OpenAI chat format):
      [0] system: full instructions
      [1-2*N] user/assistant: few-shot examples (1 pair per example)
      [-1] user: compound analysis block + sentence to extract
    """
    messages: List[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]

    for ex in _EXAMPLES:
        compound_block = ex.get("compound_analysis", "(no compound modifiers detected)")
        user_content = (
            f"COMPOUND ANALYSIS:\n{compound_block}\n\n"
            f"SENTENCE: {ex['sentence']}"
        )
        messages.append({"role": "user", "content": user_content})
        messages.append({"role": "assistant", "content": json.dumps(ex["response"])})

    analysis_block = format_analyses_for_prompt(compound_analyses)
    final_user = (
        f"COMPOUND ANALYSIS:\n{analysis_block}\n\n"
        f"SENTENCE: {sentence}"
    )
    messages.append({"role": "user", "content": final_user})
    return messages


def _build_vllm_prompt(
    sentence: str,
    compound_analyses: List[CompoundAnalysis],
) -> str:
    """
    Build a single prompt string for vLLM (not chat messages).

    Concatenates system prompt + few-shot examples + the target sentence
    into a single string with <|im_start|> role delimiters that instruct-tuned
    models (Qwen, DeepSeek) understand.
    """
    analysis_block = format_analyses_for_prompt(compound_analyses)

    parts = [f"<|im_start|>system\n{_SYSTEM_PROMPT}<|im_end|>"]

    for ex in _EXAMPLES:
        compound_block = ex.get("compound_analysis", "(no compound modifiers detected)")
        user_content = (
            f"COMPOUND ANALYSIS:\n{compound_block}\n\n"
            f"SENTENCE: {ex['sentence']}"
        )
        parts.append(f"<|im_start|>user\n{user_content}<|im_end|>")
        parts.append(f"<|im_start|>assistant\n{json.dumps(ex['response'])}<|im_end|>")

    final_user = (
        f"COMPOUND ANALYSIS:\n{analysis_block}\n\n"
        f"SENTENCE: {sentence}"
    )
    parts.append(f"<|im_start|>user\n{final_user}<|im_end|>")
    parts.append("<|im_start|>assistant\n")

    return "\n".join(parts)


# ── Response parsing ──────────────────────────────────────────────────────────

def _parse_response(response_text: str) -> dict:
    """
    Parse and validate the LLM JSON response.
    Strips markdown fencing if present.
    Raises ValueError on schema violations.
    Accepts both the old single-list format and the new two-list format.
    """
    text = response_text.strip()
    # Strip ```json ... ``` or ``` ... ```
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)

    # New two-list format: must have "entities" or "constants" (or both)
    # Old format: must have "entities"
    if "constants" not in data and "entities" not in data:
        raise ValueError("Missing both 'constants' and 'entities' lists")
    if "entities" not in data:
        data["entities"] = []
    if "constants" not in data:
        data["constants"] = []
    if not isinstance(data.get("entities"), list):
        raise ValueError("Missing or invalid 'entities' list")
    if not isinstance(data.get("constants"), list):
        raise ValueError("Missing or invalid 'constants' list")
    if not isinstance(data.get("facts"), list):
        raise ValueError("Missing or invalid 'facts' list")
    for e in data["entities"]:
        if "id" not in e or "surface" not in e:
            raise ValueError(f"Entity missing id/surface: {e}")
    for c in data["constants"]:
        if "id" not in c or "surface" not in c:
            raise ValueError(f"Constant missing id/surface: {c}")
    for f in data["facts"]:
        if "pred" not in f or "args" not in f:
            raise ValueError(f"Fact missing pred/args: {f}")
    return data


def _dict_to_extraction(
    nl: str,
    data: dict,
    compound_analyses: List[CompoundAnalysis],
) -> SentenceExtraction:
    """Convert validated LLM response dict → SentenceExtraction."""
    etype_map = {
        "existential": EntityType.EXISTENTIAL,
        "universal":   EntityType.UNIVERSAL,
        # backward compat: old prompts may still emit "constant" in entities
        "constant":    EntityType.CONSTANT,
    }

    # New-style: items in data["constants"] → Constant objects
    constants = [
        Constant(id=c["id"], surface=c["surface"])
        for c in data.get("constants", [])
    ]

    # Items in data["entities"] with entity_type="constant" → also Constant
    # Items with existential/universal → Entity
    entities = []
    for e in data.get("entities", []):
        etype_raw = e.get("entity_type", "existential")
        if etype_raw == "constant":
            # Route to constants list (old-format LLM output)
            constants.append(Constant(id=e["id"], surface=e["surface"]))
        else:
            entities.append(Entity(
                id=e["id"],
                surface=e["surface"],
                entity_type=etype_map.get(etype_raw, EntityType.EXISTENTIAL),
            ))

    facts = [
        Fact(
            pred=f["pred"],
            args=f["args"],
            negated=bool(f.get("negated", False)),
        )
        for f in data["facts"]
    ]
    raw_mt = data.get("macro_template", "ground_positive")
    try:
        macro = MacroTemplate(raw_mt)
    except ValueError:
        macro = MacroTemplate.GROUND_POSITIVE

    return SentenceExtraction(
        nl=nl,
        entities=entities,
        facts=facts,
        macro_template=macro,
        compound_analyses=compound_analyses,
        constants=constants,
    )


# ── LLM extraction ────────────────────────────────────────────────────────────

def extract_sentence(
    sentence: str,
    compound_analyses: List[CompoundAnalysis],
    client=None,
    model: str = "gpt-4o",
    vllm_extractor=None,
) -> SentenceExtraction:
    """
    Extract entities, constants, and facts from one sentence.

    Exactly one backend must be provided:
      - client: an OpenAI-compatible API client (OpenAI, DeepSeek, Together AI)
      - vllm_extractor: a VLLMExtractor instance for local GPU inference

    Raises RuntimeError if neither backend is provided. No fallbacks.
    """
    if vllm_extractor is not None:
        prompt = _build_vllm_prompt(sentence, compound_analyses)
        data = vllm_extractor.extract_single(prompt)
        return _dict_to_extraction(sentence, data, compound_analyses)

    if client is not None:
        messages = _build_prompt(sentence, compound_analyses)
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.0,
            max_tokens=1200,
        )
        raw = response.choices[0].message.content
        data = _parse_response(raw)
        return _dict_to_extraction(sentence, data, compound_analyses)

    raise RuntimeError(
        "No extraction backend configured. Provide either:\n"
        "  - client: an OpenAI-compatible API client, OR\n"
        "  - vllm_extractor: a VLLMExtractor instance for local GPU inference.\n"
        "See notebook Cell 2 for configuration."
    )


def extract_problem(
    problem_sentences: List[str],
    client=None,
    model: str = "gpt-4o",
    problem_id: str = "unknown",
    max_workers: int = 5,
    vllm_extractor=None,
) -> ProblemExtraction:
    """
    Extract all sentences in a FOLIO problem.

    When vllm_extractor is provided, uses batch inference (all sentences in one
    GPU pass). When client is provided, uses parallel API calls via
    ThreadPoolExecutor. Raises RuntimeError if neither backend is provided.
    """
    if client is None and vllm_extractor is None:
        raise RuntimeError(
            "No extraction backend configured. Provide either client or vllm_extractor."
        )

    # Stage 1: pre-analysis for all sentences
    all_analyses = [analyze_sentence(sent) for sent in problem_sentences]

    if vllm_extractor is not None:
        # Batch mode: build all prompts, run in one vLLM pass
        prompts = [
            _build_vllm_prompt(sent, analyses)
            for sent, analyses in zip(problem_sentences, all_analyses)
        ]
        batch_results = vllm_extractor.extract_batch(prompts)
        raw_extractions = [
            _dict_to_extraction(sent, data, analyses)
            for sent, data, analyses in zip(problem_sentences, batch_results, all_analyses)
        ]
    else:
        # API mode: parallel calls via ThreadPoolExecutor
        def _extract_one(args) -> SentenceExtraction:
            sent, analyses = args
            return extract_sentence(sent, analyses, client=client, model=model)

        workers = min(max_workers, len(problem_sentences)) if problem_sentences else 1
        with ThreadPoolExecutor(max_workers=workers) as pool:
            raw_extractions = list(pool.map(_extract_one, zip(problem_sentences, all_analyses)))

    # Sequential entity-ID deduplication (stateful — must not be parallelised)
    sentence_extractions: List[SentenceExtraction] = []
    entity_registry: dict = {}    # surface (lower) → canonical id
    constant_registry: dict = {}  # surface (lower) → canonical id
    id_counter = {"e": 1, "c": 1}

    for extraction in raw_extractions:
        # Remap entity IDs
        id_remap: dict = {}
        new_entities = []
        for ent in extraction.entities:
            key = ent.surface.lower()
            if key in entity_registry:
                new_id = entity_registry[key]
            else:
                prefix = "e"
                new_id = f"{prefix}{id_counter[prefix]}"
                id_counter[prefix] += 1
                entity_registry[key] = new_id
            id_remap[ent.id] = new_id
            new_entities.append(
                Entity(id=new_id, surface=ent.surface, entity_type=ent.entity_type)
            )

        # Remap constant IDs — use camelCase surface as canonical id when possible
        new_constants = []
        for const in extraction.constants:
            key = const.surface.lower()
            if key in constant_registry:
                new_id = constant_registry[key]
            else:
                # Use camelCase id from const.id or derive from surface
                new_id = const.id
                constant_registry[key] = new_id
            id_remap[const.id] = new_id
            new_constants.append(Constant(id=new_id, surface=const.surface))

        # Remap fact args
        new_facts = []
        for fact in extraction.facts:
            new_args = [id_remap.get(a, a) for a in fact.args]
            new_facts.append(Fact(pred=fact.pred, args=new_args, negated=fact.negated))

        sentence_extractions.append(
            SentenceExtraction(
                nl=extraction.nl,
                entities=new_entities,
                facts=new_facts,
                macro_template=extraction.macro_template,
                compound_analyses=extraction.compound_analyses,
                constants=new_constants,
            )
        )

    return ProblemExtraction(problem_id=problem_id, sentences=sentence_extractions)
