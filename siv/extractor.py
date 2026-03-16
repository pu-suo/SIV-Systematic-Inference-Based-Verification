"""
Stage 2: Enriched LLM Extraction

Takes a sentence + the Stage 1 compound analyses and calls GPT-4o (or Claude)
to extract entities and facts into the minimal JSON schema defined in schema.py.

The compound analyses are injected into the prompt as structured context,
guiding the LLM's split/keep decisions with objective evidence.

The LLM also identifies the macro_template (one of the 7 Aristotelian forms).

When no API key is available the module falls back to a spaCy/NLTK rule-based
extractor that is accurate enough to run the full pipeline end-to-end.
"""
import json
import os
import re
from pathlib import Path
from typing import List, Optional

from siv.schema import (
    CompoundAnalysis, Entity, EntityType, Fact,
    MacroTemplate, ProblemExtraction, SentenceExtraction,
)
from siv.pre_analyzer import analyze_sentence, format_analyses_for_prompt

# ── Paths ─────────────────────────────────────────────────────────────────────

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


# ── API key helper ────────────────────────────────────────────────────────────

def _get_openai_key() -> str:
    try:
        from google.colab import userdata  # type: ignore
        return userdata.get("OPENAI_API_KEY") or ""
    except Exception:
        return os.environ.get("OPENAI_API_KEY", "")


# ── Prompt construction ───────────────────────────────────────────────────────

def _load_system_prompt() -> str:
    path = _PROMPTS_DIR / "extraction_system.txt"
    if path.exists():
        return path.read_text()
    # Minimal inline fallback
    return (
        "Extract entities and facts from the sentence into JSON with keys: "
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
    messages: List[dict] = [{"role": "system", "content": _load_system_prompt()}]

    for ex in _load_examples():
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


# ── Response parsing ──────────────────────────────────────────────────────────

def _parse_response(response_text: str) -> dict:
    """
    Parse and validate the LLM JSON response.
    Strips markdown fencing if present.
    Raises ValueError on schema violations.
    """
    text = response_text.strip()
    # Strip ```json ... ``` or ``` ... ```
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)

    if not isinstance(data.get("entities"), list):
        raise ValueError("Missing or invalid 'entities' list")
    if not isinstance(data.get("facts"), list):
        raise ValueError("Missing or invalid 'facts' list")
    for e in data["entities"]:
        if "id" not in e or "surface" not in e:
            raise ValueError(f"Entity missing id/surface: {e}")
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
        "constant":    EntityType.CONSTANT,
        "existential": EntityType.EXISTENTIAL,
        "universal":   EntityType.UNIVERSAL,
    }
    entities = [
        Entity(
            id=e["id"],
            surface=e["surface"],
            entity_type=etype_map.get(e.get("entity_type", "existential"),
                                      EntityType.EXISTENTIAL),
        )
        for e in data["entities"]
    ]
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
    )


# ── LLM extraction ────────────────────────────────────────────────────────────

def extract_sentence(
    sentence: str,
    compound_analyses: List[CompoundAnalysis],
    client=None,
    model: str = "gpt-4o",
    use_api: bool = True,
) -> SentenceExtraction:
    """
    Full extraction pipeline for one sentence.

    If use_api=False or no API client is provided, falls back to rule-based
    extraction (for testing without an API key).
    """
    if use_api and client is not None:
        messages = _build_prompt(sentence, compound_analyses)
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.0,
                max_tokens=800,
            )
            raw = response.choices[0].message.content
            data = _parse_response(raw)
            return _dict_to_extraction(sentence, data, compound_analyses)
        except Exception as e:
            # Fall through to rule-based
            pass

    return _fallback_extraction(sentence, compound_analyses)


def extract_problem(
    problem_sentences: List[str],
    client=None,
    model: str = "gpt-4o",
    use_api: bool = True,
    problem_id: str = "unknown",
) -> ProblemExtraction:
    """
    Extract all sentences in a FOLIO problem.

    Runs Stage 1 pre-analysis, then Stage 2 extraction for each sentence.
    Entity IDs are deduplicated across sentences using surface-form matching.
    """
    sentence_extractions: List[SentenceExtraction] = []
    # Cross-sentence entity registry: surface (lower) → canonical id
    entity_registry: dict = {}
    id_counter = {"e": 1, "c": 1}

    for sent in problem_sentences:
        analyses = analyze_sentence(sent)
        extraction = extract_sentence(
            sent, analyses, client=client, model=model, use_api=use_api
        )
        # Remap entity IDs to be unique across the problem
        id_remap: dict = {}
        new_entities = []
        for ent in extraction.entities:
            key = ent.surface.lower()
            if key in entity_registry:
                new_id = entity_registry[key]
            else:
                prefix = "c" if ent.entity_type == EntityType.CONSTANT else "e"
                new_id = f"{prefix}{id_counter[prefix]}"
                id_counter[prefix] += 1
                entity_registry[key] = new_id
            id_remap[ent.id] = new_id
            new_entities.append(
                Entity(id=new_id, surface=ent.surface, entity_type=ent.entity_type)
            )

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
            )
        )

    return ProblemExtraction(problem_id=problem_id, sentences=sentence_extractions)


# ── Rule-based fallback ───────────────────────────────────────────────────────

def _fallback_extraction(
    sentence: str,
    compound_analyses: Optional[List[CompoundAnalysis]] = None,
) -> SentenceExtraction:
    """
    Rule-based fallback when the API is unavailable.

    Uses spaCy (if available) or NLTK POS tagging for basic entity/fact
    extraction.  Less accurate than GPT-4o but produces valid schema-conforming
    output for end-to-end testing.
    """
    if compound_analyses is None:
        compound_analyses = []

    try:
        import spacy
        try:
            nlp = spacy.load("en_core_web_sm")
        except OSError:
            raise ImportError("en_core_web_sm not found")
        return _spacy_fallback(sentence, compound_analyses, nlp)
    except ImportError:
        return _nltk_fallback(sentence, compound_analyses)


def _spacy_fallback(sentence: str, analyses: List[CompoundAnalysis], nlp) -> SentenceExtraction:
    """spaCy-based rule-based extraction."""
    doc = nlp(sentence)

    # Build a KEEP-set from compound analyses for multi-word compounds
    keep_set = {
        f"{ca.modifier.lower()} {ca.noun.lower()}"
        for ca in analyses
        if ca.recommendation == "KEEP"
    }
    split_modifiers = {
        ca.modifier.lower()
        for ca in analyses
        if ca.recommendation == "SPLIT"
    }

    lower = sentence.lower().strip()
    if lower.startswith(("all ", "every ", "each ")):
        default_etype = EntityType.UNIVERSAL
        macro = MacroTemplate.TYPE_A
    elif lower.startswith("no "):
        default_etype = EntityType.UNIVERSAL
        macro = MacroTemplate.TYPE_E
    else:
        default_etype = EntityType.EXISTENTIAL
        macro = MacroTemplate.GROUND_POSITIVE

    entities: List[Entity] = []
    facts: List[Fact] = []
    eid = 1
    token_to_eid: dict = {}
    used_compounds: set = set()

    # First pass: build entities
    for tok in doc:
        if tok.pos_ in ("NOUN", "PROPN") and tok.dep_ not in ("compound",):
            # Check if this is part of a KEEP compound (modifier already attached)
            compound_key = None
            for child in tok.children:
                if child.dep_ in ("amod", "compound"):
                    ck = f"{child.text.lower()} {tok.text.lower()}"
                    if ck in keep_set:
                        compound_key = ck
                        used_compounds.add(child.i)

            if compound_key:
                surface = compound_key  # e.g. "Harvard student"
            else:
                surface = tok.text.lower()

            etype = (
                EntityType.CONSTANT
                if tok.pos_ == "PROPN" or tok.ent_type_
                else default_etype
            )
            eid_str = f"{'c' if etype == EntityType.CONSTANT else 'e'}{eid}"
            eid += 1
            entity = Entity(id=eid_str, surface=surface, entity_type=etype)
            entities.append(entity)
            token_to_eid[tok.i] = eid_str

    # Second pass: build facts
    for tok in doc:
        if tok.i in used_compounds:
            continue
        if tok.pos_ in ("ADJ",) or (tok.dep_ in ("amod",) and tok.i not in used_compounds):
            # Adjective → unary property on its head noun's entity
            head_eid = token_to_eid.get(tok.head.i)
            if head_eid and tok.text.lower() in split_modifiers:
                facts.append(Fact(pred=tok.text.lower(), args=[head_eid]))
        elif tok.pos_ == "VERB" and tok.dep_ not in ("aux", "auxpass"):
            subj_eid = None
            obj_eid = None
            for child in tok.children:
                if child.dep_ in ("nsubj", "nsubjpass"):
                    subj_eid = token_to_eid.get(child.i)
                if child.dep_ in ("dobj", "attr", "pobj"):
                    obj_eid = token_to_eid.get(child.i)
            if subj_eid and obj_eid:
                facts.append(Fact(pred=tok.lemma_.lower(), args=[subj_eid, obj_eid]))
            elif subj_eid:
                facts.append(Fact(pred=tok.lemma_.lower(), args=[subj_eid]))

    # Fallback: entity type facts
    for ent in entities:
        has_type_fact = any(
            f.pred == ent.surface and f.args == [ent.id] for f in facts
        )
        if not has_type_fact:
            # Add a type fact so the entity surface is represented in tests
            facts.insert(0, Fact(pred=ent.surface, args=[ent.id]))

    # Detect negation in macro template
    neg_words = {"not", "never", "no", "n't"}
    if any(t.lower_ in neg_words for t in doc):
        if default_etype == EntityType.UNIVERSAL:
            macro = MacroTemplate.TYPE_E
        else:
            macro = MacroTemplate.GROUND_NEGATIVE

    return SentenceExtraction(
        nl=sentence,
        entities=entities,
        facts=facts,
        macro_template=macro,
        compound_analyses=analyses,
    )


def _nltk_fallback(sentence: str, analyses: List[CompoundAnalysis]) -> SentenceExtraction:
    """Minimal NLTK POS-tag fallback (no spaCy)."""
    try:
        import nltk
        for resource in ("punkt_tab", "averaged_perceptron_tagger_eng"):
            try:
                nltk.data.find(f"tokenizers/{resource}")
            except LookupError:
                nltk.download(resource, quiet=True)
            try:
                nltk.data.find(f"taggers/{resource}")
            except LookupError:
                nltk.download(resource, quiet=True)

        tokens = nltk.word_tokenize(sentence)
        tagged = nltk.pos_tag(tokens)
    except Exception:
        # Absolute last resort: whitespace split
        tagged = [(w, "NN") for w in sentence.split()]

    lower = sentence.lower().strip()
    if lower.startswith(("all ", "every ", "each ")):
        default_etype = EntityType.UNIVERSAL
        macro = MacroTemplate.TYPE_A
    else:
        default_etype = EntityType.EXISTENTIAL
        macro = MacroTemplate.GROUND_POSITIVE

    entities: List[Entity] = []
    facts: List[Fact] = []
    eid = 1
    stop_words = {"the", "a", "an", "some", "all", "every", "each", "no",
                  "is", "are", "was", "were", "be", "been", "being"}

    for word, tag in tagged:
        if word.lower() in stop_words:
            continue
        if tag in ("NN", "NNS", "NNP", "NNPS"):
            etype = EntityType.CONSTANT if tag in ("NNP", "NNPS") else default_etype
            eid_str = f"{'c' if etype == EntityType.CONSTANT else 'e'}{eid}"
            eid += 1
            surface = word.lower()
            entities.append(Entity(id=eid_str, surface=surface, entity_type=etype))
            facts.append(Fact(pred=surface, args=[eid_str]))
        elif tag in ("JJ", "JJR", "JJS") and entities:
            facts.append(Fact(pred=word.lower(), args=[entities[-1].id]))

    return SentenceExtraction(
        nl=sentence,
        entities=entities,
        facts=facts,
        macro_template=macro,
        compound_analyses=analyses,
    )
