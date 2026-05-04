"""
Path 1-Hard, Step 2: Build the candidate pool.

60 verified hard candidates from multi-quantifier FOLIO premises with
compound-3 perturbation and SIV-detected category failures.

Run: python scripts/c2_path1_hard_step2.py
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(_REPO_ROOT / ".env")

from datasets import load_dataset
from siv.vampire_interface import check_entailment, vampire_check, is_vampire_available
from siv.fol_utils import parse_fol
from siv.gold_suite_generator import generate_test_suite_from_gold

OUT_DIR = _REPO_ROOT / "reports" / "c2_investigations" / "path1_hard"
FOLIO_TO_NLI = {"True": "entailment", "False": "contradiction", "Uncertain": "neutral"}

MUTATION_TO_CATEGORY = {
    "negate_atom": "polarity",
    "swap_binary_args": "argument-order",
    "flip_quantifier": "quantifier-scope",
    "drop_restrictor_conjunct": "restrictor-content",
    "flip_connective": "connective-polarity",
    "replace_subformula_with_negation": "polarity",
}

ALL_CATEGORIES = [
    "argument-order", "quantifier-scope", "restrictor-content",
    "polarity", "connective-polarity", "content-gap",
]


# ── Perturbation functions ────────────────────────────────────────────────────

def perturb_arg_swap(fol: str) -> Optional[str]:
    pattern = r'(\w+)\(([^,()]+),\s*([^,()]+)\)'
    matches = list(re.finditer(pattern, fol))
    if not matches:
        return None
    m = random.choice(matches)
    result = fol[:m.start()] + f"{m.group(1)}({m.group(3)}, {m.group(2)})" + fol[m.end():]
    return result if parse_fol(result) else None


def perturb_negation_flip(fol: str) -> Optional[str]:
    pattern = r'(?<!-)(\w+\([^)]+\))'
    matches = list(re.finditer(pattern, fol))
    if matches:
        m = random.choice(matches)
        result = fol[:m.start()] + f"-{m.group(1)}" + fol[m.end():]
        if parse_fol(result):
            return result
    match = re.search(r'-(\w+\([^)]+\))', fol)
    if match:
        result = fol[:match.start()] + match.group(1) + fol[match.end():]
        if parse_fol(result):
            return result
    return None


def perturb_quantifier_swap(fol: str) -> Optional[str]:
    if "all " in fol:
        occurrences = [m.start() for m in re.finditer(r'\ball\b', fol)]
        if occurrences:
            idx = random.choice(occurrences)
            result = fol[:idx] + "exists" + fol[idx+3:]
            return result if parse_fol(result) else None
    if "exists " in fol:
        occurrences = [m.start() for m in re.finditer(r'\bexists\b', fol)]
        if occurrences:
            idx = random.choice(occurrences)
            result = fol[:idx] + "all" + fol[idx+6:]
            return result if parse_fol(result) else None
    return None


def perturb_connective_flip(fol: str) -> Optional[str]:
    if " & " in fol:
        occurrences = [m.start() for m in re.finditer(r' & ', fol)]
        if occurrences:
            idx = random.choice(occurrences)
            result = fol[:idx] + " | " + fol[idx+3:]
            return result if parse_fol(result) else None
    if " | " in fol:
        occurrences = [m.start() for m in re.finditer(r' \| ', fol)]
        if occurrences:
            idx = random.choice(occurrences)
            result = fol[:idx] + " & " + fol[idx+3:]
            return result if parse_fol(result) else None
    if " -> " in fol:
        occurrences = [m.start() for m in re.finditer(r' -> ', fol)]
        if occurrences:
            idx = random.choice(occurrences)
            result = fol[:idx] + " & " + fol[idx+4:]
            return result if parse_fol(result) else None
    return None


def perturb_drop_conjunct(fol: str) -> Optional[str]:
    if " & " not in fol:
        return None
    pattern = r'\w+\([^()]+\) & '
    match = re.search(pattern, fol)
    if match:
        result = fol[:match.start()] + fol[match.end():]
        if parse_fol(result):
            return result
    pattern2 = r' & \w+\([^()]+\)'
    match2 = re.search(pattern2, fol)
    if match2:
        result = fol[:match2.start()] + fol[match2.end():]
        if parse_fol(result):
            return result
    return None


PERTURBATION_FUNCS = [
    ("argument-order", perturb_arg_swap),
    ("polarity", perturb_negation_flip),
    ("quantifier-scope", perturb_quantifier_swap),
    ("connective-polarity", perturb_connective_flip),
    ("restrictor-content", perturb_drop_conjunct),
]


def make_compound_3(fol: str) -> Optional[tuple[str, list[str]]]:
    """Apply 3 different perturbations."""
    funcs = list(PERTURBATION_FUNCS)
    random.shuffle(funcs)
    result = fol
    applied_cats = []
    used = set()

    for cat, func in funcs:
        if len(applied_cats) >= 3:
            break
        if cat in used:
            continue
        new_result = func(result)
        if new_result and new_result != result:
            result = new_result
            applied_cats.append(cat)
            used.add(cat)

    # If only got 2, try one more from any remaining
    if len(applied_cats) < 3:
        for cat, func in funcs:
            if len(applied_cats) >= 3:
                break
            new_result = func(result)
            if new_result and new_result != result:
                result = new_result
                applied_cats.append(cat)
                break

    if len(applied_cats) < 2 or result == fol:
        return None
    return result, applied_cats


def check_equivalence(fol_a: str, fol_b: str, timeout: int = 10) -> bool:
    fwd = check_entailment(fol_a, fol_b, timeout=timeout)
    if fwd is not True:
        return False
    bwd = check_entailment(fol_b, fol_a, timeout=timeout)
    return bwd is True


def get_category_failures(gold_fol: str, candidate_fol: str, nl: str) -> Optional[list[str]]:
    """Run SIV probes and determine detected categories."""
    try:
        result = generate_test_suite_from_gold(
            gold_fol, nl=nl, verify_round_trip=True,
            with_contrastives=True, timeout_s=10,
        )
        if result.error or result.suite is None:
            return None

        suite = result.suite
        detected = set()

        for p in suite.positives:
            ent = check_entailment(candidate_fol, p.fol, timeout=5)
            if ent is not True:
                detected.add("content-gap")
                break

        for c in suite.contrastives:
            v = vampire_check(candidate_fol, c.fol, check="unsat", timeout=5)
            if v != "unsat":
                mk = getattr(c, "mutation_kind", None)
                if mk and mk in MUTATION_TO_CATEGORY:
                    detected.add(MUTATION_TO_CATEGORY[mk])

        return sorted(detected) if detected else None
    except Exception:
        return None


def call_gpt4o_no_feedback(nl: str, perturbed_fol: str) -> Optional[str]:
    from openai import OpenAI
    client = OpenAI()
    prompt = f"""You are given a natural language sentence and a first-order logic (FOL) translation that contains errors. Your task is to produce the correct FOL translation of the natural language sentence.

Natural language: {nl}

Candidate FOL (contains errors): {perturbed_fol}

Provide ONLY the corrected FOL formula. Do not explain."""
    try:
        response = client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": prompt}],
            temperature=0, max_tokens=500,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return None


def main():
    if not is_vampire_available():
        print("ERROR: Vampire required.")
        sys.exit(1)
    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY required.")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    random.seed(42)
    TARGET_N = 60

    print("=" * 70)
    print("PATH 1-HARD, STEP 2: Build Candidate Pool")
    print("=" * 70)
    print()

    # Load multi-quantifier FOLIO premises
    print("Loading multi-quantifier FOLIO premises...")
    ds = load_dataset("tasksource/folio", split="train")
    premises = []
    for row in ds:
        if FOLIO_TO_NLI[row["label"]] == "neutral":
            continue
        nl_parts = [p.strip() for p in row["premises"].split("\n") if p.strip()]
        fol_parts = [p.strip() for p in row["premises-FOL"].split("\n") if p.strip()]
        if len(nl_parts) != len(fol_parts):
            continue
        for nl, fol in zip(nl_parts, fol_parts):
            n_quant = fol.count("∀") + fol.count("∃")
            if "all " in fol:
                n_quant += len(re.findall(r'\ball\b', fol))
            if "exists " in fol:
                n_quant += len(re.findall(r'\bexists\b', fol))
            if n_quant >= 2 and parse_fol(fol) is not None:
                premises.append({"nl": nl, "fol": fol})

    # Deduplicate
    seen = set()
    unique_premises = []
    for p in premises:
        if p["fol"] not in seen:
            seen.add(p["fol"])
            unique_premises.append(p)
    premises = unique_premises
    random.shuffle(premises)
    print(f"  Unique multi-quantifier premises: {len(premises)}")
    print()

    # Build candidates
    print(f"Building {TARGET_N} verified compound-3 candidates...")
    candidates = []
    stats = {"attempted": 0, "perturb_fail": 0, "equiv": 0,
             "no_category": 0, "accepted": 0}
    t0 = time.time()

    for case in premises:
        if len(candidates) >= TARGET_N:
            break
        stats["attempted"] += 1

        pert = make_compound_3(case["fol"])
        if not pert:
            stats["perturb_fail"] += 1
            continue
        perturbed, expected_cats = pert

        # Verify non-equivalence
        if check_equivalence(case["fol"], perturbed):
            stats["equiv"] += 1
            continue

        # Get SIV category failures
        actual_cats = get_category_failures(case["fol"], perturbed, case["nl"])
        if not actual_cats:
            stats["no_category"] += 1
            continue

        stats["accepted"] += 1
        candidates.append({
            "candidate_id": f"H{stats['accepted']:03d}",
            "nl": case["nl"],
            "gold_fol": case["fol"],
            "perturbed_fol": perturbed,
            "expected_categories": expected_cats,
            "actual_categories": actual_cats,
        })

        if stats["accepted"] % 10 == 0:
            elapsed = time.time() - t0
            print(f"  Accepted {stats['accepted']}/{TARGET_N} ({elapsed:.0f}s)")

    elapsed = time.time() - t0
    print(f"\n  Done in {elapsed:.1f}s")
    print(f"  Stats: {json.dumps(stats)}")
    print(f"  Final pool: {len(candidates)}")
    print()

    if len(candidates) < 50:
        print(f"WARNING: Only {len(candidates)} candidates. Below 50 threshold.")

    # Category distribution
    cat_dist = Counter()
    for c in candidates:
        for cat in c["actual_categories"]:
            cat_dist[cat] += 1
    print("Category distribution:")
    for cat in ALL_CATEGORIES:
        count = cat_dist.get(cat, 0)
        pct = count / len(candidates) * 100 if candidates else 0
        print(f"  {cat:<22}: {count:3d} ({pct:.1f}%)")
    print()

    # Baseline correction rate
    print("Running no-feedback baseline on full pool...")
    baseline_correct = 0
    for i, cand in enumerate(candidates):
        correction = call_gpt4o_no_feedback(cand["nl"], cand["perturbed_fol"])
        correct = check_equivalence(cand["gold_fol"], correction) if correction and parse_fol(correction) else False
        cand["baseline_correct"] = correct
        if correct:
            baseline_correct += 1
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(candidates)}: {baseline_correct}/{i+1} ({baseline_correct/(i+1):.1%})")

    baseline_rate = baseline_correct / len(candidates) if candidates else 0
    print(f"\n  Pool baseline: {baseline_correct}/{len(candidates)} ({baseline_rate:.1%})")
    print()

    # Decision
    if 0.10 <= baseline_rate <= 0.30:
        decision = "IN_BAND"
        decision_text = f"Pool baseline {baseline_rate:.1%} in 10-30% band. Proceed."
    elif baseline_rate > 0.30:
        decision = "TOO_EASY"
        decision_text = f"Pool baseline {baseline_rate:.1%} >30%. Need harder perturbations."
    else:
        decision = "TOO_HARD"
        decision_text = f"Pool baseline {baseline_rate:.1%} <10%. Reduce difficulty."

    print(f"Decision: {decision}")
    print(f"  {decision_text}")

    # Save
    out_path = OUT_DIR / "path1_hard_candidates.json"
    out_path.write_text(json.dumps(candidates, indent=2))
    print(f"\nCandidates saved to: {out_path}")

    # Summary markdown
    md_path = OUT_DIR / "step2_candidate_pool.md"
    md_lines = [
        "# Step 2: Candidate Pool (Path 1-Hard)",
        "",
        f"## Pool Size: {len(candidates)}",
        f"## Baseline Correction Rate: {baseline_rate:.1%}",
        f"## Decision: {decision} — {decision_text}",
        "",
        "## Category Distribution",
        "",
        "| Category | Count | % |",
        "|----------|-------|---|",
    ]
    for cat in ALL_CATEGORIES:
        count = cat_dist.get(cat, 0)
        pct = count / len(candidates) * 100 if candidates else 0
        md_lines.append(f"| {cat} | {count} | {pct:.1f}% |")
    md_lines.extend([
        "",
        "## Source",
        "",
        "- Multi-quantifier FOLIO premises (≥2 quantifiers in gold FOL)",
        "- Compound-3 perturbation (3 layers of distinct error patterns)",
        "- Verified: parseable, non-equivalent to gold, SIV-detectable category failures",
    ])
    md_path.write_text("\n".join(md_lines))
    print(f"Summary saved to: {md_path}")


if __name__ == "__main__":
    main()
