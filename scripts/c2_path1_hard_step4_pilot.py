"""
Path 1-Hard, Step 4: Pilot run.

20 candidates × 5 conditions × GPT-4o only × 1 seed.
Tests whether per-aspect category feedback helps at higher difficulty.

Run: python scripts/c2_path1_hard_step4_pilot.py
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
    raise ValueError(f"Unknown condition: {condition}")


def call_gpt4o(prompt: str) -> Optional[str]:
    from openai import OpenAI
    client = OpenAI()
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0, max_tokens=500,
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
    print("PATH 1-HARD, STEP 4: Pilot Run")
    print("=" * 70)
    print()

    candidates = load_candidates()
    prompts = load_prompts()

    # Sample 20
    pilot = random.sample(candidates, min(20, len(candidates)))
    print(f"Pilot candidates: {len(pilot)}")
    cat_coverage = Counter()
    for c in pilot:
        for cat in c["actual_categories"]:
            cat_coverage[cat] += 1
    print(f"Category coverage: {dict(cat_coverage)}")
    print()

    # Compute SIV scores for perturbed
    print("Computing SIV scores for perturbed candidates...")
    for cand in pilot:
        siv = get_siv_score(cand["gold_fol"], cand["perturbed_fol"], cand["nl"])
        cand["siv_score"] = siv if siv is not None else 0.0
    print(f"  Mean perturbed SIV: {sum(c['siv_score'] for c in pilot)/len(pilot):.4f}")
    print()

    # Run 5 conditions
    CONDITIONS = ["no_feedback", "score_only", "structured_category", "shuffled_category", "count_only"]
    results = {cond: [] for cond in CONDITIONS}

    print("Running 5 conditions on GPT-4o...")
    t0 = time.time()

    for i, cand in enumerate(pilot):
        for cond in CONDITIONS:
            prompt = format_prompt(
                cond, cand["nl"], cand["perturbed_fol"],
                cand["siv_score"], cand["actual_categories"], prompts)
            correction = call_gpt4o(prompt)

            parseable = correction is not None and parse_fol(correction) is not None
            equiv = check_equivalence(cand["gold_fol"], correction) if parseable else False
            siv_equiv = False
            if parseable and correction:
                siv_sc = get_siv_score(cand["gold_fol"], correction, cand["nl"])
                siv_equiv = (siv_sc is not None and siv_sc >= 1.0)

            results[cond].append({
                "candidate_id": cand["candidate_id"],
                "correction": correction[:200] if correction else None,
                "parseable": parseable,
                "equiv_to_gold": equiv,
                "siv_equiv": siv_equiv,
            })

        if (i + 1) % 5 == 0:
            elapsed = time.time() - t0
            print(f"  {i+1}/{len(pilot)} ({elapsed:.0f}s)")

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s")
    print()

    # Results
    print("=" * 70)
    print("PILOT RESULTS")
    print("=" * 70)
    print()
    print(f"{'Condition':<25} {'Parse':>7} {'Equiv(V)':>9} {'Equiv(SIV)':>11}")
    print("-" * 55)

    rates = {}
    for cond in CONDITIONS:
        res = results[cond]
        n = len(res)
        n_parse = sum(1 for r in res if r["parseable"])
        n_equiv = sum(1 for r in res if r["equiv_to_gold"])
        n_siv = sum(1 for r in res if r["siv_equiv"])
        rates[cond] = {"parse": n_parse/n, "equiv": n_equiv/n, "siv": n_siv/n, "n": n}
        print(f"{cond:<25} {n_parse}/{n} ({n_parse/n:.0%})  {n_equiv}/{n} ({n_equiv/n:.0%})   {n_siv}/{n} ({n_siv/n:.0%})")

    print()

    # Primary comparison
    struct_rate = rates["structured_category"]["siv"]
    shuffled_rate = rates["shuffled_category"]["siv"]
    delta = struct_rate - shuffled_rate

    print(f"PRIMARY COMPARISON (SIV equivalence):")
    print(f"  Structured: {struct_rate:.1%}")
    print(f"  Shuffled:   {shuffled_rate:.1%}")
    print(f"  Δ (structured - shuffled): {delta:+.3f}")
    print()

    # Sanity checks
    nf_rate = rates["no_feedback"]["siv"]
    so_rate = rates["score_only"]["siv"]
    all_parseable = all(rates[c]["parse"] >= 0.80 for c in CONDITIONS)

    check1 = nf_rate <= 0.40  # Should be near 27% baseline
    check2 = so_rate >= nf_rate - 0.10
    check3 = all_parseable

    print("SANITY CHECKS:")
    print(f"  1. No-feedback ≤40% (baseline ~27%): {nf_rate:.1%} {'✓' if check1 else '✗'}")
    print(f"  2. Score-only ≥ no-feedback (±10pp): {so_rate:.1%} vs {nf_rate:.1%} {'✓' if check2 else '✗'}")
    print(f"  3. All conditions ≥80% parseable: {'✓' if check3 else '✗'}")
    sanity_pass = check1 and check2 and check3
    print(f"  Overall: {'PASS' if sanity_pass else 'FAIL'}")
    print()

    # Decision
    if not sanity_pass:
        decision = "SANITY_FAIL"
        decision_text = "Sanity checks failed. Debug before main run."
    elif delta >= 0.15:
        decision = "STRONG_SIGNAL"
        decision_text = f"Pilot Δ={delta:+.3f} ≥ 0.15. Strong signal! Proceed to main run."
    elif delta >= 0.05:
        decision = "MODERATE_SIGNAL"
        decision_text = f"Pilot Δ={delta:+.3f} in [0.05, 0.15). Moderate. Proceed to main run at full n=60."
    elif delta >= 0:
        decision = "WEAK_SIGNAL"
        decision_text = f"Pilot Δ={delta:+.3f} in [0, 0.05). Weak. Surface to user before main run."
    else:
        decision = "NEGATIVE"
        decision_text = f"Pilot Δ={delta:+.3f} < 0. Debug implementation."

    print(f"DECISION: {decision}")
    print(f"  {decision_text}")
    print()

    # Example corrections
    print("=" * 70)
    print("EXAMPLE CORRECTIONS")
    print("=" * 70)
    print()

    for i in range(min(7, len(pilot))):
        cand = pilot[i]
        s_res = results["structured_category"][i]
        h_res = results["shuffled_category"][i]
        # Focus on cases where structured and shuffled differ
        if s_res["siv_equiv"] != h_res["siv_equiv"] or i < 5:
            marker = " ***DIFFERS***" if s_res["siv_equiv"] != h_res["siv_equiv"] else ""
            print(f"--- Case {i+1}: {cand['candidate_id']}{marker} ---")
            print(f"  NL: {cand['nl'][:100]}")
            print(f"  Gold: {cand['gold_fol'][:100]}")
            print(f"  Perturbed: {cand['perturbed_fol'][:100]}")
            print(f"  Categories: {cand['actual_categories']}")
            print(f"  Structured → equiv={s_res['siv_equiv']}: {s_res['correction'][:100] if s_res['correction'] else 'None'}")
            print(f"  Shuffled   → equiv={h_res['siv_equiv']}: {h_res['correction'][:100] if h_res['correction'] else 'None'}")
            print()

    # Save
    report = {
        "n_pilot": len(pilot),
        "condition_rates": rates,
        "primary_comparison": {
            "structured_rate": struct_rate,
            "shuffled_rate": shuffled_rate,
            "delta": round(delta, 4),
        },
        "sanity_checks": {
            "no_feedback_below_40": check1,
            "score_only_geq_no_feedback": check2,
            "all_parseable": check3,
            "overall": sanity_pass,
        },
        "decision": decision,
        "decision_text": decision_text,
        "per_condition": {cond: res for cond, res in results.items()},
    }

    (OUT_DIR / "step4_pilot.json").write_text(json.dumps(report, indent=2, default=str))

    md_lines = [
        "# Step 4: Pilot Results (Path 1-Hard)",
        "",
        f"## Setup: {len(pilot)} candidates × 5 conditions × GPT-4o",
        "",
        "## Results",
        "",
        "| Condition | Parseable | SIV Equiv |",
        "|-----------|-----------|-----------|",
    ]
    for cond in CONDITIONS:
        r = rates[cond]
        md_lines.append(f"| {cond} | {r['parse']:.0%} | {r['siv']:.0%} |")
    md_lines.extend([
        "",
        "## Primary Comparison",
        "",
        f"- Structured: {struct_rate:.1%}",
        f"- Shuffled: {shuffled_rate:.1%}",
        f"- **Δ = {delta:+.3f}**",
        "",
        f"## Decision: {decision}",
        f"{decision_text}",
    ])
    (OUT_DIR / "step4_pilot.md").write_text("\n".join(md_lines))
    print(f"Saved to: {OUT_DIR / 'step4_pilot.json'}")


if __name__ == "__main__":
    main()
