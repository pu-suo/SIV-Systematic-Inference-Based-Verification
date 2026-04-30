"""Phase 1.1 — Entailment harness: translate premises, run Vampire, record correctness.

For each FOLIO example (story premises + conclusion + gold label):
  - Hold conclusion FOL fixed at FOLIO gold
  - Translate all premises with each translator (gold, GPT-4o, GPT-4o-mini, Claude Sonnet)
  - Run Vampire prove_strict() on (translated premises, gold conclusion)
  - Compare verdict to gold label
  - Record results

Usage:
    python scripts/phase1_translate_and_entail.py --split train --timeout-s 10
    python scripts/phase1_translate_and_entail.py --split train --limit 5  # dry run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from siv.fol_utils import normalize_fol_string, parse_fol

# ── Constants ──────────────────────────────────────────────────────────────────

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

LABEL_TO_VERDICT = {"True": "entailment", "False": "contradiction", "Uncertain": "neutral"}


# ── Translation Cache ──────────────────────────────────────────────────────────

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


# ── Translation Functions ──────────────────────────────────────────────────────

def translate_nl_to_fol_openai(nl: str, client, model: str) -> Tuple[str, str]:
    """Translate NL to FOL using OpenAI API (cached)."""
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


def translate_nl_to_fol_anthropic(nl: str, client, model: str) -> Tuple[str, str]:
    """Translate NL to FOL using Anthropic API (cached)."""
    cached = _cache_get(model, nl)
    if cached:
        return cached["fol"], cached.get("response_id", "cached")

    # Convert few-shot messages to Anthropic format (alternating user/assistant)
    messages = list(FEW_SHOT_MESSAGES) + [{"role": "user", "content": nl}]

    response = client.messages.create(
        model=model, system=SYSTEM_PROMPT,
        messages=messages,
        temperature=0.0, max_tokens=512,
    )
    fol = response.content[0].text.strip()
    resp_id = response.id or ""
    _cache_put(model, nl, fol, resp_id)
    return fol, resp_id


# ── Data Loading ───────────────────────────────────────────────────────────────

def load_folio_examples(split: str) -> List[Dict[str, Any]]:
    """Load FOLIO examples with full story structure (premises + conclusion + label).

    Returns list of dicts with keys:
        example_id, story_id, premises_nl (List[str]), premises_fol (List[str]),
        conclusion_nl (str), conclusion_fol (str), gold_label (str)
    """
    from datasets import load_dataset

    ds = load_dataset("tasksource/folio", split=split)
    examples = []
    skipped = 0

    for row in ds:
        nl_parts = [p.strip() for p in row["premises"].split("\n") if p.strip()]
        fol_parts = [p.strip() for p in row["premises-FOL"].split("\n") if p.strip()]
        if len(nl_parts) != len(fol_parts):
            skipped += 1
            continue

        conclusion_nl = row.get("conclusion", "")
        conclusion_fol = row.get("conclusion-FOL", "")
        if not conclusion_fol:
            skipped += 1
            continue

        examples.append({
            "example_id": row.get("example_id", ""),
            "story_id": row.get("story_id"),
            "premises_nl": nl_parts,
            "premises_fol": fol_parts,
            "conclusion_nl": conclusion_nl,
            "conclusion_fol": conclusion_fol,
            "gold_label": row.get("label", ""),
        })

    sys.stderr.write(
        f"[phase1] Loaded {len(examples)} examples from {split} "
        f"(skipped {skipped} with mismatched/missing data)\n"
    )
    return examples


# ── Entailment ─────────────────────────────────────────────────────────────────

def run_entailment(
    premises_fol: List[str],
    conclusion_fol: str,
    gold_label: str,
    timeout: int = 10,
) -> Dict[str, Any]:
    """Run prove_strict, map verdict to gold label, return result dict."""
    from siv.vampire_interface import prove_strict

    # Count parse errors
    parse_errors = 0
    for fol in premises_fol:
        norm = normalize_fol_string(fol)
        if not norm or parse_fol(norm) is None:
            parse_errors += 1
    conc_norm = normalize_fol_string(conclusion_fol)
    if not conc_norm or parse_fol(conc_norm) is None:
        parse_errors += 1

    # Normalize all FOLs for Vampire
    norm_premises = [normalize_fol_string(f) for f in premises_fol]
    norm_conclusion = normalize_fol_string(conclusion_fol)

    verdict, proof_info = prove_strict(norm_premises, norm_conclusion, timeout=timeout)

    expected = LABEL_TO_VERDICT.get(gold_label, "neutral")
    correct = verdict == expected
    is_timeout = proof_info is not None and "Timeout" in str(proof_info)

    return {
        "verdict": verdict,
        "correct": correct,
        "parse_errors": parse_errors,
        "timeout_count": 1 if is_timeout else 0,
    }


# ── Translation Orchestration ──────────────────────────────────────────────────

def translate_premises(
    premises_nl: List[str],
    translator: str,
    premises_fol_gold: List[str],
    openai_client=None,
    anthropic_client=None,
) -> Tuple[List[str], str]:
    """Translate all premises for a given translator.

    Returns (translated_fol_list, model_name).
    """
    if translator == "gold":
        return [normalize_fol_string(f) for f in premises_fol_gold], "gold"

    elif translator == "gpt-4o":
        model = "gpt-4o-2024-08-06"
        fols = []
        for nl in premises_nl:
            fol, _ = translate_nl_to_fol_openai(nl, openai_client, model)
            fols.append(fol)
        return fols, model

    elif translator == "gpt-4o-mini":
        model = "gpt-4o-mini"
        fols = []
        for nl in premises_nl:
            fol, _ = translate_nl_to_fol_openai(nl, openai_client, model)
            fols.append(fol)
        return fols, model

    elif translator == "claude-sonnet":
        model = "claude-sonnet-4-6-20250514"
        fols = []
        for nl in premises_nl:
            fol, _ = translate_nl_to_fol_anthropic(nl, anthropic_client, model)
            fols.append(fol)
        return fols, model

    else:
        raise ValueError(f"Unknown translator: {translator}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", type=str, default="train",
                    help="FOLIO split (default: train)")
    ap.add_argument("--timeout-s", type=int, default=10)
    ap.add_argument("--limit", type=int, default=None,
                    help="Process only first N examples (debugging)")
    ap.add_argument("--output", type=str,
                    default=str(_REPO_ROOT / "reports" / "phase1" / "entailment_results.jsonl"))
    ap.add_argument("--translators", type=str, default="gold,gpt-4o,gpt-4o-mini,claude-sonnet",
                    help="Comma-separated list of translators")
    ap.add_argument("--skip-claude", action="store_true",
                    help="Skip Claude translator (if no ANTHROPIC_API_KEY)")
    args = ap.parse_args()

    translators = [t.strip() for t in args.translators.split(",")]

    # Initialize API clients
    from dotenv import load_dotenv
    load_dotenv(_REPO_ROOT / ".env")

    openai_client = None
    anthropic_client = None

    needs_openai = any(t in translators for t in ("gpt-4o", "gpt-4o-mini"))
    needs_anthropic = "claude-sonnet" in translators and not args.skip_claude

    if needs_openai:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            sys.stderr.write("[phase1] OPENAI_API_KEY not set. Skipping OpenAI translators.\n")
            translators = [t for t in translators if t not in ("gpt-4o", "gpt-4o-mini")]
        else:
            from openai import OpenAI
            openai_client = OpenAI()

    if needs_anthropic:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            sys.stderr.write("[phase1] ERROR: ANTHROPIC_API_KEY not set.\n")
            sys.stderr.write("[phase1] Either set it in .env or use --skip-claude\n")
            return 1
        import anthropic
        anthropic_client = anthropic.Anthropic()
        # Verify the API key works before processing 1000+ examples
        sys.stderr.write("[phase1] Verifying Anthropic API key...\n")
        try:
            test_resp = anthropic_client.messages.create(
                model="claude-sonnet-4-6-20250514",
                system="Reply with OK.",
                messages=[{"role": "user", "content": "test"}],
                max_tokens=5,
            )
            sys.stderr.write(f"[phase1] Anthropic API key verified OK\n")
        except Exception as e:
            sys.stderr.write(f"[phase1] ERROR: Anthropic API check failed: {e}\n")
            sys.stderr.write("[phase1] Fix your API key/credits, or use --skip-claude\n")
            return 1

    if args.skip_claude and "claude-sonnet" in translators:
        translators = [t for t in translators if t != "claude-sonnet"]

    sys.stderr.write(f"[phase1] Translators: {translators}\n")

    # Load examples
    examples = load_folio_examples(args.split)
    if args.limit:
        examples = examples[:args.limit]
        sys.stderr.write(f"[phase1] --limit active: {len(examples)} examples\n")

    # Process
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    total = len(examples) * len(translators)
    done = 0
    t0 = time.time()

    results = []
    for ex in examples:
        conclusion_fol = normalize_fol_string(ex["conclusion_fol"])

        for translator in translators:
            premises_fol, model = translate_premises(
                ex["premises_nl"], translator, ex["premises_fol"],
                openai_client=openai_client,
                anthropic_client=anthropic_client,
            )

            ent = run_entailment(
                premises_fol, conclusion_fol, ex["gold_label"],
                timeout=args.timeout_s,
            )

            row = {
                "example_id": ex["example_id"],
                "story_id": ex["story_id"],
                "translator": translator,
                "premises_fol": premises_fol,
                "conclusion_fol": conclusion_fol,
                "verdict": ent["verdict"],
                "gold_label": ex["gold_label"],
                "correct": ent["correct"],
                "parse_errors": ent["parse_errors"],
                "timeout_count": ent["timeout_count"],
                "model": model,
                "n_premises": len(premises_fol),
            }
            results.append(row)

            done += 1
            if done % 10 == 0 or done == total:
                elapsed = time.time() - t0
                sys.stderr.write(
                    f"[phase1] {done}/{total} processed "
                    f"(elapsed={elapsed:.0f}s)\n"
                )

            # Incremental save every 100 rows
            if len(results) % 100 == 0:
                with output_path.open("w") as f:
                    for r in results:
                        f.write(json.dumps(r) + "\n")

    # Final write
    with output_path.open("w") as f:
        for row in results:
            f.write(json.dumps(row) + "\n")

    sys.stderr.write(f"[phase1] Wrote {len(results)} rows to {output_path}\n")

    # Summary
    from collections import Counter
    correct_by_translator = defaultdict(list)
    for row in results:
        correct_by_translator[row["translator"]].append(row["correct"])

    sys.stderr.write("[phase1] Summary:\n")
    for t, vals in sorted(correct_by_translator.items()):
        n = len(vals)
        acc = sum(vals) / n if n else 0
        parse_errs = sum(1 for r in results if r["translator"] == t and r["parse_errors"] > 0)
        timeouts = sum(r["timeout_count"] for r in results if r["translator"] == t)
        sys.stderr.write(
            f"  {t}: accuracy={acc:.3f} ({sum(vals)}/{n}) "
            f"parse_errors={parse_errs} timeouts={timeouts}\n"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
