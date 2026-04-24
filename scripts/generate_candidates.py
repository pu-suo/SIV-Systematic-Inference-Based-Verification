"""Generate candidate FOL translations for FOLIO premises.

Produces candidate translations from multiple sources for each premise:
gold FOL, model translations (GPT-4o, GPT-4o-mini), and AST perturbations
(Tiers A–D).  No SIV pipeline involvement — candidates are independent of
the metric under test.

Usage:
    # Full run (requires OPENAI_API_KEY):
    python scripts/generate_candidates.py --split train

    # Dry run (skip LLM calls):
    python scripts/generate_candidates.py --split train --limit 10 --skip-models

    # Custom output:
    python scripts/generate_candidates.py --split train --output my_candidates.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).parent.parent
load_dotenv(_REPO_ROOT / ".env")

sys.path.insert(0, str(_REPO_ROOT))

from siv.aligner import extract_symbols_from_fol
from siv.fol_utils import is_valid_fol, normalize_fol_string, parse_fol
from siv.nltk_perturbations import NotApplicable, select_perturbation
from siv.stratum_classifier import classify_stratum_from_fol

# ── Constants ────────────────────────────────────────────────────────────────

SEED = 42
CACHE_DIR = _REPO_ROOT / ".siv_cache"

SYSTEM_PROMPT = """You are a formal logic translator. Given a natural language sentence, produce its first-order logic (FOL) translation. Use these conventions:

  - all x.(...) for universal quantification
  - exists x.(...) for existential quantification
  - -> for implication
  - & for conjunction
  - | for disjunction
  - <-> for biconditional
  - -P(x) for negation (prefix dash)
  - CamelCase for predicate names (e.g., HasTeeth, IsHappy)
  - camelCase for constants (e.g., john, theLegendOfZelda)
  - Parentheses to clarify scope

Output ONLY the FOL formula. No explanation, no commentary."""

FEW_SHOT_MESSAGES = [
    {"role": "user", "content": "LanguageA is a universal language"},
    {"role": "assistant", "content": "UniversalLanguage(languageA)"},
    {"role": "user", "content": "All people who regularly drink coffee are dependent on caffeine."},
    {"role": "assistant", "content": "all x.(DrinkRegularly(x, coffee) -> IsDependentOn(x, caffeine))"},
    {"role": "user", "content": "All animals displayed in the collection are multicellular."},
    {"role": "assistant", "content": "all x.((DisplayedIn(x, collection) & Animal(x)) -> Multicellular(x))"},
    {"role": "user", "content": "Sam is doing a project."},
    {"role": "assistant", "content": "exists x.(Project(x) & Do(sam, x))"},
]


# ── Data Loading ─────────────────────────────────────────────────────────────


def _load_fewshot_exclusions() -> Set[str]:
    path = _REPO_ROOT / "prompts" / "extraction_examples.json"
    if path.exists():
        data = json.loads(path.read_text())
        return {e["sentence"] for e in data}
    return set()


def load_premises(split: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    from datasets import load_dataset

    ds = load_dataset("tasksource/folio", split=split)
    exclusions = _load_fewshot_exclusions()
    seen: set = set()
    pairs: List[Dict[str, Any]] = []

    for row in ds:
        nl_parts = [p.strip() for p in row["premises"].split("\n") if p.strip()]
        fol_parts = [p.strip() for p in row["premises-FOL"].split("\n") if p.strip()]
        if len(nl_parts) != len(fol_parts):
            continue
        for n, f in zip(nl_parts, fol_parts):
            if n in seen or n in exclusions:
                continue
            seen.add(n)
            pairs.append({"story_id": row.get("story_id"), "nl": n, "gold_fol": f})

    stories = {p["story_id"] for p in pairs}
    sys.stderr.write(
        f"[candidates] Split={split}  Stories={len(stories)}  Premises={len(pairs)}\n"
    )
    if limit:
        pairs = pairs[:limit]
        sys.stderr.write(f"[candidates] --limit active: {len(pairs)} premises\n")
    return pairs


def build_story_context(pairs: List[Dict[str, Any]]) -> Dict[Any, Dict[str, Any]]:
    by_story: Dict[Any, List[Dict]] = defaultdict(list)
    for p in pairs:
        by_story[p["story_id"]].append(p)

    context = {}
    for story_id, premises in by_story.items():
        all_preds: Set[str] = set()
        all_consts: Set[str] = set()
        for p in premises:
            syms = extract_symbols_from_fol(normalize_fol_string(p["gold_fol"]))
            all_preds.update(syms["predicates"].keys())
            all_consts.update(syms["constants"])
        context[story_id] = {
            "predicates": sorted(all_preds),
            "constants": sorted(all_consts),
        }
    return context


# ── Translation Cache ────────────────────────────────────────────────────────

_TRANSLATION_CACHE: Dict[str, Dict] = {}
_CACHE_FILE = CACHE_DIR / "translation_cache.jsonl"


def _cache_key(model: str, nl: str) -> str:
    return hashlib.sha256(f"{model}|{nl}".encode()).hexdigest()


def _load_cache():
    if _TRANSLATION_CACHE:
        return
    if _CACHE_FILE.exists():
        for line in _CACHE_FILE.read_text().splitlines():
            if line.strip():
                entry = json.loads(line)
                _TRANSLATION_CACHE[entry["key"]] = entry


def _cache_get(model: str, nl: str) -> Optional[Dict]:
    _load_cache()
    return _TRANSLATION_CACHE.get(_cache_key(model, nl))


def _cache_put(model: str, nl: str, fol: str, response_id: str):
    key = _cache_key(model, nl)
    entry = {"key": key, "model": model, "nl": nl, "fol": fol, "response_id": response_id}
    _TRANSLATION_CACHE[key] = entry
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with _CACHE_FILE.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def translate_nl_to_fol(nl: str, client, model: str) -> Tuple[str, str]:
    cached = _cache_get(model, nl)
    if cached:
        return cached["fol"], cached.get("response_id", "cached")

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(FEW_SHOT_MESSAGES)
    messages.append({"role": "user", "content": nl})

    response = client.chat.completions.create(
        model=model, messages=messages,
        temperature=0.0, seed=SEED, max_tokens=512,
    )
    fol = response.choices[0].message.content.strip()
    resp_id = response.id or ""
    _cache_put(model, nl, fol, resp_id)
    return fol, resp_id


# ── BLEU ─────────────────────────────────────────────────────────────────────

def compute_bleu(candidate: str, reference: str) -> float:
    import re
    import sacrebleu

    def _tok(fol: str) -> str:
        fol = re.sub(r"([(),&|<>!=\-])", r" \1 ", fol)
        return " ".join(fol.split())

    bleu = sacrebleu.sentence_bleu(_tok(candidate), [_tok(reference)])
    return round(bleu.score / 100.0, 4)


# ── Candidate Generation ──────────────────────────────────────────���─────────


def generate_candidates(
    pairs: List[Dict[str, Any]],
    story_context: Dict[Any, Dict],
    client_strong=None,
    client_weak=None,
    model_strong: str = "gpt-4o-2024-08-06",
    model_weak: str = "gpt-4o-mini",
    skip_models: bool = False,
    seed: int = SEED,
) -> List[Dict[str, Any]]:
    rng = random.Random(seed)
    candidates = []
    item_counter = 0
    t0 = time.time()

    for pi, pair in enumerate(pairs):
        premise_id = f"P{pi:04d}"
        nl = pair["nl"]
        gold_raw = pair["gold_fol"]
        gold_norm = normalize_fol_string(gold_raw)
        story_id = pair["story_id"]
        stratum = classify_stratum_from_fol(gold_raw)
        parsed = parse_fol(gold_norm)
        ctx = story_context.get(story_id, {"predicates": [], "constants": []})

        def _add(ctype, fol, pert_op=None, model=None, resp_id=None):
            nonlocal item_counter
            item_counter += 1
            candidates.append({
                "item_id": f"I{item_counter:05d}",
                "premise_id": premise_id,
                "story_id": story_id,
                "nl": nl,
                "gold_fol": gold_raw,
                "gold_fol_normalized": gold_norm,
                "stratum": stratum or "unparseable",
                "candidate_type": ctype,
                "candidate_fol": fol,
                "perturbation_operator": pert_op,
                "model": model,
                "model_response_id": resp_id,
                "bleu_vs_gold": compute_bleu(fol, gold_norm) if fol else 0.0,
                "parse_valid": is_valid_fol(normalize_fol_string(fol)) if fol else False,
            })

        # C_gold
        _add("C_gold", gold_norm)

        # C_model_strong
        if not skip_models and client_strong:
            try:
                fol, rid = translate_nl_to_fol(nl, client_strong, model_strong)
                _add("C_model_strong", fol, model=model_strong, resp_id=rid)
            except Exception as e:
                _add("C_model_strong", "", model=model_strong, resp_id=f"error:{e}")
        elif skip_models:
            _add("C_model_strong", f"PLACEHOLDER_STRONG({premise_id})", model=model_strong)

        # C_model_weak
        if not skip_models and client_weak:
            try:
                fol, rid = translate_nl_to_fol(nl, client_weak, model_weak)
                _add("C_model_weak", fol, model=model_weak, resp_id=rid)
            except Exception as e:
                _add("C_model_weak", "", model=model_weak, resp_id=f"error:{e}")
        elif skip_models:
            _add("C_model_weak", f"PLACEHOLDER_WEAK({premise_id})", model=model_weak)

        # Perturbations (only if gold parses)
        if parsed is not None:
            for tier, n_needed in [("A", 1), ("B", 2), ("C", 1), ("D", 1)]:
                used_ops: Set[str] = set()
                for _ in range(n_needed):
                    try:
                        pert, op = select_perturbation(
                            tier, parsed, rng,
                            story_predicates=ctx["predicates"],
                            story_constants=ctx["constants"],
                            exclude_ops=used_ops,
                        )
                        _add(f"C_pert_tier{tier}", str(pert), pert_op=op)
                        used_ops.add(op)
                    except NotApplicable:
                        break

        if (pi + 1) % 100 == 0 or (pi + 1) == len(pairs):
            dt = time.time() - t0
            sys.stderr.write(
                f"[candidates] {pi+1}/{len(pairs)} premises, "
                f"{len(candidates)} candidates, {dt:.0f}s\n"
            )

    return candidates


# ── Main ──────────────────────────────────────────────────────────────��──────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", type=str, default="train")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--skip-models", action="store_true",
                    help="Skip LLM translation calls (for dry runs).")
    ap.add_argument("--output", type=str,
                    default=str(_REPO_ROOT / "reports" / "human_study" / "candidates.jsonl"))
    args = ap.parse_args()

    pairs = load_premises(args.split, limit=args.limit)
    if not pairs:
        sys.stderr.write("[candidates] No premises loaded.\n")
        return 1

    story_context = build_story_context(pairs)

    client_strong = client_weak = None
    if not args.skip_models:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            sys.stderr.write("[candidates] OPENAI_API_KEY not set. Use --skip-models.\n")
            return 2
        from openai import OpenAI
        client_strong = OpenAI()
        client_weak = OpenAI()

    candidates = generate_candidates(
        pairs, story_context,
        client_strong=client_strong, client_weak=client_weak,
        skip_models=args.skip_models, seed=args.seed,
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for c in candidates:
            f.write(json.dumps(c, default=str) + "\n")

    sys.stderr.write(f"[candidates] Wrote {out_path} ({len(candidates)} candidates)\n")

    # Summary
    types = Counter(c["candidate_type"] for c in candidates)
    strata = Counter(c["stratum"] for c in candidates)
    ops = Counter(c["perturbation_operator"] for c in candidates if c["perturbation_operator"])
    sys.stderr.write(f"[candidates] Types: {dict(types.most_common())}\n")
    sys.stderr.write(f"[candidates] Strata: {dict(strata.most_common())}\n")
    sys.stderr.write(f"[candidates] Perturbation ops: {dict(ops.most_common())}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
