"""
C2 Design Investigation 2: Outcome-metric sensitivity to correction quality.

Question: Does the entailment-label outcome respond gradedly to correction quality,
or does it saturate / collapse to binary?

Method: For 15 load-bearing sentences, construct four versions:
1. Gold (original) — should produce correct label
2. Corrupted (meaning-altering perturbation) — should produce wrong label
3. Partial repair — fixes the perturbation but introduces a small error
4. Full repair — logically equivalent to gold, syntactically different

Decision rule:
- Partial repairs correct 50-70%: metric is appropriately graded
- >85%: saturates (too easy)
- <30%: collapses to binary (can't distinguish partial from wrong)

Run: python scripts/c2_investigation_2.py
"""
from __future__ import annotations

import json
import random
import re
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from datasets import load_dataset
from siv.vampire_interface import prove_strict, is_vampire_available, check_entailment
from siv.fol_utils import parse_fol
from siv.gold_suite_generator import generate_test_suite_from_gold
from siv.fol_parser import parse_gold_fol
from siv.compiler import compile_canonical_fol
from siv.scorer import score

OUT_DIR = _REPO_ROOT / "reports" / "c2_investigations"
FOLIO_TO_NLI = {"True": "entailment", "False": "contradiction", "Uncertain": "neutral"}


def load_investigation_1():
    """Load results from investigation 1."""
    path = OUT_DIR / "investigation_1_load_bearing.json"
    return json.loads(path.read_text())


def load_folio_examples():
    """Load ALL FOLIO examples (story_id × conclusion pairs)."""
    ds = load_dataset("tasksource/folio", split="train")
    examples = []
    for row in ds:
        nl_parts = [p.strip() for p in row["premises"].split("\n") if p.strip()]
        fol_parts = [p.strip() for p in row["premises-FOL"].split("\n") if p.strip()]
        if len(nl_parts) != len(fol_parts):
            continue
        if len(nl_parts) < 2:
            continue
        examples.append({
            "story_id": row["story_id"],
            "example_id": row.get("example_id"),
            "nl_sentences": nl_parts,
            "fol_sentences": fol_parts,
            "conclusion": row["conclusion"],
            "conclusion_fol": row["conclusion-FOL"],
            "gold_label": FOLIO_TO_NLI[row["label"]],
        })
    return examples


def check_fol_parseable(fol_list: list, conclusion_fol: str) -> bool:
    """Check all FOLs parse without error."""
    for f in fol_list:
        if parse_fol(f) is None:
            return False
    if parse_fol(conclusion_fol) is None:
        return False
    return True


# ── Perturbation operators ────────────────────────────────────────────────────

def corrupt_arg_swap(fol: str) -> str | None:
    """Swap arguments in a binary predicate."""
    # Find patterns like Pred(a, b) and swap to Pred(b, a)
    pattern = r'(\w+)\(([^,()]+),\s*([^,()]+)\)'
    matches = list(re.finditer(pattern, fol))
    if not matches:
        return None
    # Pick a random match
    m = random.choice(matches)
    swapped = f"{m.group(1)}({m.group(3)}, {m.group(2)})"
    return fol[:m.start()] + swapped + fol[m.end():]


def corrupt_negate_consequent(fol: str) -> str | None:
    """Negate the consequent of a universal-implication formula."""
    # Pattern: ∀x (...→ P) becomes ∀x (...→ ¬P)
    # Find → and negate what's after it
    if "→" in fol:
        idx = fol.rfind("→")
        consequent = fol[idx+1:].strip()
        if consequent.startswith("¬"):
            # Remove negation
            new_cons = consequent[1:].strip()
        else:
            new_cons = f"¬{consequent}"
        return fol[:idx+1] + " " + new_cons
    # Try ->
    if "->" in fol:
        idx = fol.rfind("->")
        consequent = fol[idx+2:].strip()
        if consequent.startswith("-"):
            new_cons = consequent[1:].strip()
            if new_cons.startswith("("):
                new_cons = new_cons  # keep parens
        else:
            new_cons = f"-({consequent})"
        return fol[:idx+2] + " " + new_cons
    return None


def corrupt_drop_conjunct(fol: str) -> str | None:
    """Drop a conjunct from a conjunction."""
    # Simple: find ∧ or & and remove left or right operand
    if "∧" in fol:
        parts = fol.split("∧", 1)
        if len(parts) == 2:
            return parts[1].strip()
    if " & " in fol:
        idx = fol.find(" & ")
        # Return just the right side
        return fol[idx+3:].strip()
    return None


def corrupt_flip_quantifier(fol: str) -> str | None:
    """Flip ∀ to ∃ or vice versa."""
    if "∀" in fol:
        return fol.replace("∀", "∃", 1)
    if "∃" in fol:
        return fol.replace("∃", "∀", 1)
    if fol.strip().startswith("all "):
        return "exists " + fol.strip()[4:]
    if fol.strip().startswith("exists "):
        return "all " + fol.strip()[7:]
    return None


CORRUPTION_OPS = [
    ("arg_swap", corrupt_arg_swap),
    ("negate_consequent", corrupt_negate_consequent),
    ("drop_conjunct", corrupt_drop_conjunct),
    ("flip_quantifier", corrupt_flip_quantifier),
]


def try_corrupt(fol: str) -> tuple[str, str] | None:
    """Try corruption operators until one works and produces a parseable result."""
    random.shuffle(CORRUPTION_OPS)
    for name, op in CORRUPTION_OPS:
        result = op(fol)
        if result and parse_fol(result) is not None:
            return name, result
    return None


def make_partial_repair(gold_fol: str, corrupted_fol: str, corruption_type: str) -> str | None:
    """Create a partial repair: fixes the main error but introduces a minor one.

    Strategy: take the gold FOL and make a SMALL modification that doesn't
    completely break it but introduces an inaccuracy. This should be different
    from the corruption.
    """
    # Approach: take gold and apply a mild perturbation
    # The key is it should be CLOSER to gold than the corruption but not identical

    # Strategy 1: If gold has a binary predicate, rename it slightly (keeps structure)
    pattern = r'(\w+)\(([^()]+)\)'
    matches = list(re.finditer(pattern, gold_fol))

    if matches and len(matches) > 1:
        # Drop the LAST predicate application (minor omission)
        m = matches[-1]
        # Replace last predicate with a tautology-like filler
        # Actually, let's add a spurious negation to ONE atom
        m = random.choice(matches)
        atom = m.group(0)
        if f"¬{atom}" in gold_fol or f"-{atom}" in gold_fol:
            # Already negated; un-negate it
            partial = gold_fol.replace(f"¬{atom}", atom, 1)
            if partial != gold_fol and parse_fol(partial) is not None:
                return partial
        else:
            # Add negation to this atom
            partial = gold_fol.replace(atom, f"¬{atom}", 1)
            if partial != gold_fol and parse_fol(partial) is not None:
                return partial

    # Strategy 2: Swap two constants if present
    consts = re.findall(r'\b([a-z][a-zA-Z0-9]*)\b', gold_fol)
    # Filter to likely constants (not quantifier variables)
    consts = [c for c in consts if len(c) > 1 and c not in ('all', 'exists')]
    if len(set(consts)) >= 2:
        unique = list(set(consts))
        c1, c2 = unique[0], unique[1]
        partial = gold_fol.replace(c1, "__TMP__").replace(c2, c1).replace("__TMP__", c2)
        if partial != gold_fol and parse_fol(partial) is not None:
            return partial

    # Strategy 3: If universal, flip to existential (changes meaning mildly)
    result = corrupt_flip_quantifier(gold_fol)
    if result and result != corrupted_fol and parse_fol(result) is not None:
        return result

    return None


def make_full_repair(gold_fol: str) -> str | None:
    """Create a logically equivalent but syntactically different version of gold.

    Strategies: rename variables, reorder conjuncts, double-negate.
    """
    # Strategy 1: Rename all bound variables
    # x -> y, y -> z, etc.
    result = gold_fol
    # Simple variable renaming
    if "x" in result and "z" not in result:
        result = result.replace("x", "z")
        if parse_fol(result) is not None:
            return result

    # Strategy 2: Double negate the whole thing
    result = f"-(-(({gold_fol})))"
    if parse_fol(result) is not None:
        return result

    # Strategy 3: A ∧ B → B ∧ A (reorder)
    if "∧" in gold_fol:
        parts = gold_fol.split("∧", 1)
        if len(parts) == 2:
            result = f"{parts[1].strip()} ∧ {parts[0].strip()}"
            if parse_fol(result) is not None:
                return result

    # Fallback: just use gold (variable rename with different pattern)
    result = gold_fol
    for old, new in [("x", "w"), ("y", "v"), ("z", "u")]:
        if old in result:
            result = result.replace(old, new)
            if result != gold_fol and parse_fol(result) is not None:
                return result
            result = gold_fol  # Reset and try next

    return None


def get_siv_score(fol: str, gold_fol: str, nl: str) -> float | None:
    """Score a FOL against v2 gold-derived suite. Returns recall."""
    try:
        result = generate_test_suite_from_gold(
            gold_fol, nl=nl, verify_round_trip=True,
            with_contrastives=True, timeout_s=10,
        )
        if result.error or result.suite is None:
            return None
        report = score(result.suite, fol, timeout_s=10)
        return report.recall if report else None
    except Exception:
        return None


def main():
    if not is_vampire_available():
        print("ERROR: Vampire required.")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    random.seed(42)

    print("=" * 70)
    print("INVESTIGATION 2: Outcome-metric sensitivity to correction quality")
    print("=" * 70)
    print()

    # Load FOLIO examples and find load-bearing sentences directly
    # (Investigation 1 didn't store conclusion_fol per story, so we recompute)
    print("Loading FOLIO examples and finding load-bearing sentences...")
    all_examples = load_folio_examples()

    # Filter to entailment/contradiction only (neutral has no LB sentences)
    candidates = [e for e in all_examples if e["gold_label"] in ("entailment", "contradiction")]
    random.shuffle(candidates)

    # Find load-bearing sentences (verify gold label, then test removal)
    lb_cases = []
    checked = 0
    for ex in candidates:
        if len(lb_cases) >= 40:  # Enough to select 15
            break
        if not check_fol_parseable(ex["fol_sentences"], ex["conclusion_fol"]):
            continue

        # Verify gold produces correct label
        gold_label_check, _ = prove_strict(ex["fol_sentences"], ex["conclusion_fol"], timeout=10)
        checked += 1
        if gold_label_check != ex["gold_label"]:
            continue

        # Find load-bearing sentences in this example
        for j in range(len(ex["fol_sentences"])):
            reduced = ex["fol_sentences"][:j] + ex["fol_sentences"][j+1:]
            reduced_label, _ = prove_strict(reduced, ex["conclusion_fol"], timeout=10)
            if reduced_label != ex["gold_label"]:
                lb_cases.append({
                    "story_id": ex["story_id"],
                    "gold_label": ex["gold_label"],
                    "sentence_idx": j,
                    "nl": ex["nl_sentences"][j],
                    "fol": ex["fol_sentences"][j],
                    "all_fols": ex["fol_sentences"],
                    "conclusion_fol": ex["conclusion_fol"],
                })

        if checked % 20 == 0:
            print(f"  Checked {checked} examples, found {len(lb_cases)} LB sentences...")

    print(f"  Checked {checked} examples total")
    print(f"Load-bearing sentences available: {len(lb_cases)}")

    # Sample 15 diverse cases
    random.shuffle(lb_cases)
    # Try to get mix of labels and perturbation compatibility
    selected = []
    for case in lb_cases:
        if len(selected) >= 15:
            break
        # Check we can corrupt it
        corruption = try_corrupt(case["fol"])
        if corruption is None:
            continue
        case["corruption_type"], case["corrupted_fol"] = corruption
        selected.append(case)

    print(f"Selected {len(selected)} cases for testing")
    if len(selected) < 10:
        print("ERROR: Need minimum 10 cases. Insufficient data.")
        sys.exit(1)
    print()

    # Process each case
    results = []
    t0 = time.time()

    for i, case in enumerate(selected):
        gold_fol = case["fol"]
        corrupted_fol = case["corrupted_fol"]
        corruption_type = case["corruption_type"]
        all_fols = case["all_fols"]
        sent_idx = case["sentence_idx"]
        conclusion_fol = case["conclusion_fol"]
        gold_label = case["gold_label"]

        # Build premise variants
        def make_premise_set(target_fol):
            return all_fols[:sent_idx] + [target_fol] + all_fols[sent_idx+1:]

        # 1. Gold (sanity check)
        gold_premises = make_premise_set(gold_fol)
        gold_vampire_label, _ = prove_strict(gold_premises, conclusion_fol, timeout=10)

        # 2. Corrupted
        corrupted_premises = make_premise_set(corrupted_fol)
        corrupted_vampire_label, _ = prove_strict(corrupted_premises, conclusion_fol, timeout=10)

        # 3. Partial repair
        partial_fol = make_partial_repair(gold_fol, corrupted_fol, corruption_type)
        partial_vampire_label = None
        if partial_fol:
            partial_premises = make_premise_set(partial_fol)
            partial_vampire_label, _ = prove_strict(partial_premises, conclusion_fol, timeout=10)

        # 4. Full repair
        full_repair_fol = make_full_repair(gold_fol)
        full_repair_vampire_label = None
        if full_repair_fol:
            full_repair_premises = make_premise_set(full_repair_fol)
            full_repair_vampire_label, _ = prove_strict(full_repair_premises, conclusion_fol, timeout=10)

        # SIV scores (secondary outcome)
        siv_gold = get_siv_score(gold_fol, gold_fol, case["nl"])
        siv_corrupted = get_siv_score(corrupted_fol, gold_fol, case["nl"])
        siv_partial = get_siv_score(partial_fol, gold_fol, case["nl"]) if partial_fol else None
        siv_full = get_siv_score(full_repair_fol, gold_fol, case["nl"]) if full_repair_fol else None

        result = {
            "story_id": case["story_id"],
            "sentence_idx": sent_idx,
            "nl": case["nl"],
            "gold_fol": gold_fol,
            "corrupted_fol": corrupted_fol,
            "corruption_type": corruption_type,
            "partial_repair_fol": partial_fol,
            "full_repair_fol": full_repair_fol,
            "gold_label": gold_label,
            "gold_produces_correct": gold_vampire_label == gold_label,
            "corrupted_produces_correct": corrupted_vampire_label == gold_label,
            "partial_produces_correct": partial_vampire_label == gold_label if partial_vampire_label else None,
            "full_repair_produces_correct": full_repair_vampire_label == gold_label if full_repair_vampire_label else None,
            "vampire_labels": {
                "gold": gold_vampire_label,
                "corrupted": corrupted_vampire_label,
                "partial": partial_vampire_label,
                "full_repair": full_repair_vampire_label,
            },
            "siv_scores": {
                "gold": siv_gold,
                "corrupted": siv_corrupted,
                "partial": siv_partial,
                "full_repair": siv_full,
            },
        }
        results.append(result)

        if (i + 1) % 5 == 0:
            print(f"  Processed {i+1}/{len(selected)}...")

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s")
    print()

    # Analyze results
    n = len(results)

    # Sanity: gold should produce correct label
    gold_correct = sum(1 for r in results if r["gold_produces_correct"])
    print(f"Sanity check — Gold produces correct label: {gold_correct}/{n} ({gold_correct/n:.1%})")

    # Full repair should produce correct label
    full_repair_results = [r for r in results if r["full_repair_produces_correct"] is not None]
    full_correct = sum(1 for r in full_repair_results if r["full_repair_produces_correct"])
    n_full = len(full_repair_results)
    print(f"Full repair produces correct label: {full_correct}/{n_full} ({full_correct/n_full:.1%} if n_full > 0 else 'N/A')")

    # Corrupted should produce WRONG label
    corrupted_wrong = sum(1 for r in results if not r["corrupted_produces_correct"])
    print(f"Corrupted produces wrong label: {corrupted_wrong}/{n} ({corrupted_wrong/n:.1%})")

    # KEY METRIC: Partial repair rate
    partial_results = [r for r in results if r["partial_produces_correct"] is not None]
    partial_correct = sum(1 for r in partial_results if r["partial_produces_correct"])
    n_partial = len(partial_results)
    partial_rate = partial_correct / n_partial if n_partial > 0 else 0

    print(f"\n*** Partial repair produces correct label: {partial_correct}/{n_partial} ({partial_rate:.1%}) ***")
    print()

    # SIV score analysis
    siv_results = [r for r in results if all(
        r["siv_scores"][k] is not None for k in ["gold", "corrupted"]
    )]
    if siv_results:
        print("SIV score means:")
        for version in ["gold", "corrupted", "partial", "full_repair"]:
            scores = [r["siv_scores"][version] for r in results if r["siv_scores"][version] is not None]
            if scores:
                mean = sum(scores) / len(scores)
                print(f"  {version}: {mean:.4f} (n={len(scores)})")
    print()

    # Decision
    if 0.50 <= partial_rate <= 0.70:
        decision = "GRADED"
        decision_text = (
            f"Outcome metric is appropriately graded. Partial repairs produce correct "
            f"labels in {partial_rate:.1%} of cases (target: 50-70%). "
            f"Bridge 2 with entailment-label as primary outcome works."
        )
    elif partial_rate > 0.85:
        decision = "SATURATES"
        decision_text = (
            f"Outcome saturates. Partial repairs produce correct labels in {partial_rate:.1%} "
            f"(>85%). A partially-correct correction still gets credit. "
            f"Use SIV-equivalence as primary outcome or narrow load-bearing definition."
        )
    elif partial_rate < 0.30:
        decision = "BINARY_COLLAPSE"
        decision_text = (
            f"Outcome collapses to binary. Partial repairs only {partial_rate:.1%} correct "
            f"(<30%). Only essentially-equivalent corrections produce right label. "
            f"Use SIV-equivalence as primary outcome."
        )
    else:
        # Gray zone 30-50% or 70-85%
        decision = "GRAY_ZONE"
        decision_text = (
            f"Partial repair rate {partial_rate:.1%} is in the gray zone. "
            f"Need to examine whether SIV score agrees in direction with label-match."
        )

    print(f"DECISION: {decision}")
    print(f"  {decision_text}")
    print()

    # Check agreement between SIV and label outcomes
    agree_count = 0
    disagree_count = 0
    for r in results:
        if r["partial_produces_correct"] is not None and r["siv_scores"]["partial"] is not None:
            label_says_good = r["partial_produces_correct"]
            siv_says_good = r["siv_scores"]["partial"] > 0.5  # Threshold for "good"
            if label_says_good == siv_says_good:
                agree_count += 1
            else:
                disagree_count += 1

    if agree_count + disagree_count > 0:
        agreement_rate = agree_count / (agree_count + disagree_count)
        print(f"SIV-label agreement rate: {agreement_rate:.1%} ({agree_count}/{agree_count + disagree_count})")

    # Save report
    report = {
        "n_cases": n,
        "gold_correct_rate": gold_correct / n,
        "corrupted_wrong_rate": corrupted_wrong / n,
        "partial_correct_rate": partial_rate,
        "partial_n": n_partial,
        "full_repair_correct_rate": full_correct / n_full if n_full > 0 else None,
        "full_repair_n": n_full,
        "decision": decision,
        "decision_text": decision_text,
        "per_case": results,
    }

    out_path = OUT_DIR / "investigation_2_metric_sensitivity.json"
    out_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nReport saved to: {out_path}")

    # Markdown
    md_path = OUT_DIR / "investigation_2_metric_sensitivity.md"
    md_lines = [
        "# Investigation 2: Outcome-metric Sensitivity to Correction Quality",
        "",
        "## Summary",
        "",
        f"- Cases tested: {n}",
        f"- Gold produces correct label: {gold_correct}/{n} ({gold_correct/n:.1%})",
        f"- Corrupted produces wrong label: {corrupted_wrong}/{n} ({corrupted_wrong/n:.1%})",
        f"- **Partial repair produces correct label: {partial_correct}/{n_partial} ({partial_rate:.1%})**",
        f"- Full repair produces correct label: {full_correct}/{n_full} ({full_correct/n_full:.1%} if applicable)",
        "",
        "## Decision",
        "",
        f"**{decision}**: {decision_text}",
        "",
        "## Per-case Detail",
        "",
        "| # | Story | Label | Corruption | Gold✓ | Corrupt✓ | Partial✓ | Full✓ | SIV-gold | SIV-corrupt | SIV-partial |",
        "|---|-------|-------|-----------|-------|----------|----------|-------|----------|-------------|-------------|",
    ]
    for i, r in enumerate(results):
        sg = f"{r['siv_scores']['gold']:.3f}" if r['siv_scores']['gold'] is not None else "N/A"
        sc = f"{r['siv_scores']['corrupted']:.3f}" if r['siv_scores']['corrupted'] is not None else "N/A"
        sp = f"{r['siv_scores']['partial']:.3f}" if r['siv_scores']['partial'] is not None else "N/A"
        md_lines.append(
            f"| {i+1} | {r['story_id']} | {r['gold_label']} | {r['corruption_type']} | "
            f"{'✓' if r['gold_produces_correct'] else '✗'} | "
            f"{'✓' if r['corrupted_produces_correct'] else '✗'} | "
            f"{'✓' if r['partial_produces_correct'] else ('✗' if r['partial_produces_correct'] is False else '?')} | "
            f"{'✓' if r['full_repair_produces_correct'] else ('✗' if r['full_repair_produces_correct'] is False else '?')} | "
            f"{sg} | {sc} | {sp} |"
        )
    md_lines.extend([
        "",
        "## Decision Rule (pre-registered)",
        "",
        "- 50-70% partial correct → metric is graded, use entailment-label as primary",
        "- >85% → saturates, use SIV-equivalence as primary",
        "- <30% → collapses to binary, use SIV-equivalence as primary",
    ])
    md_path.write_text("\n".join(md_lines))
    print(f"Markdown saved to: {md_path}")


if __name__ == "__main__":
    main()
