"""
Path 1, Step 1: Build the candidate pool.

Generates 80 verified compound-2 perturbations with ground-truth category failures.
Each candidate is verified: parseable, non-equivalent, label-changing, and has
category failures derivable from actual SIV probe results.

Run: python scripts/c2_path1_step1.py
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(_REPO_ROOT / ".env")

from datasets import load_dataset
from siv.vampire_interface import prove_strict, check_entailment, vampire_check, is_vampire_available
from siv.fol_utils import parse_fol
from siv.gold_suite_generator import generate_test_suite_from_gold
from siv.fol_parser import parse_gold_fol
from siv.compiler import compile_canonical_fol

OUT_DIR = _REPO_ROOT / "reports" / "c2_investigations" / "path1"
FOLIO_TO_NLI = {"True": "entailment", "False": "contradiction", "Uncertain": "neutral"}

# Category mapping (from Step 0)
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


# ── Perturbation helpers ──────────────────────────────────────────────────────

def perturb_arg_swap(fol: str) -> Optional[str]:
    pattern = r'(\w+)\(([^,()]+),\s*([^,()]+)\)'
    matches = list(re.finditer(pattern, fol))
    if not matches:
        return None
    m = random.choice(matches)
    result = fol[:m.start()] + f"{m.group(1)}({m.group(3)}, {m.group(2)})" + fol[m.end():]
    return result if parse_fol(result) else None


def perturb_negation_flip(fol: str) -> Optional[str]:
    # Try adding negation
    pattern = r'(?<!¬)(\w+\([^)]+\))'
    matches = list(re.finditer(pattern, fol))
    if matches:
        m = random.choice(matches)
        result = fol[:m.start()] + f"¬{m.group(1)}" + fol[m.end():]
        if parse_fol(result):
            return result
    # Try removing negation
    if "¬" in fol:
        pat2 = r'¬(\w+\([^)]+\))'
        match = re.search(pat2, fol)
        if match:
            result = fol[:match.start()] + match.group(1) + fol[match.end():]
            if parse_fol(result):
                return result
    return None


def perturb_quantifier_swap(fol: str) -> Optional[str]:
    if "∀" in fol:
        r = fol.replace("∀", "∃", 1)
        return r if parse_fol(r) else None
    if "∃" in fol:
        r = fol.replace("∃", "∀", 1)
        return r if parse_fol(r) else None
    return None


def perturb_connective_flip(fol: str) -> Optional[str]:
    if "∧" in fol:
        r = fol.replace("∧", "∨", 1)
        return r if parse_fol(r) else None
    if "∨" in fol:
        r = fol.replace("∨", "∧", 1)
        return r if parse_fol(r) else None
    if "→" in fol:
        # Try swapping sides of implication
        idx = fol.find("→")
        before = fol[:idx].strip()
        after = fol[idx+1:].strip()
        # Find the antecedent (last balanced expression before →)
        r = fol.replace("→", "↔", 1)
        return r if parse_fol(r) else None
    return None


def perturb_constant_swap(fol: str) -> Optional[str]:
    keywords = {"all", "exists", "and", "or", "not", "implies"}
    consts = re.findall(r'\b([a-z][a-zA-Z0-9]+)\b', fol)
    consts = [c for c in consts if c not in keywords and len(c) > 1]
    unique = list(set(consts))
    if len(unique) < 2:
        return None
    c1, c2 = random.sample(unique, 2)
    result = fol.replace(c1, "__TMP__").replace(c2, c1).replace("__TMP__", c2)
    return result if result != fol and parse_fol(result) else None


# Map each perturbation function to its expected category
PERTURBATION_FUNCS = [
    ("argument-order", perturb_arg_swap),
    ("polarity", perturb_negation_flip),
    ("quantifier-scope", perturb_quantifier_swap),
    ("connective-polarity", perturb_connective_flip),
    ("argument-order", perturb_constant_swap),  # constant swap is a form of argument-order
]


def make_compound_perturbation(fol: str, n_layers: int = 3) -> Optional[tuple[str, list[str]]]:
    """Apply n_layers different perturbations. Returns (perturbed_fol, [cats])."""
    random.shuffle(PERTURBATION_FUNCS)

    result = fol
    applied_cats = []
    used_funcs = set()

    for _ in range(n_layers):
        candidates_for_layer = [(c, f) for c, f in PERTURBATION_FUNCS
                                if id(f) not in used_funcs]
        random.shuffle(candidates_for_layer)

        applied_this_layer = False
        for cat, func in candidates_for_layer:
            new_result = func(result)
            if new_result and new_result != result:
                result = new_result
                applied_cats.append(cat)
                used_funcs.add(id(func))
                applied_this_layer = True
                break

        if not applied_this_layer:
            break

    if not applied_cats or result == fol:
        return None

    return result, applied_cats


def get_category_failures(gold_fol: str, candidate_fol: str, nl: str) -> Optional[list[str]]:
    """Run SIV probes and determine which categories actually fail.

    Returns list of detected category labels, or None if suite generation fails.
    """
    try:
        result = generate_test_suite_from_gold(
            gold_fol, nl=nl, verify_round_trip=True,
            with_contrastives=True, timeout_s=10,
        )
        if result.error or result.suite is None:
            return None

        suite = result.suite
        detected_categories = set()

        # Check positive probes (content-gap)
        for p in suite.positives:
            ent = check_entailment(candidate_fol, p.fol, timeout=5)
            if ent is not True:  # Failed to entail
                detected_categories.add("content-gap")
                break  # One failure is enough for the category

        # Check contrastive probes
        for c in suite.contrastives:
            v = vampire_check(candidate_fol, c.fol, check="unsat", timeout=5)
            if v != "unsat":  # Consistent when should be inconsistent = error detected
                mk = getattr(c, "mutation_kind", None)
                if mk and mk in MUTATION_TO_CATEGORY:
                    detected_categories.add(MUTATION_TO_CATEGORY[mk])

        return sorted(detected_categories)
    except Exception as e:
        return None


def run_baseline_correction(nl: str, perturbed_fol: str) -> Optional[str]:
    """GPT-4o baseline correction (no feedback)."""
    from openai import OpenAI
    client = OpenAI()
    prompt = f"""You are given a natural language sentence and a first-order logic (FOL) translation that may contain errors. Your task is to produce the correct FOL translation.

Natural language: {nl}

Candidate FOL (may be incorrect): {perturbed_fol}

Provide ONLY the corrected FOL formula. Do not explain."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=500,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return None


def check_equivalence(fol_a: str, fol_b: str, timeout: int = 10) -> bool:
    fwd = check_entailment(fol_a, fol_b, timeout=timeout)
    if fwd is not True:
        return False
    bwd = check_entailment(fol_b, fol_a, timeout=timeout)
    return bwd is True


def main():
    if not is_vampire_available():
        print("ERROR: Vampire required.")
        sys.exit(1)
    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY required.")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    random.seed(42)

    TARGET_N = 80

    print("=" * 70)
    print("PATH 1, STEP 1: Build Candidate Pool")
    print("=" * 70)
    print()

    # Load FOLIO examples
    print("Loading FOLIO train split...")
    ds = load_dataset("tasksource/folio", split="train")
    examples = []
    for row in ds:
        nl_parts = [p.strip() for p in row["premises"].split("\n") if p.strip()]
        fol_parts = [p.strip() for p in row["premises-FOL"].split("\n") if p.strip()]
        if len(nl_parts) != len(fol_parts) or len(nl_parts) < 2:
            continue
        if FOLIO_TO_NLI[row["label"]] == "neutral":
            continue  # Investigation 1: neutral has no LB sentences
        examples.append({
            "story_id": row["story_id"],
            "example_id": row.get("example_id"),
            "nl_sentences": nl_parts,
            "fol_sentences": fol_parts,
            "conclusion": row["conclusion"],
            "conclusion_fol": row["conclusion-FOL"],
            "gold_label": FOLIO_TO_NLI[row["label"]],
        })
    random.shuffle(examples)
    print(f"  Eligible examples (ent+contra, ≥2 sentences): {len(examples)}")
    print()

    # Build candidates (compound-3 per severity decision)
    print(f"Building {TARGET_N} verified compound-3 candidates...")
    print(f"  (compound-3 = 3 layers of perturbation, per severity escalation)")
    candidates = []
    stats = {"checked": 0, "parse_fail": 0, "label_mismatch": 0,
             "perturb_fail": 0, "equiv_to_gold": 0, "no_label_change": 0,
             "no_category_fail": 0, "accepted": 0}
    # Track category coverage to ensure balance
    category_counts = Counter()

    t0 = time.time()
    for ex in examples:
        if len(candidates) >= TARGET_N:
            break

        # Check all FOLs parse
        if not all(parse_fol(f) is not None for f in ex["fol_sentences"]):
            stats["parse_fail"] += 1
            continue
        if parse_fol(ex["conclusion_fol"]) is None:
            stats["parse_fail"] += 1
            continue

        # Verify gold label
        stats["checked"] += 1
        gold_label_check, _ = prove_strict(ex["fol_sentences"], ex["conclusion_fol"], timeout=10)
        if gold_label_check != ex["gold_label"]:
            stats["label_mismatch"] += 1
            continue

        # Try each sentence
        for j in range(len(ex["fol_sentences"])):
            if len(candidates) >= TARGET_N:
                break

            fol = ex["fol_sentences"][j]
            nl = ex["nl_sentences"][j]

            # Compound-3 perturbation
            pert_result = make_compound_perturbation(fol, n_layers=3)
            if not pert_result:
                stats["perturb_fail"] += 1
                continue
            perturbed, expected_cats = pert_result

            # Check non-equivalence
            if check_equivalence(fol, perturbed, timeout=5):
                stats["equiv_to_gold"] += 1
                continue

            # Check label changes (load-bearing verification)
            pert_premises = ex["fol_sentences"][:j] + [perturbed] + ex["fol_sentences"][j+1:]
            pert_label, _ = prove_strict(pert_premises, ex["conclusion_fol"], timeout=10)
            if pert_label == ex["gold_label"]:
                stats["no_label_change"] += 1
                continue

            # Get actual category failures from SIV probes
            actual_cats = get_category_failures(fol, perturbed, nl)
            if not actual_cats:
                stats["no_category_fail"] += 1
                continue

            # Accepted!
            stats["accepted"] += 1
            candidates.append({
                "candidate_id": f"C{stats['accepted']:03d}",
                "story_id": ex["story_id"],
                "example_id": ex.get("example_id"),
                "sentence_idx": j,
                "nl": nl,
                "gold_fol": fol,
                "perturbed_fol": perturbed,
                "gold_label": ex["gold_label"],
                "perturbed_label": pert_label,
                "all_fols": ex["fol_sentences"],
                "conclusion_fol": ex["conclusion_fol"],
                "expected_categories": expected_cats,
                "actual_categories": actual_cats,
            })

            if stats["accepted"] % 10 == 0:
                elapsed = time.time() - t0
                print(f"  Accepted {stats['accepted']}/{TARGET_N} ({elapsed:.0f}s)")

    elapsed = time.time() - t0
    print(f"\n  Done in {elapsed:.1f}s")
    print(f"  Stats: {json.dumps(stats, indent=4)}")
    print(f"  Final pool size: {len(candidates)}")
    print()

    if len(candidates) < TARGET_N:
        print(f"  WARNING: Only got {len(candidates)}/{TARGET_N} candidates.")
        print(f"  Proceeding with available pool.")
        print()

    # Category distribution
    cat_dist = Counter()
    for c in candidates:
        for cat in c["actual_categories"]:
            cat_dist[cat] += 1
    total_cat_instances = sum(cat_dist.values())
    print("Category distribution (across all candidates):")
    for cat in ALL_CATEGORIES:
        count = cat_dist.get(cat, 0)
        pct = count / len(candidates) * 100 if candidates else 0
        print(f"  {cat:<22}: {count:3d} ({pct:.1f}% of candidates)")
    print()

    # Baseline correction
    print("Running baseline GPT-4o corrections (no feedback)...")
    baseline_results = []
    for i, cand in enumerate(candidates):
        correction = run_baseline_correction(cand["nl"], cand["perturbed_fol"])
        if correction:
            is_equiv = check_equivalence(cand["gold_fol"], correction, timeout=5)
        else:
            is_equiv = False
        baseline_results.append(is_equiv)
        cand["baseline_correction_correct"] = is_equiv

        if (i + 1) % 20 == 0:
            n_correct = sum(baseline_results)
            print(f"  {i+1}/{len(candidates)}: {n_correct}/{i+1} correct ({n_correct/(i+1):.1%})")

    n_baseline_correct = sum(baseline_results)
    baseline_rate = n_baseline_correct / len(candidates) if candidates else 0
    print(f"\n  Baseline correction rate: {n_baseline_correct}/{len(candidates)} ({baseline_rate:.1%})")
    print()

    # Decision on baseline rate
    if 0.30 <= baseline_rate <= 0.45:
        severity_decision = "IN_BAND"
        severity_text = f"Baseline rate {baseline_rate:.1%} is in target band (30-45%). Proceed."
    elif 0.45 < baseline_rate <= 0.60:
        severity_decision = "SLIGHTLY_EASY"
        severity_text = f"Baseline rate {baseline_rate:.1%} slightly easy (45-60%). Proceed but expect smaller effects."
    elif baseline_rate > 0.60:
        severity_decision = "TOO_EASY"
        severity_text = f"Baseline rate {baseline_rate:.1%} too easy (>60%). STOP: use compound-3."
    elif 0.20 <= baseline_rate < 0.30:
        severity_decision = "BORDERLINE_HARD"
        severity_text = f"Baseline rate {baseline_rate:.1%} borderline (20-30%). Proceed but flag."
    else:
        severity_decision = "TOO_HARD"
        severity_text = f"Baseline rate {baseline_rate:.1%} too hard (<20%). STOP: reduce to compound-1.5."

    print(f"  Severity decision: {severity_decision}")
    print(f"  {severity_text}")
    print()

    # Save candidates
    candidates_path = OUT_DIR / "path1_candidates.json"
    # Strip all_fols to keep file manageable
    save_candidates = []
    for c in candidates:
        save_c = {k: v for k, v in c.items() if k != "all_fols"}
        save_c["all_fols_hash"] = hash(str(c["all_fols"]))  # For reproducibility check
        save_candidates.append(save_c)

    candidates_path.write_text(json.dumps(save_candidates, indent=2))
    print(f"Candidates saved to: {candidates_path}")

    # Also save full candidates with all_fols for the experiment runner
    full_path = OUT_DIR / "path1_candidates_full.json"
    full_path.write_text(json.dumps(candidates, indent=2))

    # Markdown summary
    md_path = OUT_DIR / "step1_candidate_pool.md"
    md_lines = [
        "# Step 1: Candidate Pool",
        "",
        "## Summary",
        "",
        f"- Target: {TARGET_N} candidates",
        f"- Achieved: {len(candidates)}",
        f"- Examples checked: {stats['checked']}",
        f"- Rejections: parse_fail={stats['parse_fail']}, label_mismatch={stats['label_mismatch']}, "
        f"perturb_fail={stats['perturb_fail']}, equiv={stats['equiv_to_gold']}, "
        f"no_label_change={stats['no_label_change']}, no_cat_fail={stats['no_category_fail']}",
        "",
        "## Category Distribution",
        "",
        "| Category | Count | % of candidates |",
        "|----------|-------|-----------------|",
    ]
    for cat in ALL_CATEGORIES:
        count = cat_dist.get(cat, 0)
        pct = count / len(candidates) * 100 if candidates else 0
        md_lines.append(f"| {cat} | {count} | {pct:.1f}% |")
    md_lines.extend([
        "",
        "## Baseline Correction Rate (GPT-4o, no feedback)",
        "",
        f"**{n_baseline_correct}/{len(candidates)} ({baseline_rate:.1%})**",
        "",
        f"Decision: **{severity_decision}** — {severity_text}",
        "",
        "## Decision Rule (pre-registered)",
        "",
        "- 30-45%: in band, proceed",
        "- 45-60%: slightly easy, proceed with note",
        "- >60%: too easy, STOP",
        "- 20-30%: borderline, proceed with flag",
        "- <20%: too hard, STOP",
    ])
    md_path.write_text("\n".join(md_lines))
    print(f"Summary saved to: {md_path}")


if __name__ == "__main__":
    main()
