"""
C2 Pilots: Baseline calibration, leakage probe, over-correction, model scaling.

Runs all 4 pre-C2 pilots to determine:
  - Pilot 1: No-feedback correction rate (target 20-50% band)
  - Pilot 2: Optimal diagnostic granularity (coarsest that helps)
  - Pilot 3: Over-correction/regression rate under diagnostic feedback
  - Pilot 4: Effect across model scales

Models:
  - Frontier: GPT-4o (OpenAI)
  - Frontier-alt: Claude Sonnet (Anthropic)
  - Mid-tier: GPT-4o-mini (OpenAI)

Run: python scripts/c2_pilots.py [--pilot 1|2|3|4|all] [--seed 42]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

load_dotenv(_REPO_ROOT / ".env")

from siv.fol_utils import normalize_fol_string
from siv.gold_suite_generator import generate_test_suite_from_gold
from siv.fol_parser import parse_gold_fol
from siv.compiler import compile_canonical_fol
from siv.contrastive_generator import derive_witness_axioms
from siv.scorer import score
from siv.vampire_interface import check_entailment, is_vampire_available

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

EXP1_DIR = _REPO_ROOT / "reports" / "experiments" / "exp1"
EXP2_DIR = _REPO_ROOT / "reports" / "experiments" / "exp2"
SUITES_PATH = _REPO_ROOT / "reports" / "test_suites" / "test_suites.jsonl"
OUT_DIR = _REPO_ROOT / "reports" / "c2_pilots"
CACHE_DIR = OUT_DIR / ".cache"

SEED = 42

# Model configs
MODELS = {
    "gpt-4o": {"provider": "openai", "model": "gpt-4o"},
    "gpt-4o-mini": {"provider": "openai", "model": "gpt-4o-mini"},
    "claude-sonnet": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
}

CORRECTIONS_PATH = _REPO_ROOT / "docs" / "corrections_template.md"


# ═══════════════════════════════════════════════════════════════════════════
# LLM interface
# ═══════════════════════════════════════════════════════════════════════════

def call_llm(model_key: str, prompt: str, temperature: float = 0.0) -> str:
    """Call LLM and return response text. Caches responses."""
    cache_key = hashlib.sha256(f"{model_key}:{prompt}".encode()).hexdigest()[:16]
    cache_path = CACHE_DIR / f"{model_key}_{cache_key}.json"

    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        return cached["response"]

    config = MODELS[model_key]
    provider = config["provider"]
    model = config["model"]

    if provider == "openai":
        import openai
        client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=1024,
        )
        text = resp.choices[0].message.content.strip()

    elif provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        resp = client.messages.create(
            model=model,
            max_tokens=1024,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()

    else:
        raise ValueError(f"Unknown provider: {provider}")

    # Cache
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({
        "model_key": model_key,
        "prompt": prompt,
        "response": text,
    }, indent=2))

    return text


# ═══════════════════════════════════════════════════════════════════════════
# Candidate pool
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class PilotCandidate:
    premise_id: str
    nl: str
    gold_fol: str
    broken_fol: str
    error_type: str  # "partial", "overweak", "overstrong", "B_arg_swap", "B_negation_drop"
    source: str  # "exp_a" or "exp_b"


def load_broken_gold_candidates() -> List[PilotCandidate]:
    """Load broken gold premises with hand-corrections from corrections_template.md."""
    if not CORRECTIONS_PATH.exists():
        return []

    text = CORRECTIONS_PATH.read_text()
    candidates = []

    sections = text.split("\n## ")[1:]
    for section in sections:
        lines = section.strip().split("\n")
        pid = lines[0].strip()

        nl = ""
        gold_broken = ""
        correct_fol = ""

        for line in lines:
            if line.startswith("NL:"):
                nl = line[4:].strip().strip('"')
            elif line.startswith("Gold FOL (broken):"):
                gold_broken = line[len("Gold FOL (broken):"):].strip()
            elif line.startswith("c_correct_fol:"):
                correct_fol = line[len("c_correct_fol:"):].strip()

        if nl and correct_fol and gold_broken:
            candidates.append(PilotCandidate(
                premise_id=pid,
                nl=nl,
                gold_fol=correct_fol,       # The correction IS the gold for scoring
                broken_fol=gold_broken,      # The broken gold is what the LLM corrects
                error_type="broken_gold",
                source="broken_gold",
            ))

    return candidates


def build_candidate_pool(seed: int = 42, n: int = 30) -> List[PilotCandidate]:
    """Build the pilot candidate pool from Exp A + Exp B + broken gold."""
    rng = random.Random(seed)

    # Load NL map
    nl_map = {}
    for line in SUITES_PATH.read_text().strip().split("\n"):
        row = json.loads(line)
        nl_map[row["premise_id"]] = row.get("nl", "")

    # Load Exp B gold FOLs and candidates
    exp2_gold = {}
    for line in (EXP2_DIR / "curated_premises.jsonl").read_text().strip().split("\n"):
        row = json.loads(line)
        exp2_gold[row["premise_id"]] = row["gold_fol"]

    exp2_candidates = []
    for line in (EXP2_DIR / "scored_candidates.jsonl").read_text().strip().split("\n"):
        row = json.loads(line)
        if row["candidate_type"] in ("partial", "overweak", "overstrong"):
            pid = row["premise_id"]
            exp2_candidates.append(PilotCandidate(
                premise_id=pid,
                nl=nl_map.get(pid, ""),
                gold_fol=exp2_gold.get(pid, ""),
                broken_fol=row["candidate_fol"],
                error_type=row["candidate_type"],
                source="exp_b",
            ))

    # Load Exp A gold FOLs and candidates
    exp1_gold = {}
    for line in (EXP1_DIR / "aligned_subset_manifest.jsonl").read_text().strip().split("\n"):
        row = json.loads(line)
        if row.get("passes"):
            exp1_gold[row["premise_id"]] = row["gold_fol"]

    exp1_candidates = []
    for line in (EXP1_DIR / "scored_candidates.jsonl").read_text().strip().split("\n"):
        row = json.loads(line)
        if row["candidate_type"] in ("B_arg_swap", "B_negation_drop"):
            pid = row["premise_id"]
            exp1_candidates.append(PilotCandidate(
                premise_id=pid,
                nl=nl_map.get(pid, ""),
                gold_fol=exp1_gold.get(pid, ""),
                broken_fol=row["candidate_fol"],
                error_type=row["candidate_type"],
                source="exp_a",
            ))

    # Load broken gold with hand-corrections
    broken_gold = load_broken_gold_candidates()

    # Sample mix: 40% Exp B + 40% Exp A + 20% broken gold (per doc spec)
    partial = [c for c in exp2_candidates if c.error_type == "partial"]
    overweak = [c for c in exp2_candidates if c.error_type == "overweak"]
    overstrong = [c for c in exp2_candidates if c.error_type == "overstrong"]
    arg_swap = [c for c in exp1_candidates if c.error_type == "B_arg_swap"]
    neg_drop = [c for c in exp1_candidates if c.error_type == "B_negation_drop"]

    pool = []
    pool += rng.sample(partial, min(5, len(partial)))
    pool += rng.sample(overweak, min(4, len(overweak)))
    pool += rng.sample(overstrong, min(3, len(overstrong)))
    pool += rng.sample(arg_swap, min(6, len(arg_swap)))
    pool += rng.sample(neg_drop, min(6, len(neg_drop)))
    pool += rng.sample(broken_gold, min(6, len(broken_gold)))

    rng.shuffle(pool)
    return pool[:n]


# ═══════════════════════════════════════════════════════════════════════════
# Prompt templates
# ═══════════════════════════════════════════════════════════════════════════

CORRECTION_PROMPT_BASE = """You are given a natural-language sentence and a first-order logic (FOL) translation that may contain errors. Your task is to produce the correct FOL translation.

Natural language: {nl}

Candidate FOL (may be incorrect): {broken_fol}

Produce ONLY the corrected FOL formula. Use the same predicate and constant naming conventions as the candidate. Do not explain your reasoning — output only the formula."""

CORRECTION_PROMPT_SCORE = """You are given a natural-language sentence and a first-order logic (FOL) translation that may contain errors. A scoring system evaluated this translation and assigned it a quality score.

Natural language: {nl}

Candidate FOL (may be incorrect): {broken_fol}

Quality score: {score:.2f} out of 1.00

Produce ONLY the corrected FOL formula. Use the same predicate and constant naming conventions as the candidate. Do not explain your reasoning — output only the formula."""

CORRECTION_PROMPT_CATEGORY = """You are given a natural-language sentence and a first-order logic (FOL) translation that may contain errors. A diagnostic system identified specific issues with this translation.

Natural language: {nl}

Candidate FOL (may be incorrect): {broken_fol}

Diagnostic summary:
- Positive sub-entailment probes passed: {pos_passed}/{pos_total}
- Contrastive probes incorrectly entailed: {con_entailed}/{con_total}
{category_note}

Produce ONLY the corrected FOL formula. Use the same predicate and constant naming conventions as the candidate. Do not explain your reasoning — output only the formula."""

CORRECTION_PROMPT_PROBES = """You are given a natural-language sentence and a first-order logic (FOL) translation that may contain errors. A diagnostic system tested this translation against specific logical probes and identified failures.

Natural language: {nl}

Candidate FOL (may be incorrect): {broken_fol}

Failed probes (the candidate SHOULD entail these but does NOT):
{failed_positives}

Incorrectly entailed (the candidate should NOT entail these but DOES):
{entailed_contrastives}

Produce ONLY the corrected FOL formula. Use the same predicate and constant naming conventions as the candidate. Do not explain your reasoning — output only the formula."""


# ═══════════════════════════════════════════════════════════════════════════
# Scoring and evaluation
# ═══════════════════════════════════════════════════════════════════════════

def extract_fol_from_response(response: str) -> str:
    """Extract FOL formula from LLM response (strip markdown, explanations)."""
    # Remove markdown code blocks
    text = response.strip()
    if "```" in text:
        parts = text.split("```")
        # Take content inside first code block
        if len(parts) >= 3:
            text = parts[1].strip()
            if text.startswith("fol") or text.startswith("logic"):
                text = text.split("\n", 1)[1] if "\n" in text else text
    # Take first non-empty line if multiple lines
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if lines:
        return lines[0]
    return text


def check_correction(corrected_fol: str, gold_fol: str, timeout: int = 10) -> str:
    """Check if corrected FOL is equivalent to gold.

    Returns: "equivalent", "not_equivalent", "parse_error", "timeout"
    """
    try:
        normalized_gold = normalize_fol_string(gold_fol)
    except Exception:
        return "parse_error"

    try:
        fwd = check_entailment(corrected_fol, normalized_gold, timeout=timeout)
        if fwd is None:
            return "timeout"
        if fwd is False:
            return "not_equivalent"

        bwd = check_entailment(normalized_gold, corrected_fol, timeout=timeout)
        if bwd is None:
            return "timeout"
        if bwd is True:
            return "equivalent"
        return "not_equivalent"
    except Exception:
        return "parse_error"


def get_probe_feedback(candidate: PilotCandidate) -> Optional[Dict]:
    """Generate v2 suite and score candidate to get probe-level feedback."""
    try:
        result = generate_test_suite_from_gold(
            candidate.gold_fol, nl=candidate.nl,
            verify_round_trip=False, with_contrastives=True, timeout_s=10,
        )
        if result.suite is None:
            return None

        report = score(result.suite, candidate.broken_fol, timeout_s=10)

        # Detailed per-probe results
        failed_positives = []
        passed_positives = []
        entailed_contrastives = []
        rejected_contrastives = []

        for kind, fol, verdict in report.per_test_results:
            if kind == "positive":
                if verdict == "entailed":
                    passed_positives.append(fol)
                else:
                    failed_positives.append(fol)
            elif kind == "contrastive" and fol:
                if verdict == "entailed":
                    entailed_contrastives.append(fol)
                else:
                    rejected_contrastives.append(fol)

        return {
            "recall": report.recall,
            "precision": report.precision,
            "positives_total": report.positives_total,
            "positives_entailed": report.positives_entailed,
            "contrastives_total": report.contrastives_total,
            "contrastives_rejected": report.contrastives_rejected,
            "failed_positives": failed_positives,
            "passed_positives": passed_positives,
            "entailed_contrastives": entailed_contrastives,
            "rejected_contrastives": rejected_contrastives,
        }
    except Exception as e:
        logger.warning("Probe feedback failed for %s: %s", candidate.premise_id, e)
        return None


# ═══════════════════════════════════════════════════════════════════════════
# Pilots
# ═══════════════════════════════════════════════════════════════════════════

def pilot1_baseline(candidates: List[PilotCandidate], models: List[str]) -> Dict:
    """Pilot 1: No-feedback correction rate."""
    print()
    print("=" * 70)
    print("PILOT 1: Baseline Correction Rate (no feedback)")
    print("=" * 70)
    print(f"Candidates: {len(candidates)}, Models: {models}")
    print()

    results = defaultdict(lambda: defaultdict(list))

    for i, cand in enumerate(candidates):
        print(f"  [{i+1}/{len(candidates)}] {cand.premise_id} ({cand.error_type})...")
        prompt = CORRECTION_PROMPT_BASE.format(
            nl=cand.nl, broken_fol=cand.broken_fol,
        )

        for model in models:
            response = call_llm(model, prompt)
            corrected = extract_fol_from_response(response)
            verdict = check_correction(corrected, cand.gold_fol)

            results[model][cand.error_type].append({
                "premise_id": cand.premise_id,
                "verdict": verdict,
                "corrected_fol": corrected,
            })

    # Summary
    print()
    print("PILOT 1 RESULTS")
    print("-" * 60)
    print(f"{'Model':<16} {'Type':<16} {'Equiv':>6} {'Total':>6} {'Rate':>8}")
    print("-" * 60)

    summary = {}
    for model in models:
        model_total = 0
        model_equiv = 0
        for etype, items in sorted(results[model].items()):
            equiv = sum(1 for r in items if r["verdict"] == "equivalent")
            total = len(items)
            model_total += total
            model_equiv += equiv
            rate = equiv / total if total else 0
            print(f"{model:<16} {etype:<16} {equiv:>6} {total:>6} {rate:>7.0%}")

        overall_rate = model_equiv / model_total if model_total else 0
        print(f"{model:<16} {'OVERALL':<16} {model_equiv:>6} {model_total:>6} {overall_rate:>7.0%}")
        print()
        summary[model] = {
            "overall_rate": round(overall_rate, 4),
            "n": model_total,
            "equiv": model_equiv,
            "by_type": {
                etype: {
                    "rate": round(sum(1 for r in items if r["verdict"] == "equivalent") / len(items), 4),
                    "n": len(items),
                }
                for etype, items in results[model].items()
            },
        }

    # Decision
    for model, s in summary.items():
        rate = s["overall_rate"]
        if rate > 0.60:
            decision = "TOO EASY — harden candidates or drop source"
        elif rate < 0.10:
            decision = "TOO HARD — drop source"
        else:
            decision = "IN BAND (20-50%) — keep"
        print(f"  {model}: {rate:.0%} → {decision}")

    return {"pilot1": summary, "raw": {m: dict(v) for m, v in results.items()}}


def pilot2_leakage(candidates: List[PilotCandidate], model: str) -> Dict:
    """Pilot 2: Leakage probe — test 3 diagnostic granularities."""
    print()
    print("=" * 70)
    print(f"PILOT 2: Leakage Probe ({model})")
    print("=" * 70)
    print(f"Candidates: {len(candidates)}")
    print()

    # Get probe feedback for all candidates
    print("Generating probe feedback...")
    feedbacks = {}
    for cand in candidates:
        fb = get_probe_feedback(cand)
        if fb:
            feedbacks[cand.premise_id] = fb

    print(f"  Got feedback for {len(feedbacks)}/{len(candidates)} candidates")
    print()

    # Conditions: no_feedback, score_only, category, probes
    conditions = ["no_feedback", "score_only", "category", "probes"]
    results = {cond: [] for cond in conditions}

    for i, cand in enumerate(candidates):
        if cand.premise_id not in feedbacks:
            continue
        fb = feedbacks[cand.premise_id]
        print(f"  [{i+1}/{len(candidates)}] {cand.premise_id} ({cand.error_type})...")

        # Condition 1: No feedback
        prompt_nf = CORRECTION_PROMPT_BASE.format(nl=cand.nl, broken_fol=cand.broken_fol)
        resp_nf = call_llm(model, prompt_nf)
        corrected_nf = extract_fol_from_response(resp_nf)
        verdict_nf = check_correction(corrected_nf, cand.gold_fol)
        results["no_feedback"].append({"premise_id": cand.premise_id, "verdict": verdict_nf})

        # Condition 2: Score only
        prompt_so = CORRECTION_PROMPT_SCORE.format(
            nl=cand.nl, broken_fol=cand.broken_fol, score=fb["recall"],
        )
        resp_so = call_llm(model, prompt_so)
        corrected_so = extract_fol_from_response(resp_so)
        verdict_so = check_correction(corrected_so, cand.gold_fol)
        results["score_only"].append({"premise_id": cand.premise_id, "verdict": verdict_so})

        # Condition 3: Category-level
        pos_passed = fb["positives_entailed"]
        pos_total = fb["positives_total"]
        con_entailed = fb["contrastives_total"] - fb["contrastives_rejected"]
        con_total = fb["contrastives_total"]

        if con_entailed > 0:
            category_note = "Issue: the translation entails formulas it should not (overstrong)."
        elif pos_passed < pos_total:
            category_note = "Issue: the translation fails to entail expected consequences (underspec)."
        else:
            category_note = ""

        prompt_cat = CORRECTION_PROMPT_CATEGORY.format(
            nl=cand.nl, broken_fol=cand.broken_fol,
            pos_passed=pos_passed, pos_total=pos_total,
            con_entailed=con_entailed, con_total=con_total,
            category_note=category_note,
        )
        resp_cat = call_llm(model, prompt_cat)
        corrected_cat = extract_fol_from_response(resp_cat)
        verdict_cat = check_correction(corrected_cat, cand.gold_fol)
        results["category"].append({"premise_id": cand.premise_id, "verdict": verdict_cat})

        # Condition 4: Full probe formulas
        failed_pos_str = "\n".join(f"  - {fol}" for fol in fb["failed_positives"][:5]) or "  (none)"
        entailed_con_str = "\n".join(f"  - {fol}" for fol in fb["entailed_contrastives"][:5]) or "  (none)"

        prompt_probes = CORRECTION_PROMPT_PROBES.format(
            nl=cand.nl, broken_fol=cand.broken_fol,
            failed_positives=failed_pos_str,
            entailed_contrastives=entailed_con_str,
        )
        resp_probes = call_llm(model, prompt_probes)
        corrected_probes = extract_fol_from_response(resp_probes)
        verdict_probes = check_correction(corrected_probes, cand.gold_fol)
        results["probes"].append({"premise_id": cand.premise_id, "verdict": verdict_probes})

    # Summary
    print()
    print("PILOT 2 RESULTS")
    print("-" * 50)
    summary = {}
    for cond in conditions:
        equiv = sum(1 for r in results[cond] if r["verdict"] == "equivalent")
        total = len(results[cond])
        rate = equiv / total if total else 0
        print(f"  {cond:<16}: {equiv}/{total} = {rate:.0%}")
        summary[cond] = {"rate": round(rate, 4), "n": total, "equiv": equiv}

    print()
    # Decision
    rates = {c: summary[c]["rate"] for c in conditions}
    nf_rate = rates["no_feedback"]
    gains = {c: rates[c] - nf_rate for c in conditions if c != "no_feedback"}

    print("  Gains over no_feedback:")
    for cond, gain in gains.items():
        print(f"    {cond:<16}: {gain:+.0%}")

    # Pick coarsest that helps
    if gains["category"] >= 0.05:
        chosen = "category"
    elif gains["probes"] >= 0.05:
        chosen = "probes"
    else:
        chosen = "score_only"

    print(f"\n  Chosen granularity: {chosen}")
    if chosen == "probes" and gains["category"] < gains["probes"] - 0.1:
        print("  WARNING: Only fine-grained helps — possible leakage risk.")

    summary["chosen_granularity"] = chosen
    summary["gains"] = gains
    return {"pilot2": summary, "raw": results}


def pilot3_overcorrection(candidates: List[PilotCandidate], model: str) -> Dict:
    """Pilot 3: Over-correction check on partial candidates."""
    print()
    print("=" * 70)
    print(f"PILOT 3: Over-Correction Check ({model})")
    print("=" * 70)

    # Use only partial candidates (close to correct)
    partials = [c for c in candidates if c.error_type == "partial"]
    print(f"Partial candidates: {len(partials)}")
    print()

    if not partials:
        print("  No partial candidates available.")
        return {"pilot3": {"error": "no_partial_candidates"}}

    # Get probe feedback for generating diagnostic
    print("Generating probe feedback...")
    feedbacks = {}
    for cand in partials:
        fb = get_probe_feedback(cand)
        if fb:
            feedbacks[cand.premise_id] = fb

    results_score = []
    results_diag = []

    for i, cand in enumerate(partials):
        if cand.premise_id not in feedbacks:
            continue
        fb = feedbacks[cand.premise_id]
        print(f"  [{i+1}/{len(partials)}] {cand.premise_id}...")

        # Score the broken candidate itself
        broken_verdict = check_correction(cand.broken_fol, cand.gold_fol)
        broken_recall = fb["recall"]

        # Condition A: Score-only correction
        prompt_so = CORRECTION_PROMPT_SCORE.format(
            nl=cand.nl, broken_fol=cand.broken_fol, score=fb["recall"],
        )
        resp_so = call_llm(model, prompt_so)
        corrected_so = extract_fol_from_response(resp_so)
        verdict_so = check_correction(corrected_so, cand.gold_fol)

        # Score the correction against v2 suite to check for regression
        try:
            result = generate_test_suite_from_gold(
                cand.gold_fol, nl=cand.nl, verify_round_trip=False,
                with_contrastives=True, timeout_s=10,
            )
            if result.suite:
                report_so = score(result.suite, corrected_so, timeout_s=10)
                corrected_recall_so = report_so.recall
            else:
                corrected_recall_so = None
        except Exception:
            corrected_recall_so = None

        results_score.append({
            "premise_id": cand.premise_id,
            "broken_recall": broken_recall,
            "corrected_recall": corrected_recall_so,
            "verdict": verdict_so,
            "regressed": corrected_recall_so is not None and corrected_recall_so < broken_recall,
        })

        # Condition B: Diagnostic correction (category level)
        pos_passed = fb["positives_entailed"]
        pos_total = fb["positives_total"]
        con_entailed = fb["contrastives_total"] - fb["contrastives_rejected"]
        con_total = fb["contrastives_total"]
        category_note = "Issue: the translation fails to entail expected consequences (underspec)."

        prompt_diag = CORRECTION_PROMPT_CATEGORY.format(
            nl=cand.nl, broken_fol=cand.broken_fol,
            pos_passed=pos_passed, pos_total=pos_total,
            con_entailed=con_entailed, con_total=con_total,
            category_note=category_note,
        )
        resp_diag = call_llm(model, prompt_diag)
        corrected_diag = extract_fol_from_response(resp_diag)
        verdict_diag = check_correction(corrected_diag, cand.gold_fol)

        try:
            if result.suite:
                report_diag = score(result.suite, corrected_diag, timeout_s=10)
                corrected_recall_diag = report_diag.recall
            else:
                corrected_recall_diag = None
        except Exception:
            corrected_recall_diag = None

        results_diag.append({
            "premise_id": cand.premise_id,
            "broken_recall": broken_recall,
            "corrected_recall": corrected_recall_diag,
            "verdict": verdict_diag,
            "regressed": corrected_recall_diag is not None and corrected_recall_diag < broken_recall,
        })

    # Summary
    print()
    print("PILOT 3 RESULTS")
    print("-" * 60)

    def classify_outcome(items):
        improved = sum(1 for r in items if r["verdict"] == "equivalent")
        regressed = sum(1 for r in items if r.get("regressed"))
        unchanged = sum(1 for r in items
                       if r["verdict"] != "equivalent" and not r.get("regressed")
                       and r.get("corrected_recall") is not None
                       and abs((r["corrected_recall"] or 0) - r["broken_recall"]) < 0.01)
        partial_improved = len(items) - improved - regressed - unchanged
        return {"improved": improved, "regressed": regressed,
                "unchanged": unchanged, "partial_improved": partial_improved,
                "total": len(items)}

    score_outcomes = classify_outcome(results_score)
    diag_outcomes = classify_outcome(results_diag)

    print(f"  {'Outcome':<20} {'Score-only':>12} {'Diagnostic':>12}")
    print(f"  {'-'*44}")
    for key in ["improved", "partial_improved", "unchanged", "regressed"]:
        print(f"  {key:<20} {score_outcomes[key]:>12} {diag_outcomes[key]:>12}")
    print(f"  {'total':<20} {score_outcomes['total']:>12} {diag_outcomes['total']:>12}")

    regression_rate_score = score_outcomes["regressed"] / score_outcomes["total"] if score_outcomes["total"] else 0
    regression_rate_diag = diag_outcomes["regressed"] / diag_outcomes["total"] if diag_outcomes["total"] else 0
    print()
    print(f"  Regression rate (score-only): {regression_rate_score:.0%}")
    print(f"  Regression rate (diagnostic): {regression_rate_diag:.0%}")

    if regression_rate_diag > regression_rate_score + 0.1:
        print("  WARNING: Diagnostic causes significantly more regression.")
    else:
        print("  OK: Diagnostic does not cause excess regression.")

    return {
        "pilot3": {
            "score_only": score_outcomes,
            "diagnostic": diag_outcomes,
            "regression_rate_score": round(regression_rate_score, 4),
            "regression_rate_diag": round(regression_rate_diag, 4),
        },
        "raw_score": results_score,
        "raw_diag": results_diag,
    }


def pilot4_scaling(candidates: List[PilotCandidate]) -> Dict:
    """Pilot 4: Model scaling sanity check across frontier/mid-tier/frontier-alt."""
    print()
    print("=" * 70)
    print("PILOT 4: Model Scaling Sanity Check")
    print("=" * 70)

    # Use a subset for scaling check
    subset = candidates[:15]
    models = list(MODELS.keys())
    print(f"Candidates: {len(subset)}, Models: {models}")
    print()

    results = defaultdict(list)

    for i, cand in enumerate(subset):
        print(f"  [{i+1}/{len(subset)}] {cand.premise_id} ({cand.error_type})...")
        prompt = CORRECTION_PROMPT_BASE.format(nl=cand.nl, broken_fol=cand.broken_fol)

        for model in models:
            response = call_llm(model, prompt)
            corrected = extract_fol_from_response(response)
            verdict = check_correction(corrected, cand.gold_fol)
            results[model].append({
                "premise_id": cand.premise_id,
                "error_type": cand.error_type,
                "verdict": verdict,
            })

    # Summary
    print()
    print("PILOT 4 RESULTS")
    print("-" * 50)
    summary = {}
    for model in models:
        equiv = sum(1 for r in results[model] if r["verdict"] == "equivalent")
        total = len(results[model])
        rate = equiv / total if total else 0
        print(f"  {model:<16}: {equiv}/{total} = {rate:.0%}")
        summary[model] = {"rate": round(rate, 4), "n": total, "equiv": equiv}

    # Decision
    print()
    rates = {m: summary[m]["rate"] for m in models}
    if all(r > 0.6 for r in rates.values()):
        print("  All models saturate (>60%). Focus on harder candidates.")
    elif all(r < 0.1 for r in rates.values()):
        print("  All models fail (<10%). Task too hard at this scale.")
    else:
        print("  Signal detected across scales. Proceed with all models.")

    return {"pilot4": summary, "raw": dict(results)}


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="C2 Pilots")
    parser.add_argument("--pilot", default="all", help="1|2|3|4|all")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if not is_vampire_available():
        print("ERROR: Vampire required.")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Build candidate pool
    candidates = build_candidate_pool(seed=args.seed, n=30)
    print(f"Candidate pool: {len(candidates)}")
    for etype in sorted(set(c.error_type for c in candidates)):
        n = sum(1 for c in candidates if c.error_type == etype)
        print(f"  {etype}: {n}")
    print()

    all_results = {}

    if args.pilot in ("1", "all"):
        # Pilot 1: baseline with frontier + mid-tier + frontier-alt
        r1 = pilot1_baseline(candidates, ["gpt-4o", "gpt-4o-mini", "claude-sonnet"])
        all_results.update(r1)

    if args.pilot in ("2", "all"):
        # Pilot 2: leakage probe with frontier model
        r2 = pilot2_leakage(candidates[:20], "gpt-4o")
        all_results.update(r2)

    if args.pilot in ("3", "all"):
        # Pilot 3: over-correction on partial candidates
        r3 = pilot3_overcorrection(candidates, "gpt-4o")
        all_results.update(r3)

    if args.pilot in ("4", "all"):
        # Pilot 4: scaling check across all models
        r4 = pilot4_scaling(candidates)
        all_results.update(r4)

    # Save consolidated report
    report_path = OUT_DIR / "pilot_results.json"
    # Separate raw from summary for cleaner report
    summary = {k: v for k, v in all_results.items() if not k.startswith("raw")}
    report_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nConsolidated report: {report_path}")

    # Save full raw data
    raw_path = OUT_DIR / "pilot_raw.json"
    raw_path.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"Full raw data: {raw_path}")


if __name__ == "__main__":
    main()
