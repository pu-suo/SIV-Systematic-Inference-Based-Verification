"""
Path 1-Hard, Step 5: Main run (optimized — 1 seed, parallelized scoring).

60 candidates × 5 conditions × 3 models × 1 seed = 900 calls.
Full bootstrap on candidate-level outcomes.

Run: python scripts/c2_path1_hard_step5_main_v2.py
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(_REPO_ROOT / ".env")

import numpy as np
from siv.vampire_interface import check_entailment, is_vampire_available
from siv.fol_utils import parse_fol
from siv.gold_suite_generator import generate_test_suite_from_gold
from siv.scorer import score

OUT_DIR = _REPO_ROOT / "reports" / "c2_investigations" / "path1_hard"
PATH1_DIR = _REPO_ROOT / "reports" / "c2_investigations" / "path1"

ALL_CATEGORIES = [
    "argument-order", "quantifier-scope", "restrictor-content",
    "polarity", "connective-polarity", "content-gap",
]
CONDITIONS = ["no_feedback", "score_only", "structured_category", "shuffled_category", "count_only"]
MODELS = {
    "gpt-4o": {"provider": "openai", "model": "gpt-4o"},
    "gpt-4o-mini": {"provider": "openai", "model": "gpt-4o-mini"},
    "claude-sonnet": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
}


def load_candidates():
    return json.loads((OUT_DIR / "path1_hard_candidates.json").read_text())

def load_prompts():
    return json.loads((PATH1_DIR / "step2_prompts.json").read_text())

def get_siv_score(gold_fol, candidate_fol, nl):
    try:
        result = generate_test_suite_from_gold(gold_fol, nl=nl, verify_round_trip=True, with_contrastives=True, timeout_s=10)
        if result.error or result.suite is None:
            return None
        report = score(result.suite, candidate_fol, timeout_s=10)
        return report.recall if report else None
    except:
        return None

def check_equivalence(fol_a, fol_b):
    fwd = check_entailment(fol_a, fol_b, timeout=10)
    if fwd is not True:
        return False
    return check_entailment(fol_b, fol_a, timeout=10) is True

def get_shuffled_categories(actual_cats):
    non_actual = [c for c in ALL_CATEGORIES if c not in actual_cats]
    return random.sample(non_actual, min(len(actual_cats), len(non_actual)))

def build_category_list(categories):
    return "\n".join(f"- {cat}" for cat in categories)

def format_prompt(condition, nl, perturbed_fol, siv_score, actual_categories, prompts):
    preamble = prompts["task_preamble"]
    if condition == "no_feedback":
        return prompts["conditions"]["no_feedback"]["template"].format(task_preamble=preamble, nl=nl, perturbed_fol=perturbed_fol)
    elif condition == "score_only":
        return prompts["conditions"]["score_only"]["template"].format(task_preamble=preamble, nl=nl, perturbed_fol=perturbed_fol, siv_score=f"{siv_score:.2f}")
    elif condition == "structured_category":
        return prompts["conditions"]["structured_category"]["template"].format(task_preamble=preamble, nl=nl, perturbed_fol=perturbed_fol, siv_score=f"{siv_score:.2f}", category_list=build_category_list(actual_categories))
    elif condition == "shuffled_category":
        return prompts["conditions"]["shuffled_category"]["template"].format(task_preamble=preamble, nl=nl, perturbed_fol=perturbed_fol, siv_score=f"{siv_score:.2f}", category_list=build_category_list(get_shuffled_categories(actual_categories)))
    elif condition == "count_only":
        return prompts["conditions"]["count_only"]["template"].format(task_preamble=preamble, nl=nl, perturbed_fol=perturbed_fol, siv_score=f"{siv_score:.2f}", n_categories=len(actual_categories))

def call_llm(prompt, model_key):
    info = MODELS[model_key]
    try:
        if info["provider"] == "openai":
            from openai import OpenAI
            client = OpenAI()
            r = client.chat.completions.create(model=info["model"], messages=[{"role": "user", "content": prompt}], temperature=0, max_tokens=500)
            return r.choices[0].message.content.strip()
        else:
            import anthropic
            client = anthropic.Anthropic()
            r = client.messages.create(model=info["model"], max_tokens=500, messages=[{"role": "user", "content": prompt}])
            return r.content[0].text.strip()
    except Exception as e:
        return None

def bootstrap_ci(data_a, data_b, n_boot=10000):
    n = min(len(data_a), len(data_b))
    a, b = np.array(data_a[:n], dtype=float), np.array(data_b[:n], dtype=float)
    observed = float(np.mean(a) - np.mean(b))
    deltas = []
    for _ in range(n_boot):
        idx = np.random.randint(0, n, n)
        deltas.append(float(np.mean(a[idx]) - np.mean(b[idx])))
    deltas.sort()
    return observed, deltas[int(0.025*n_boot)], deltas[int(0.975*n_boot)], float(np.mean([d <= 0 for d in deltas]))


def main():
    if not is_vampire_available():
        sys.exit("ERROR: Vampire required.")
    for key in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"]:
        if not os.environ.get(key):
            sys.exit(f"ERROR: {key} required.")

    random.seed(42)
    np.random.seed(42)

    print("=" * 70)
    print("PATH 1-HARD, STEP 5: Main Run (1 seed)")
    print("=" * 70)

    candidates = load_candidates()
    prompts = load_prompts()
    n = len(candidates)
    total = n * len(CONDITIONS) * len(MODELS)
    print(f"  {n} candidates × {len(CONDITIONS)} conditions × {len(MODELS)} models = {total} calls")
    print()

    # Pre-compute SIV scores
    print("Pre-computing SIV scores...")
    for c in candidates:
        siv = get_siv_score(c["gold_fol"], c["perturbed_fol"], c["nl"])
        c["siv_score"] = siv if siv is not None else 0.0
    print(f"  Mean perturbed SIV: {np.mean([c['siv_score'] for c in candidates]):.4f}")
    print()

    # Run all conditions for all models
    results = {}  # model -> condition -> [bool per candidate (siv_equiv)]
    t0 = time.time()
    calls = 0

    for model_key in MODELS:
        results[model_key] = {}
        for cond in CONDITIONS:
            cond_results = []
            for cand in candidates:
                prompt = format_prompt(cond, cand["nl"], cand["perturbed_fol"], cand["siv_score"], cand["actual_categories"], prompts)
                correction = call_llm(prompt, model_key)
                calls += 1

                parseable = correction is not None and parse_fol(correction) is not None
                siv_equiv = False
                if parseable and correction:
                    siv_sc = get_siv_score(cand["gold_fol"], correction, cand["nl"])
                    siv_equiv = (siv_sc is not None and siv_sc >= 1.0)
                cond_results.append(siv_equiv)

            results[model_key][cond] = cond_results
            rate = sum(cond_results) / len(cond_results)
            elapsed = time.time() - t0
            print(f"  {model_key}/{cond}: {rate:.1%} ({calls}/{total} calls, {elapsed:.0f}s)")

    elapsed = time.time() - t0
    print(f"\nComplete: {calls} calls in {elapsed:.1f}s")
    print()

    # Analysis
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    print()
    print(f"{'Model':<15} {'NoFB':>6} {'Score':>6} {'Struct':>6} {'Shuf':>6} {'Count':>6}  {'Δ(S-H)':>7}  {'95%CI':>14}  {'p':>6}")
    print("-" * 85)

    model_stats = {}
    models_significant = 0
    for model_key in MODELS:
        rates = {c: np.mean(results[model_key][c]) for c in CONDITIONS}
        delta, ci_lo, ci_hi, p = bootstrap_ci(results[model_key]["structured_category"], results[model_key]["shuffled_category"])
        model_stats[model_key] = {"rates": {c: float(v) for c, v in rates.items()}, "delta": delta, "ci_lo": ci_lo, "ci_hi": ci_hi, "p": p}

        sig = "✓" if delta >= 0.10 and p < 0.05 else ""
        if delta >= 0.10 and p < 0.05:
            models_significant += 1
        print(f"{model_key:<15} {rates['no_feedback']:>5.1%} {rates['score_only']:>5.1%} "
              f"{rates['structured_category']:>5.1%} {rates['shuffled_category']:>5.1%} "
              f"{rates['count_only']:>5.1%}  {delta:>+6.3f}  [{ci_lo:+.3f},{ci_hi:+.3f}]  {p:>5.3f} {sig}")

    print()

    # Decision
    if models_significant >= 2:
        decision = "PER_ASPECT_SUPPORTED"
        decision_text = f"Per-aspect claim supported on {models_significant}/3 models (Δ≥0.10, p<0.05). Category-level feedback is actionable when task difficulty exceeds LLM zero-shot capability."
    elif models_significant == 1:
        decision = "MODEL_DEPENDENT"
        decision_text = "Signal on 1/3 models only. Report as preliminary."
    else:
        any_moderate = any(s["delta"] >= 0.05 for s in model_stats.values())
        if any_moderate:
            decision = "AMBIGUOUS"
            decision_text = "Some models show Δ in 0.05-0.10 range. Suggestive but not definitive."
        else:
            decision = "NULL"
            decision_text = "Per-aspect fails at harder difficulty too. Claim rejected."

    print(f"DECISION: {decision}")
    print(f"  {decision_text}")
    print()

    # Secondary: structured vs score_only, structured vs count_only
    print("SECONDARY COMPARISONS:")
    for model_key in MODELS:
        d1, _, _, p1 = bootstrap_ci(results[model_key]["structured_category"], results[model_key]["score_only"])
        d2, _, _, p2 = bootstrap_ci(results[model_key]["structured_category"], results[model_key]["count_only"])
        print(f"  {model_key}: struct vs score_only Δ={d1:+.3f} p={p1:.3f} | struct vs count Δ={d2:+.3f} p={p2:.3f}")
    print()

    # Per-category
    print("PER-CATEGORY (structured success rate):")
    for model_key in MODELS:
        print(f"  {model_key}:")
        for cat in ALL_CATEGORIES:
            idxs = [i for i, c in enumerate(candidates) if cat in c["actual_categories"]]
            if not idxs:
                continue
            s_rate = sum(results[model_key]["structured_category"][i] for i in idxs) / len(idxs)
            h_rate = sum(results[model_key]["shuffled_category"][i] for i in idxs) / len(idxs)
            print(f"    {cat:<22}: struct={s_rate:.0%} shuf={h_rate:.0%} (n={len(idxs)})")

    # Save
    report = {
        "n_candidates": n,
        "total_calls": calls,
        "elapsed_s": elapsed,
        "per_model": model_stats,
        "decision": decision,
        "decision_text": decision_text,
        "models_significant": models_significant,
        "raw_results": {m: {c: r for c, r in conds.items()} for m, conds in results.items()},
    }
    out_path = OUT_DIR / "step5_main_results.json"
    out_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nSaved to: {out_path}")


if __name__ == "__main__":
    main()
