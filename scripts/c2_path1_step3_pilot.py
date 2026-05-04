"""
Path 1, Step 3: Pilot run.

20 candidates × 5 conditions × GPT-4o only × 1 seed.
Sanity checks + pilot Δ for primary comparison.

Run: python scripts/c2_path1_step3_pilot.py
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

from siv.vampire_interface import check_entailment, prove_strict, is_vampire_available
from siv.fol_utils import parse_fol
from siv.gold_suite_generator import generate_test_suite_from_gold
from siv.scorer import score

OUT_DIR = _REPO_ROOT / "reports" / "c2_investigations" / "path1"

ALL_CATEGORIES = [
    "argument-order", "quantifier-scope", "restrictor-content",
    "polarity", "connective-polarity", "content-gap",
]


def load_candidates():
    path = OUT_DIR / "path1_candidates_full.json"
    return json.loads(path.read_text())


def load_prompts():
    path = OUT_DIR / "step2_prompts.json"
    return json.loads(path.read_text())


def get_siv_score(gold_fol: str, candidate_fol: str, nl: str) -> Optional[float]:
    """Score candidate against gold-derived suite. Returns recall."""
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


def check_equivalence(fol_a: str, fol_b: str, timeout: int = 10) -> bool:
    fwd = check_entailment(fol_a, fol_b, timeout=timeout)
    if fwd is not True:
        return False
    bwd = check_entailment(fol_b, fol_a, timeout=timeout)
    return bwd is True


def build_category_list(categories: list[str]) -> str:
    return "\n".join(f"- {cat}" for cat in categories)


def get_shuffled_categories(actual_cats: list[str]) -> list[str]:
    """Per shuffling protocol: replace ALL actual with non-actual."""
    non_actual = [c for c in ALL_CATEGORIES if c not in actual_cats]
    n_to_draw = len(actual_cats)
    if n_to_draw > len(non_actual):
        n_to_draw = len(non_actual)
    return random.sample(non_actual, n_to_draw)


def format_prompt(condition: str, nl: str, perturbed_fol: str,
                  siv_score: float, actual_categories: list[str],
                  prompts: dict) -> str:
    """Build the prompt for a given condition."""
    preamble = prompts["task_preamble"]

    if condition == "no_feedback":
        return prompts["conditions"]["no_feedback"]["template"].format(
            task_preamble=preamble, nl=nl, perturbed_fol=perturbed_fol
        )
    elif condition == "score_only":
        return prompts["conditions"]["score_only"]["template"].format(
            task_preamble=preamble, nl=nl, perturbed_fol=perturbed_fol,
            siv_score=f"{siv_score:.2f}"
        )
    elif condition == "structured_category":
        cat_list = build_category_list(actual_categories)
        return prompts["conditions"]["structured_category"]["template"].format(
            task_preamble=preamble, nl=nl, perturbed_fol=perturbed_fol,
            siv_score=f"{siv_score:.2f}", category_list=cat_list
        )
    elif condition == "shuffled_category":
        shuffled = get_shuffled_categories(actual_categories)
        cat_list = build_category_list(shuffled)
        return prompts["conditions"]["shuffled_category"]["template"].format(
            task_preamble=preamble, nl=nl, perturbed_fol=perturbed_fol,
            siv_score=f"{siv_score:.2f}", category_list=cat_list
        )
    elif condition == "count_only":
        return prompts["conditions"]["count_only"]["template"].format(
            task_preamble=preamble, nl=nl, perturbed_fol=perturbed_fol,
            siv_score=f"{siv_score:.2f}", n_categories=len(actual_categories)
        )
    else:
        raise ValueError(f"Unknown condition: {condition}")


def call_gpt4o(prompt: str) -> Optional[str]:
    from openai import OpenAI
    client = OpenAI()
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=500,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"    API error: {e}")
        return None


def main():
    if not is_vampire_available():
        print("ERROR: Vampire required.")
        sys.exit(1)
    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY required.")
        sys.exit(1)

    random.seed(42)

    print("=" * 70)
    print("PATH 1, STEP 3: Pilot Run")
    print("=" * 70)
    print()

    # Load data
    candidates = load_candidates()
    prompts = load_prompts()

    # Sample 20 candidates
    pilot_candidates = random.sample(candidates, min(20, len(candidates)))
    print(f"Pilot candidates: {len(pilot_candidates)}")

    # Category coverage in pilot
    cat_coverage = Counter()
    for c in pilot_candidates:
        for cat in c["actual_categories"]:
            cat_coverage[cat] += 1
    print(f"Category coverage in pilot: {dict(cat_coverage)}")
    print()

    # First, compute SIV scores for perturbed versions (needed for feedback conditions)
    print("Computing SIV scores for perturbed candidates...")
    for i, cand in enumerate(pilot_candidates):
        siv_sc = get_siv_score(cand["gold_fol"], cand["perturbed_fol"], cand["nl"])
        cand["siv_score"] = siv_sc if siv_sc is not None else 0.0
    mean_siv_pert = sum(c["siv_score"] for c in pilot_candidates) / len(pilot_candidates)
    print(f"  Mean SIV score of perturbed: {mean_siv_pert:.4f}")
    print()

    # Run 5 conditions
    CONDITIONS = ["no_feedback", "score_only", "structured_category", "shuffled_category", "count_only"]
    results = {cond: [] for cond in CONDITIONS}

    print("Running 5 conditions on GPT-4o...")
    t0 = time.time()

    for i, cand in enumerate(pilot_candidates):
        for cond in CONDITIONS:
            prompt = format_prompt(
                cond, cand["nl"], cand["perturbed_fol"],
                cand["siv_score"], cand["actual_categories"], prompts
            )
            correction = call_gpt4o(prompt)

            # Score the correction
            parseable = correction is not None and parse_fol(correction) is not None
            equiv_to_gold = check_equivalence(cand["gold_fol"], correction, timeout=5) if parseable else False
            siv_equiv = False
            if parseable and correction:
                siv_sc = get_siv_score(cand["gold_fol"], correction, cand["nl"])
                siv_equiv = (siv_sc is not None and siv_sc >= 1.0)

            results[cond].append({
                "candidate_id": cand.get("candidate_id", f"C{i:03d}"),
                "correction": correction[:200] if correction else None,
                "parseable": parseable,
                "equiv_to_gold": equiv_to_gold,
                "siv_equiv": siv_equiv,
            })

        if (i + 1) % 5 == 0:
            elapsed = time.time() - t0
            print(f"  {i+1}/{len(pilot_candidates)} candidates ({elapsed:.0f}s)")

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s")
    print()

    # Analyze results
    print("=" * 70)
    print("PILOT RESULTS")
    print("=" * 70)
    print()

    print(f"{'Condition':<25} {'Parseable':>10} {'Equiv(Vamp)':>12} {'Equiv(SIV)':>11}")
    print("-" * 60)

    condition_rates = {}
    for cond in CONDITIONS:
        res = results[cond]
        n = len(res)
        n_parseable = sum(1 for r in res if r["parseable"])
        n_equiv = sum(1 for r in res if r["equiv_to_gold"])
        n_siv = sum(1 for r in res if r["siv_equiv"])
        condition_rates[cond] = {
            "parseable_rate": n_parseable / n,
            "equiv_rate": n_equiv / n,
            "siv_rate": n_siv / n,
            "n": n,
        }
        print(f"{cond:<25} {n_parseable}/{n} ({n_parseable/n:.0%}) "
              f"   {n_equiv}/{n} ({n_equiv/n:.0%})    {n_siv}/{n} ({n_siv/n:.0%})")

    print()

    # Primary comparison: structured vs shuffled
    struct_rate = condition_rates["structured_category"]["siv_rate"]
    shuffled_rate = condition_rates["shuffled_category"]["siv_rate"]
    delta = struct_rate - shuffled_rate

    print(f"PRIMARY COMPARISON (SIV equivalence):")
    print(f"  Structured: {struct_rate:.1%}")
    print(f"  Shuffled:   {shuffled_rate:.1%}")
    print(f"  Δ (structured - shuffled): {delta:+.3f}")
    print()

    # Sanity checks
    print("SANITY CHECKS:")
    nf_rate = condition_rates["no_feedback"]["siv_rate"]
    so_rate = condition_rates["score_only"]["siv_rate"]
    all_parseable = all(condition_rates[c]["parseable_rate"] >= 0.80 for c in CONDITIONS)

    check1 = abs(nf_rate - 0.60) < 0.25  # Within 25pp of baseline
    check2 = so_rate >= nf_rate - 0.05  # Score-only ≥ no-feedback (with margin)
    check3 = all_parseable

    print(f"  1. No-feedback ≈ baseline (60%): {nf_rate:.1%} {'✓' if check1 else '✗'}")
    print(f"  2. Score-only ≥ no-feedback: {so_rate:.1%} vs {nf_rate:.1%} {'✓' if check2 else '✗'}")
    print(f"  3. All conditions ≥80% parseable: {'✓' if check3 else '✗'}")
    sanity_pass = check1 and check2 and check3
    print(f"  Overall: {'PASS' if sanity_pass else 'FAIL'}")
    print()

    # Decision
    if not sanity_pass:
        decision = "SANITY_FAIL"
        decision_text = "Sanity checks failed. Debug pipeline before main run."
    elif delta >= 0.15:
        decision = "STRONG_SIGNAL"
        decision_text = f"Pilot Δ={delta:+.3f} ≥ 0.15. Strong signal. Proceed to main run."
    elif delta >= 0.05:
        decision = "MODERATE_SIGNAL"
        decision_text = f"Pilot Δ={delta:+.3f} in [0.05, 0.15). Moderate. Proceed to main run at full n=80."
    elif delta >= 0:
        decision = "WEAK_SIGNAL"
        decision_text = (
            f"Pilot Δ={delta:+.3f} in [0, 0.05). Weak signal. "
            f"Surface to user: per-aspect channel may not carry signal at category level."
        )
    else:
        decision = "NEGATIVE"
        decision_text = (
            f"Pilot Δ={delta:+.3f} < 0. Structured underperforms shuffled. "
            f"Debug implementation — likely a bug in shuffling or category mapping."
        )

    print(f"DECISION: {decision}")
    print(f"  {decision_text}")
    print()

    # Show example corrections (5 cases)
    print("=" * 70)
    print("EXAMPLE CORRECTIONS (5 cases)")
    print("=" * 70)
    print()

    for i in range(min(5, len(pilot_candidates))):
        cand = pilot_candidates[i]
        print(f"--- Case {i+1}: {cand.get('candidate_id', '')} ---")
        print(f"  NL: {cand['nl'][:80]}")
        print(f"  Gold: {cand['gold_fol'][:80]}")
        print(f"  Perturbed: {cand['perturbed_fol'][:80]}")
        print(f"  Actual categories: {cand['actual_categories']}")
        print(f"  Structured correction: {results['structured_category'][i]['correction'][:80] if results['structured_category'][i]['correction'] else 'None'}")
        print(f"    equiv: {results['structured_category'][i]['siv_equiv']}")
        print(f"  Shuffled correction: {results['shuffled_category'][i]['correction'][:80] if results['shuffled_category'][i]['correction'] else 'None'}")
        print(f"    equiv: {results['shuffled_category'][i]['siv_equiv']}")
        print()

    # Save results
    report = {
        "n_pilot": len(pilot_candidates),
        "condition_rates": condition_rates,
        "primary_comparison": {
            "structured_rate": struct_rate,
            "shuffled_rate": shuffled_rate,
            "delta": round(delta, 4),
        },
        "sanity_checks": {
            "no_feedback_near_baseline": check1,
            "score_only_geq_no_feedback": check2,
            "all_parseable_80pct": check3,
            "overall_pass": sanity_pass,
        },
        "decision": decision,
        "decision_text": decision_text,
        "per_condition_results": {
            cond: res for cond, res in results.items()
        },
    }

    out_path = OUT_DIR / "step3_pilot.json"
    out_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"Report saved to: {out_path}")

    # Markdown
    md_path = OUT_DIR / "step3_pilot.md"
    md_lines = [
        "# Step 3: Pilot Run Results",
        "",
        f"## Setup: {len(pilot_candidates)} candidates × 5 conditions × GPT-4o",
        "",
        "## Results",
        "",
        "| Condition | Parseable | Equiv (Vampire) | Equiv (SIV) |",
        "|-----------|-----------|-----------------|-------------|",
    ]
    for cond in CONDITIONS:
        r = condition_rates[cond]
        md_lines.append(f"| {cond} | {r['parseable_rate']:.0%} | {r['equiv_rate']:.0%} | {r['siv_rate']:.0%} |")
    md_lines.extend([
        "",
        "## Primary Comparison",
        "",
        f"- Structured: {struct_rate:.1%}",
        f"- Shuffled: {shuffled_rate:.1%}",
        f"- **Δ = {delta:+.3f}**",
        "",
        "## Sanity Checks",
        "",
        f"- No-feedback ≈ baseline: {nf_rate:.1%} {'✓' if check1 else '✗'}",
        f"- Score-only ≥ no-feedback: {'✓' if check2 else '✗'}",
        f"- All parseable ≥80%: {'✓' if check3 else '✗'}",
        "",
        "## Decision",
        "",
        f"**{decision}**: {decision_text}",
    ])
    md_path.write_text("\n".join(md_lines))
    print(f"Markdown saved to: {md_path}")


if __name__ == "__main__":
    main()
