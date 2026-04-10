"""
Stage 2: Enriched LLM Extraction

Takes a sentence + the Stage 1 compound analyses and calls an LLM to extract
entities and facts into the minimal JSON schema defined in schema.py.

The compound analyses are injected into the prompt as structured context,
guiding the LLM's split/keep decisions with objective evidence.

The LLM also identifies the macro_template (one of the 8 Aristotelian forms).

Exactly one backend must be provided per call:
  - client: an OpenAI-compatible API client (OpenAI, DeepSeek, Together AI),
            or a FrozenClient instance. Raw API clients are automatically
            wrapped in FrozenClient so every call uses the pinned snapshot,
            seed, and JSON Schema binding.
  - vllm_extractor: a VLLMExtractor instance for local GPU batch inference.
            NOTE: Outputs produced via vllm_extractor are NOT published SIV
            scores. Published scores require the frozen API extractor
            (FrozenClient).

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
from siv.frozen_client import FrozenClient

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


def _build_vllm_prompt(
    sentence: str,
    compound_analyses: List[CompoundAnalysis],
) -> str:
    """
    Build a single prompt string for vLLM (not chat messages).

    Concatenates system prompt + few-shot examples + the target sentence
    into a single string with <|im_start|> role delimiters that instruct-tuned
    models (Qwen, DeepSeek) understand.

    NOTE: Outputs produced via vllm_extractor are NOT published SIV scores.
    Published scores require the frozen API extractor (FrozenClient).
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
    vllm_extractor=None,
) -> SentenceExtraction:
    """
    Extract entities, constants, and facts from one sentence.

    Exactly one backend must be provided:
      - client: an OpenAI-compatible API client or a FrozenClient instance.
                Raw clients are automatically wrapped in FrozenClient so
                every call uses the pinned snapshot, seed, and JSON Schema
                binding from siv/frozen_config.py.
      - vllm_extractor: a VLLMExtractor instance for local GPU inference.
                NOTE: Outputs produced via vllm_extractor are NOT published
                SIV scores. Published scores require FrozenClient.

    Raises RuntimeError if neither backend is provided. No fallbacks.
    """
    if vllm_extractor is not None:
        prompt = _build_vllm_prompt(sentence, compound_analyses)
        data = vllm_extractor.extract_single(prompt)
        return _dict_to_extraction(sentence, data, compound_analyses)

    if client is not None:
        if not isinstance(client, FrozenClient):
            client = FrozenClient(client)
        system_prompt = _SYSTEM_PROMPT
        few_shot_messages = []
        for ex in _EXAMPLES:
            compound_block = ex.get("compound_analysis", "(no compound modifiers detected)")
            few_shot_messages.append({
                "role": "user",
                "content": f"COMPOUND ANALYSIS:\n{compound_block}\n\nSENTENCE: {ex['sentence']}",
            })
            few_shot_messages.append({
                "role": "assistant",
                "content": json.dumps(ex["response"]),
            })
        analysis_block = format_analyses_for_prompt(compound_analyses)
        user_content = f"COMPOUND ANALYSIS:\n{analysis_block}\n\nSENTENCE: {sentence}"
        data, _meta = client.extract(system_prompt, few_shot_messages, user_content)
        return _dict_to_extraction(sentence, data, compound_analyses)

    raise RuntimeError(
        "No extraction backend configured. Provide either:\n"
        "  - client: an OpenAI-compatible API client, OR\n"
        "  - vllm_extractor: a VLLMExtractor instance for local GPU inference.\n"
        "See notebook Cell 2 for configuration."
    )


def extract_sentences_batch(
    sentences: List[str],
    compound_analyses_list: List[List[CompoundAnalysis]],
    client=None,
    vllm_extractor=None,
) -> List[SentenceExtraction]:
    """
    Batch-extract multiple sentences at once.

    When vllm_extractor is provided: builds ALL prompts, sends them in a
    SINGLE vllm_extractor.extract_batch() call, parses all results.

    When client is provided: uses ThreadPoolExecutor for parallel API calls.
    Raw clients are automatically wrapped in FrozenClient.

    Returns a list of SentenceExtraction in the same order as input.
    """
    if client is None and vllm_extractor is None:
        raise RuntimeError(
            "No extraction backend configured. Provide either client or vllm_extractor."
        )

    if vllm_extractor is not None:
        prompts = [
            _build_vllm_prompt(sent, analyses)
            for sent, analyses in zip(sentences, compound_analyses_list)
        ]
        batch_results = vllm_extractor.extract_batch(prompts)
        return [
            _dict_to_extraction(sent, data, analyses)
            for sent, data, analyses in zip(sentences, batch_results, compound_analyses_list)
        ]

    # Wrap once so all parallel workers share the same FrozenClient instance
    # (and therefore the same cache and fingerprint baseline).
    if not isinstance(client, FrozenClient):
        client = FrozenClient(client)

    def _extract_one(args) -> SentenceExtraction:
        sent, analyses = args
        return extract_sentence(sent, analyses, client=client)

    workers = min(10, len(sentences)) if sentences else 1
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_extract_one, zip(sentences, compound_analyses_list)))


def extract_problem(
    problem_sentences: List[str],
    client=None,
    problem_id: str = "unknown",
    max_workers: int = 5,
    vllm_extractor=None,
) -> ProblemExtraction:
    """
    Extract all sentences in a FOLIO problem.

    When vllm_extractor is provided, uses batch inference (all sentences in one
    GPU pass). When client is provided, uses parallel API calls via
    ThreadPoolExecutor. Raw clients are automatically wrapped in FrozenClient.
    Raises RuntimeError if neither backend is provided.
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
        # Wrap once so all workers share the same FrozenClient instance.
        if not isinstance(client, FrozenClient):
            client = FrozenClient(client)

        # API mode: parallel calls via ThreadPoolExecutor
        def _extract_one(args) -> SentenceExtraction:
            sent, analyses = args
            return extract_sentence(sent, analyses, client=client)

        workers = min(max_workers, len(problem_sentences)) if problem_sentences else 1
        with ThreadPoolExecutor(max_workers=workers) as pool:
            raw_extractions = list(pool.map(_extract_one, zip(problem_sentences, all_analyses)))

    # Sequential entity-ID deduplication (stateful — must not be parallelised)
    # FIX E1 (narrow): extraction moved to helper so tests can call it directly.
    sentence_extractions = _register_entities_across_sentences(raw_extractions)

    return ProblemExtraction(problem_id=problem_id, sentences=sentence_extractions)


def _register_entities_across_sentences(
    raw_extractions: List[SentenceExtraction],
) -> List[SentenceExtraction]:
    """
    Assign canonical cross-sentence entity/constant IDs.

    Stateful — processes extractions in order; must not be parallelised.

    # FIX E1 (narrow): registry keys are whitespace-normalised so that
    # "company building" and "company  building" (two spaces) resolve to the
    # same canonical entity.  This is the ONLY normalisation applied — no
    # article stripping, no lemmatisation, no synonym handling (Tenet 1).
    """
    sentence_extractions: List[SentenceExtraction] = []
    entity_registry: dict = {}    # normalised surface (lower) → canonical id
    constant_registry: dict = {}  # normalised surface (lower) → canonical id
    id_counter = {"e": 1, "c": 1}

    for extraction in raw_extractions:
        # Remap entity IDs
        id_remap: dict = {}
        new_entities = []
        for ent in extraction.entities:
            # FIX E1 (narrow): collapse internal whitespace and trim edges so
            # "company building" and "company  building" register as the same
            # entity.  No other normalisation is permitted (Tenet 1).
            key = re.sub(r"\s+", " ", ent.surface).strip().lower()
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
            # FIX E1 (narrow): same whitespace normalisation for constants.
            key = re.sub(r"\s+", " ", const.surface).strip().lower()
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

    return sentence_extractions
