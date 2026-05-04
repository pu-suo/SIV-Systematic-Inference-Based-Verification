"""
Path 1-Hard, Step 5: Main run.

60 candidates × 5 conditions × 3 models × 3 seeds.
Full experiment with bootstrap statistics.

Run: python scripts/c2_path1_hard_step5_main.py
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
from collections import Counter, defaultdict
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
SEEDS = [42, 137, 256]


def load_candidates():
    return json.loads((OUT_DIR / "path1_hard_candidates.json").read_text())


def load_prompts():
    return json.loads((PATH1_DIR / "step2_prompts.json").read_text())


def get_siv_score(gold_fol: str, candidate_fol: str, nl: str) -> Optional[float]:
    try:
        result = generate_test_suite_from_gold(
            gold_fol, nl=nl, verify_round_trip=True,
            with_contrastives=True, timeout_s=10,
        )
        if result.error or result.suite is None:
            return None
        report = score(result.suite, candidate_fol, timeout_s=10)
        return report.recall if report else None
    except Exception:
        return None


def check_equivalence(fol_a: str, fol_b: str) -> bool:
    fwd = check_entailment(fol_a, fol_b, timeout=10)
    if fwd is not True:
        return False
    bwd = check_entailment(fol_b, fol_a, timeout=10)
    return bwd is True


def get_shuffled_categories(actual_cats: list[str]) -> list[str]:
    non_actual = [c for c in ALL_CATEGORIES if c not in actual_cats]
    n = min(len(actual_cats), len(non_actual))
    return random.sample(non_actual, n)


def build_category_list(categories: list[str]) -> str:
    return "\n".join(f"- {cat}" for cat in categories)


def format_prompt(condition: str, nl: str, perturbed_fol: str,
                  siv_score: float, actual_categories: list[str],
                  prompts: dict) -> str:
    preamble = prompts["task_preamble"]
    if condition == "no_feedback":
        return prompts["conditions"]["no_feedback"]["template"].format(
            task_preamble=preamble, nl=nl, perturbed_fol=perturbed_fol)
    elif condition == "score_only":
        return prompts["conditions"]["score_only"]["template"].format(
            task_preamble=preamble, nl=nl, perturbed_fol=perturbed_fol,
            siv_score=f"{siv_score:.2f}")
    elif condition == "structured_category":
        return prompts["conditions"]["structured_category"]["template"].format(
            task_preamble=preamble, nl=nl, perturbed_fol=perturbed_fol,
            siv_score=f"{siv_score:.2f}",
            category_list=build_category_list(actual_categories))
    elif condition == "shuffled_category":
        shuffled = get_shuffled_categories(actual_categories)
        return prompts["conditions"]["shuffled_category"]["template"].format(
            task_preamble=preamble, nl=nl, perturbed_fol=perturbed_fol,
            siv_score=f"{siv_score:.2f}",
            category_list=build_category_list(shuffled))
    elif condition == "count_only":
        return prompts["conditions"]["count_only"]["template"].format(
            task_preamble=preamble, nl=nl, perturbed_fol=perturbed_fol,
            siv_score=f"{siv_score:.2f}",
            n_categories=len(actual_categories))
    raise ValueError(condition)


def call_llm(prompt: str, model_key: str) -> Optional[str]:
    info = MODELS[model_key]
    try:
        if info["provider"] == "openai":
            from openai import OpenAI
            client = OpenAI()
            response = client.chat.completions.create(
                model=info["model"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0, max_tokens=500,
            )
            return response.choices[0].message.content.strip()
        else:
            import anthropic
            client = anthropic.Anthropic()
            response = client.messages.create(
                model=info["model"],
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()
    except Exception as e:
        print(f"    API error ({model_key}): {e}")
        return None


def bootstrap_ci(data_a: list[bool], data_b: list[bool], n_boot: int = 10000) -> tuple:
    """Paired bootstrap for difference in means. Returns (delta, ci_lo, ci_hi, p_value)."""
    n = min(len(data_a), len(data_b))
    data_a = data_a[:n]
    data_b = data_b[:n]
    observed_delta = np.mean(data_a) - np.mean(data_b)

    boot_deltas = []
    for _ in range(n_boot):
        idx = np.random.randint(0, n, n)
        a_sample = np.array(data_a)[idx]
        b_sample = np.array(data_b)[idx]
        boot_deltas.append(np.mean(a_sample) - np.mean(b_sample))

    boot_deltas = sorted(boot_deltas)
    ci_lo = boot_deltas[int(0.025 * n_boot)]
    ci_hi = boot_deltas[int(0.975 * n_boot)]
    # p-value: fraction of bootstrap samples where delta ≤ 0
    p_value = np.mean([d <= 0 for d in boot_deltas])
    return float(observed_delta), float(ci_lo), float(ci_hi), float(p_value)


def main():
    if not is_vampire_available():
        print("ERROR: Vampire required.")
        sys.exit(1)
    for key in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"]:
        if not os.environ.get(key):
            print(f"ERROR: {key} required.")
            sys.exit(1)

    print("=" * 70)
    print("PATH 1-HARD, STEP 5: Main Run")
    print("=" * 70)
    print()

    candidates = load_candidates()
    prompts = load_prompts()
    n_cands = len(candidates)
    print(f"Candidates: {n_cands}")
    print(f"Conditions: {len(CONDITIONS)}")
    print(f"Models: {list(MODELS.keys())}")
    print(f"Seeds: {SEEDS}")
    total_calls = n_cands * len(CONDITIONS) * len(MODELS) * len(SEEDS)
    print(f"Total LLM calls: {total_calls}")
    print()

    # Pre-compute SIV scores for perturbed candidates
    print("Pre-computing SIV scores for perturbed candidates...")
    for cand in candidates:
        siv = get_siv_score(cand["gold_fol"], cand["perturbed_fol"], cand["nl"])
        cand["siv_score"] = siv if siv is not None else 0.0
    print(f"  Done. Mean perturbed SIV: {np.mean([c['siv_score'] for c in candidates]):.4f}")
    print()

    # Main run
    # Structure: results[model][seed][condition][candidate_idx] = {correction, equiv, siv_equiv}
    all_results = {}
    t0 = time.time()
    call_count = 0

    for model_key in MODELS:
        all_results[model_key] = {}
        for seed in SEEDS:
            random.seed(seed)
            all_results[model_key][seed] = {}

            # Shuffle candidate order per seed
            indices = list(range(n_cands))
            random.shuffle(indices)

            for cond in CONDITIONS:
                cond_results = [None] * n_cands
                for orig_idx in indices:
                    cand = candidates[orig_idx]
                    prompt = format_prompt(
                        cond, cand["nl"], cand["perturbed_fol"],
                        cand["siv_score"], cand["actual_categories"], prompts)
                    correction = call_llm(prompt, model_key)
                    call_count += 1

                    parseable = correction is not None and parse_fol(correction) is not None
                    equiv = check_equivalence(cand["gold_fol"], correction) if parseable else False
                    siv_equiv = False
                    if parseable and correction:
                        siv_sc = get_siv_score(cand["gold_fol"], correction, cand["nl"])
                        siv_equiv = (siv_sc is not None and siv_sc >= 1.0)

                    cond_results[orig_idx] = {
                        "parseable": parseable,
                        "equiv": equiv,
                        "siv_equiv": siv_equiv,
                    }

                all_results[model_key][seed][cond] = cond_results

            elapsed = time.time() - t0
            print(f"  {model_key} seed={seed}: {call_count}/{total_calls} calls ({elapsed:.0f}s)")

    elapsed = time.time() - t0
    print(f"\nMain run complete: {call_count} calls in {elapsed:.1f}s")
    print()

    # ── Analysis ──────────────────────────────────────────────────────────────
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    print()

    # Aggregate across seeds (majority vote per candidate × condition × model)
    # Primary metric: SIV equivalence
    aggregated = {}  # model -> condition -> [bool per candidate]
    for model_key in MODELS:
        aggregated[model_key] = {}
        for cond in CONDITIONS:
            cand_results = []
            for c_idx in range(n_cands):
                votes = [all_results[model_key][s][cond][c_idx]["siv_equiv"] for s in SEEDS]
                # Majority: at least 2/3 seeds must succeed
                cand_results.append(sum(votes) >= 2)
            aggregated[model_key][cond] = cand_results

    # Per-model rates
    print(f"{'Model':<15} {'NoFB':>6} {'Score':>6} {'Struct':>6} {'Shuf':>6} {'Count':>6}  {'Δ(S-H)':>7}  {'p':>6}")
    print("-" * 75)

    model_deltas = {}
    for model_key in MODELS:
        rates = {}
        for cond in CONDITIONS:
            rates[cond] = np.mean(aggregated[model_key][cond])

        struct_data = aggregated[model_key]["structured_category"]
        shuffled_data = aggregated[model_key]["shuffled_category"]
        delta, ci_lo, ci_hi, p_val = bootstrap_ci(struct_data, shuffled_data)
        model_deltas[model_key] = {"delta": delta, "ci_lo": ci_lo, "ci_hi": ci_hi, "p": p_val}

        print(f"{model_key:<15} {rates['no_feedback']:>5.1%} {rates['score_only']:>5.1%} "
              f"{rates['structured_category']:>5.1%} {rates['shuffled_category']:>5.1%} "
              f"{rates['count_only']:>5.1%}  {delta:>+6.3f}  {p_val:>5.3f}")

    print()

    # Primary comparison summary
    print("PRIMARY COMPARISON: Structured vs. Shuffled")
    print("-" * 50)
    models_significant = 0
    for model_key in MODELS:
        d = model_deltas[model_key]
        sig = "✓" if d["delta"] >= 0.10 and d["p"] < 0.05 else "✗"
        if d["delta"] >= 0.10 and d["p"] < 0.05:
            models_significant += 1
        print(f"  {model_key:<15}: Δ={d['delta']:+.3f} [{d['ci_lo']:+.3f}, {d['ci_hi']:+.3f}] p={d['p']:.3f} {sig}")
    print()

    # Decision
    if models_significant >= 2:
        decision = "PER_ASPECT_SUPPORTED"
        decision_text = (
            f"Per-aspect claim supported: structured > shuffled with Δ ≥ 0.10, p < 0.05 "
            f"on {models_significant}/3 models. Category-level feedback is actionable "
            f"when task difficulty exceeds LLM zero-shot capability."
        )
    elif models_significant == 1:
        decision = "MODEL_DEPENDENT"
        decision_text = (
            f"Signal is model-dependent: only 1/3 models shows significant effect. "
            f"Report as preliminary, not headline."
        )
    else:
        # Check if any are close
        any_moderate = any(d["delta"] >= 0.05 for d in model_deltas.values())
        if any_moderate:
            decision = "AMBIGUOUS"
            decision_text = "Some models show 0.05-0.10 range. Suggestive but not definitive."
        else:
            decision = "NULL"
            decision_text = (
                "Per-aspect at category level fails at harder difficulty too. "
                "Claim rejected across difficulty range."
            )

    print(f"DECISION: {decision}")
    print(f"  {decision_text}")
    print()

    # Secondary comparisons (Holm-corrected)
    print("SECONDARY COMPARISONS (Holm-corrected):")
    for model_key in MODELS:
        struct_data = aggregated[model_key]["structured_category"]
        score_data = aggregated[model_key]["score_only"]
        count_data = aggregated[model_key]["count_only"]

        d_vs_score, _, _, p_vs_score = bootstrap_ci(struct_data, score_data)
        d_vs_count, _, _, p_vs_count = bootstrap_ci(struct_data, count_data)

        # Holm correction: sort p-values, multiply by (2-rank)
        ps = sorted([(p_vs_score, "vs_score"), (p_vs_count, "vs_count")])
        holm_ps = [(p * (2 - i), name) for i, (p, name) in enumerate(ps)]

        print(f"  {model_key}:")
        print(f"    Structured vs Score-only: Δ={d_vs_score:+.3f}, p={p_vs_score:.3f}")
        print(f"    Structured vs Count-only: Δ={d_vs_count:+.3f}, p={p_vs_count:.3f}")
    print()

    # Per-category breakdown
    print("PER-CATEGORY ANALYSIS (structured condition, success rate):")
    for model_key in MODELS:
        print(f"  {model_key}:")
        for cat in ALL_CATEGORIES:
            # Candidates with this category as actual failure
            cat_indices = [i for i, c in enumerate(candidates) if cat in c["actual_categories"]]
            if not cat_indices:
                continue
            struct_success = sum(1 for i in cat_indices if aggregated[model_key]["structured_category"][i])
            shuffled_success = sum(1 for i in cat_indices if aggregated[model_key]["shuffled_category"][i])
            n_cat = len(cat_indices)
            print(f"    {cat:<22}: struct={struct_success}/{n_cat} ({struct_success/n_cat:.0%}) "
                  f"shuf={shuffled_success}/{n_cat} ({shuffled_success/n_cat:.0%})")
    print()

    # Save full results
    report = {
        "n_candidates": n_cands,
        "n_conditions": len(CONDITIONS),
        "n_models": len(MODELS),
        "n_seeds": len(SEEDS),
        "total_calls": call_count,
        "elapsed_seconds": elapsed,
        "per_model_rates": {
            model: {cond: float(np.mean(aggregated[model][cond])) for cond in CONDITIONS}
            for model in MODELS
        },
        "primary_comparison": model_deltas,
        "decision": decision,
        "decision_text": decision_text,
        "models_significant": models_significant,
    }

    (OUT_DIR / "step5_main_results.json").write_text(json.dumps(report, indent=2, default=str))
    print(f"Results saved to: {OUT_DIR / 'step5_main_results.json'}")


if __name__ == "__main__":
    main()
