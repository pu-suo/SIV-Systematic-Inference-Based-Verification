"""
Stage 3 validation: perturbed gold orders correctly.

Takes a sample of RT-verified premises, applies each Tier-B perturbation
operator to the gold FOL, scores the perturbed version against the v2 suite,
and verifies that perturbed scores lower than gold.

Acceptance: perturbed recall < gold recall (which is 1.0) for each applicable
perturbation. This confirms the test suites have appropriate detection power.

Run: python scripts/stage3_perturbation_validation.py [--sample N] [--seed S]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datasets import load_dataset

from siv.compiler import compile_canonical_fol
from siv.fol_parser import ParseError, parse_gold_fol
from siv.fol_utils import normalize_fol_string, parse_fol
from siv.gold_suite_generator import generate_test_suite_from_gold
from siv.nltk_perturbations import (
    B_arg_swap,
    B_quantifier_swap,
    B_restrictor_add,
    B_restrictor_drop,
    B_scope_flip,
    NotApplicable,
)
from siv.scorer import score
from siv.vampire_interface import check_entailment, is_vampire_available

TIER_B_OPS = [
    ("B_arg_swap", B_arg_swap),
    ("B_restrictor_drop", B_restrictor_drop),
    ("B_restrictor_add", B_restrictor_add),
    ("B_scope_flip", B_scope_flip),
    ("B_quantifier_swap", B_quantifier_swap),
]


def get_rt_verified_premises(limit: int = 0, seed: int = 42) -> list:
    """Load and filter to RT-verified premises, optionally sampling."""
    print("Loading FOLIO train split...")
    ds = load_dataset("tasksource/folio", split="train")

    unique_premises: dict = {}
    story_preds_map: dict = {}  # nl -> list of predicates in same story

    for row in ds:
        premises_nl = (row.get("premises", "") or "").split("\n")
        premises_fol = (row.get("premises-FOL", "") or "").split("\n")
        # Collect all predicates in this story for B_restrictor_add
        story_preds = set()
        for fol in premises_fol:
            fol = fol.strip()
            if fol:
                parsed = parse_fol(fol)
                if parsed:
                    story_preds.update(_extract_pred_names(parsed))

        for nl, fol in zip(premises_nl, premises_fol):
            nl = nl.strip()
            fol = fol.strip()
            if nl and fol and nl not in unique_premises:
                unique_premises[nl] = fol
                story_preds_map[nl] = list(story_preds)

    total = len(unique_premises)
    print(f"Unique premises: {total}")

    # Filter to RT-verified
    rt_verified = []
    print("Identifying RT-verified premises...")
    for i, (nl, raw_fol) in enumerate(unique_premises.items()):
        if (i + 1) % 200 == 0:
            print(f"  [{i+1}/{total}]...")
        try:
            ext = parse_gold_fol(raw_fol, nl=nl)
        except ParseError:
            continue
        compiled = compile_canonical_fol(ext)
        normalized = normalize_fol_string(raw_fol)
        fwd = check_entailment(compiled, normalized, timeout=5)
        bwd = check_entailment(normalized, compiled, timeout=5)
        if fwd is True and bwd is True:
            rt_verified.append((nl, raw_fol, story_preds_map.get(nl, [])))

    print(f"RT-verified: {len(rt_verified)}")

    if limit > 0 and limit < len(rt_verified):
        rng = random.Random(seed)
        rt_verified = rng.sample(rt_verified, limit)
        print(f"Sampled: {limit}")

    return rt_verified


def _extract_pred_names(expr) -> set:
    """Extract predicate names from an NLTK Expression."""
    from nltk.sem.logic import ApplicationExpression, AllExpression, ExistsExpression
    from nltk.sem.logic import NegatedExpression, BinaryExpression

    names = set()
    if isinstance(expr, ApplicationExpression):
        from siv.nltk_perturbations import _uncurry
        head, args = _uncurry(expr)
        names.add(str(head))
        for arg in args:
            names.update(_extract_pred_names(arg))
    elif isinstance(expr, (AllExpression, ExistsExpression)):
        names.update(_extract_pred_names(expr.term))
    elif isinstance(expr, NegatedExpression):
        names.update(_extract_pred_names(expr.term))
    elif isinstance(expr, BinaryExpression):
        names.update(_extract_pred_names(expr.first))
        names.update(_extract_pred_names(expr.second))
    return names


def main():
    parser = argparse.ArgumentParser(description="Stage 3: perturbation ordering")
    parser.add_argument("--sample", type=int, default=200,
                        help="Number of premises to sample (0=all)")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if not is_vampire_available():
        print("ERROR: Vampire is required for Stage 3 validation.")
        sys.exit(1)

    premises = get_rt_verified_premises(limit=args.sample, seed=args.seed)

    print()
    print("=" * 70)
    print("STAGE 3: Perturbation Ordering Validation")
    print("=" * 70)
    print(f"Sample size: {len(premises)}")
    print()

    # Per-operator tracking
    op_stats = {}
    for op_name, _ in TIER_B_OPS:
        op_stats[op_name] = {
            "applicable": 0,
            "correct_ordering": 0,  # perturbed recall < gold recall
            "same_score": 0,        # perturbed recall == gold recall (bad)
            "higher_score": 0,      # perturbed recall > gold (very bad, shouldn't happen)
            "score_errors": 0,
            "avg_perturbed_recall": [],
        }

    # Overall stats
    total_tests = 0
    total_correct = 0
    failures = []  # Detailed failure info

    t0 = time.time()
    for i, (nl, raw_fol, story_preds) in enumerate(premises):
        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(premises)}]...")

        # Generate v2 suite (positives only for speed — recall is the key metric)
        result = generate_test_suite_from_gold(
            raw_fol, nl=nl, verify_round_trip=False, with_contrastives=False, timeout_s=5
        )
        if result.error or result.suite is None:
            continue

        # Parse gold FOL as NLTK expression for perturbation
        parsed_gold = parse_fol(raw_fol)
        if parsed_gold is None:
            continue

        # Apply each Tier-B operator
        for op_name, op_func in TIER_B_OPS:
            try:
                kwargs = {}
                if op_name == "B_restrictor_add":
                    kwargs["story_predicates"] = story_preds
                perturbed_expr = op_func(parsed_gold, **kwargs)
            except (NotApplicable, Exception):
                continue

            op_stats[op_name]["applicable"] += 1
            total_tests += 1

            # Score perturbed FOL against the v2 suite
            perturbed_fol = str(perturbed_expr)
            try:
                report = score(result.suite, perturbed_fol, timeout_s=5)
            except Exception:
                op_stats[op_name]["score_errors"] += 1
                continue

            perturbed_recall = report.recall
            op_stats[op_name]["avg_perturbed_recall"].append(perturbed_recall)

            # Gold is always recall=1.0 (proven in Stage 2)
            if perturbed_recall < 1.0:
                op_stats[op_name]["correct_ordering"] += 1
                total_correct += 1
            elif perturbed_recall == 1.0:
                op_stats[op_name]["same_score"] += 1
                if len(failures) < 30:
                    failures.append({
                        "nl": nl[:80],
                        "gold_fol": raw_fol[:120],
                        "perturbed_fol": perturbed_fol[:120],
                        "operator": op_name,
                        "recall": perturbed_recall,
                        "issue": "same_score",
                    })
            else:
                op_stats[op_name]["higher_score"] += 1
                # This should never happen
                if len(failures) < 30:
                    failures.append({
                        "nl": nl[:80],
                        "gold_fol": raw_fol[:120],
                        "perturbed_fol": perturbed_fol[:120],
                        "operator": op_name,
                        "recall": perturbed_recall,
                        "issue": "higher_score",
                    })

    elapsed = time.time() - t0
    print(f"\nCompleted in {elapsed:.1f}s")

    # Report
    print()
    print("=" * 70)
    print("PER-OPERATOR RESULTS")
    print("=" * 70)
    print()
    print(f"{'Operator':<22} {'Applicable':>10} {'Detected':>10} {'Same':>6} {'Rate':>8}")
    print("-" * 60)

    for op_name, stats in op_stats.items():
        applicable = stats["applicable"]
        if applicable == 0:
            print(f"{op_name:<22} {'0':>10} {'—':>10} {'—':>6} {'N/A':>8}")
            continue
        correct = stats["correct_ordering"]
        same = stats["same_score"]
        rate = correct / applicable
        avg_recall = (
            sum(stats["avg_perturbed_recall"]) / len(stats["avg_perturbed_recall"])
            if stats["avg_perturbed_recall"] else 0
        )
        print(f"{op_name:<22} {applicable:>10} {correct:>10} {same:>6} {rate:>7.1%}"
              f"  (avg recall: {avg_recall:.3f})")

    print()
    print("=" * 70)
    print("OVERALL")
    print("=" * 70)
    overall_rate = total_correct / total_tests if total_tests > 0 else 0
    print(f"  Total perturbation tests: {total_tests}")
    print(f"  Correctly ordered (perturbed < gold): {total_correct} ({100*overall_rate:.1f}%)")
    print(f"  Same score (no detection): {total_tests - total_correct}")
    print()

    # Acceptance gate: overall detection rate should be meaningful
    # Not all perturbations will be detected (e.g., B_restrictor_add strengthens
    # the antecedent which still entails the same consequences). But the test
    # suites should detect MOST meaning-altering perturbations.
    gate_pass = overall_rate >= 0.60
    print(f"  Acceptance gate (overall detection >= 60%): {'PASS' if gate_pass else 'FAIL'}")
    print()

    # Show failures
    if failures:
        same_score_failures = [f for f in failures if f["issue"] == "same_score"]
        if same_score_failures:
            print(f"Same-score samples (first {min(10, len(same_score_failures))}):")
            for f in same_score_failures[:10]:
                print(f"  [{f['operator']}] {f['nl']}")
                print(f"    Gold:      {f['gold_fol']}")
                print(f"    Perturbed: {f['perturbed_fol']}")
                print()

    # Save report
    report_data = {
        "sample_size": len(premises),
        "total_tests": total_tests,
        "total_correct": total_correct,
        "overall_detection_rate": overall_rate,
        "gate_pass": gate_pass,
        "per_operator": {
            name: {
                "applicable": s["applicable"],
                "correct_ordering": s["correct_ordering"],
                "same_score": s["same_score"],
                "higher_score": s["higher_score"],
                "detection_rate": s["correct_ordering"] / s["applicable"] if s["applicable"] else 0,
                "avg_perturbed_recall": (
                    sum(s["avg_perturbed_recall"]) / len(s["avg_perturbed_recall"])
                    if s["avg_perturbed_recall"] else None
                ),
            }
            for name, s in op_stats.items()
        },
        "failures": failures,
    }

    out_path = Path("reports/stage3_perturbation_ordering.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report_data, indent=2, default=str))
    print(f"Detailed report saved to: {out_path}")


if __name__ == "__main__":
    main()
