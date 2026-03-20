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
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional

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
        except Exception:
            # Fall through to rule-based
            pass

    return _fallback_extraction(sentence, compound_analyses)


def extract_problem(
    problem_sentences: List[str],
    client=None,
    model: str = "gpt-4o",
    use_api: bool = True,
    problem_id: str = "unknown",
    max_workers: int = 5,
) -> ProblemExtraction:
    """
    Extract all sentences in a FOLIO problem.

    Runs Stage 1 pre-analysis + Stage 2 extraction for each sentence in
    parallel (up to *max_workers* concurrent API calls), then performs
    cross-sentence entity-ID deduplication sequentially on the results.

    *max_workers* caps concurrency to avoid GPT-4o rate-limit 429s.
    Set max_workers=1 to revert to fully sequential behaviour.
    """
    def _extract_one(sent: str) -> SentenceExtraction:
        analyses = analyze_sentence(sent)
        return extract_sentence(sent, analyses, client=client,
                                model=model, use_api=use_api)

    # Parallel extraction — pool.map preserves input order
    workers = min(max_workers, len(problem_sentences)) if problem_sentences else 1
    with ThreadPoolExecutor(max_workers=workers) as pool:
        raw_extractions = list(pool.map(_extract_one, problem_sentences))

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


def _detect_macro_template(sentence: str, doc=None) -> MacroTemplate:
    """
    Detect macro template from sentence text and optional spaCy doc.

    Checks both sentence-initial position AND universal determiners on subject noun.
    """
    lower = sentence.lower().strip()

    # Sentence-initial quantifiers
    if lower.startswith(("all ", "every ", "each ")):
        return MacroTemplate.TYPE_A
    if lower.startswith("no "):
        return MacroTemplate.TYPE_E

    # Negation words → switch affirmative to negative variant
    neg_words = {"not", "never", "no", "n't"}

    # spaCy-based: check universal determiners on subject noun
    if doc is not None:
        for tok in doc:
            if tok.dep_ in ("nsubj", "nsubjpass") and tok.pos_ in ("NOUN", "PROPN"):
                for child in tok.children:
                    if child.dep_ == "det" and child.text.lower() in ("all", "every", "each"):
                        if any(t.lower_ in neg_words for t in doc):
                            return MacroTemplate.TYPE_E
                        return MacroTemplate.TYPE_A
                    if child.dep_ == "det" and child.text.lower() == "no":
                        return MacroTemplate.TYPE_E
        # Check for negation with existential subject
        if any(t.lower_ in neg_words for t in doc):
            return MacroTemplate.GROUND_NEGATIVE

    return MacroTemplate.GROUND_POSITIVE


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

    macro = _detect_macro_template(sentence, doc)
    default_etype = (
        EntityType.UNIVERSAL
        if macro in (MacroTemplate.TYPE_A, MacroTemplate.TYPE_E)
        else EntityType.EXISTENTIAL
    )

    constants: List[Constant] = []
    entities: List[Entity] = []
    facts: List[Fact] = []
    eid = 1
    token_to_id: dict = {}   # token.i → id string
    used_compounds: set = set()

    # First pass: build constants + entities
    for tok in doc:
        if tok.pos_ in ("NOUN", "PROPN") and tok.dep_ not in ("compound",):
            # Check if this is part of a KEEP compound
            compound_key = None
            for child in tok.children:
                if child.dep_ in ("amod", "compound"):
                    ck = f"{child.text.lower()} {tok.text.lower()}"
                    if ck in keep_set:
                        compound_key = ck
                        used_compounds.add(child.i)

            surface = compound_key if compound_key else tok.text.lower()

            if tok.pos_ == "PROPN" or tok.ent_type_:
                # Named individual → constants list
                const_id = surface.replace(" ", "").lower()
                # Use camelCase for multi-word surfaces
                if " " in surface:
                    parts = surface.split()
                    const_id = parts[0] + "".join(p.capitalize() for p in parts[1:])
                const = Constant(id=const_id, surface=surface)
                constants.append(const)
                token_to_id[tok.i] = const_id
            else:
                etype = default_etype
                eid_str = f"e{eid}"
                eid += 1
                entity = Entity(id=eid_str, surface=surface, entity_type=etype)
                entities.append(entity)
                token_to_id[tok.i] = eid_str

    # Second pass: build facts
    for tok in doc:
        if tok.i in used_compounds:
            continue
        if tok.pos_ in ("ADJ",) or (tok.dep_ in ("amod",) and tok.i not in used_compounds):
            head_id = token_to_id.get(tok.head.i)
            if head_id and tok.text.lower() in split_modifiers:
                facts.append(Fact(pred=tok.text.lower(), args=[head_id]))
        elif tok.pos_ == "VERB" and tok.dep_ not in ("aux", "auxpass"):
            subj_id = None
            obj_id = None
            for child in tok.children:
                if child.dep_ in ("nsubj", "nsubjpass"):
                    subj_id = token_to_id.get(child.i)
                if child.dep_ in ("dobj", "attr"):
                    obj_id = token_to_id.get(child.i)
                # Bug 3.2 fix: traverse prep → pobj chains
                if child.dep_ == "prep" and obj_id is None:
                    for pobj in child.children:
                        if pobj.dep_ == "pobj":
                            pobj_id = token_to_id.get(pobj.i)
                            if pobj_id and subj_id:
                                compound_pred = f"{tok.lemma_.lower()}_{child.text.lower()}"
                                facts.append(Fact(pred=compound_pred,
                                                  args=[subj_id, pobj_id]))
            if subj_id and obj_id:
                facts.append(Fact(pred=tok.lemma_.lower(), args=[subj_id, obj_id]))
            elif subj_id and not any(
                f.args == [subj_id] and tok.lemma_.lower() in f.pred for f in facts
            ):
                facts.append(Fact(pred=tok.lemma_.lower(), args=[subj_id]))

    # Fallback: entity type facts
    for ent in entities:
        has_type_fact = any(
            f.pred == ent.surface and f.args == [ent.id] for f in facts
        )
        if not has_type_fact:
            facts.insert(0, Fact(pred=ent.surface, args=[ent.id]))

    return SentenceExtraction(
        nl=sentence,
        entities=entities,
        facts=facts,
        macro_template=macro,
        compound_analyses=analyses,
        constants=constants,
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

    macro = _detect_macro_template(sentence)

    constants: List[Constant] = []
    entities: List[Entity] = []
    facts: List[Fact] = []
    eid = 1
    stop_words = {"the", "a", "an", "some", "all", "every", "each", "no",
                  "is", "are", "was", "were", "be", "been", "being"}

    default_etype = (
        EntityType.UNIVERSAL
        if macro in (MacroTemplate.TYPE_A, MacroTemplate.TYPE_E)
        else EntityType.EXISTENTIAL
    )

    last_id: Optional[str] = None
    for word, tag in tagged:
        if word.lower() in stop_words:
            continue
        if tag in ("NN", "NNS", "NNP", "NNPS"):
            if tag in ("NNP", "NNPS"):
                # Proper noun → constants
                const_id = word.lower()
                constants.append(Constant(id=const_id, surface=word.lower()))
                last_id = const_id
                facts.append(Fact(pred=word.lower(), args=[const_id]))
            else:
                eid_str = f"e{eid}"
                eid += 1
                surface = word.lower()
                entities.append(Entity(id=eid_str, surface=surface,
                                       entity_type=default_etype))
                facts.append(Fact(pred=surface, args=[eid_str]))
                last_id = eid_str
        elif tag in ("JJ", "JJR", "JJS") and last_id is not None:
            facts.append(Fact(pred=word.lower(), args=[last_id]))

    return SentenceExtraction(
        nl=sentence,
        entities=entities,
        facts=facts,
        macro_template=macro,
        compound_analyses=analyses,
        constants=constants,
    )
