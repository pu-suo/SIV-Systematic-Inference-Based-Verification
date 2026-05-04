"""
Stage 2 validation: gold-derived test suite acceptance gates.

Three gates:
  1. Hand-picked premises (20) → generate v2 suites, inspect structure
  2. Full corpus (all RT-verified) → generate v2 suites, confirm schema invariants
  3. Gold self-score → gold FOL scores recall=1.0 on its own suite (≥95% of corpus)

Run: python scripts/stage2_validation.py [--gate 1|2|3|all] [--fast]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datasets import load_dataset

from siv.compiler import compile_canonical_fol
from siv.fol_parser import ParseError, parse_gold_fol
from siv.fol_utils import normalize_fol_string
from siv.gold_suite_generator import GoldSuiteResult, generate_test_suite_from_gold
from siv.scorer import score
from siv.vampire_interface import check_entailment, is_vampire_available


# ── Hand-picked premises spanning categories ─────────────────────────────────

HAND_PICKED = [
    # Category 1: Universal + implication
    ("All cats are animals.", "all x.(Cat(x) -> Animal(x))"),
    ("All tall students are athletes.", "all x.((Tall(x) & Student(x)) -> Athlete(x))"),
    ("Everything that flies has wings.", "all x.(Fly(x) -> HasWings(x))"),
    # Category 2: Ground instances
    ("John is tall.", "Tall(john)"),
    ("Mary likes coffee and tea.", "(Likes(mary, coffee) & Likes(mary, tea))"),
    ("It is not the case that Bob is happy.", "-Happy(bob)"),
    ("If John is smart then John is successful.", "(Smart(john) -> Successful(john))"),
    # Category 3: Existentials
    ("There is a dog that barks.", "exists x.(Dog(x) & Barks(x))"),
    ("Some student passed the exam.", "exists x.(Student(x) & Passed(x, exam))"),
    # Category 4: Nested universals
    ("Everyone likes everyone who is kind.", "all x.(all y.(Kind(y) -> Likes(x, y)))"),
    # Category 5: Inner quantification
    ("Everyone who has a pet is happy.", "all x.(exists y.(Has(x, y) & Pet(y)) -> Happy(x))"),
    # Category 7: Universal without implication
    ("Everything is either red or blue.", "all x.(Red(x) | Blue(x))"),
    ("All objects are visible and solid.", "all x.(Visible(x) & Solid(x))"),
    # Category 8: Equality
    ("John is Mary.", "(john = mary)"),
    # Arity > 2
    ("John gave Mary a book.", "Gave(john, mary, book)"),
    ("All teachers give students grades.", "all x.(Teacher(x) -> Gives(x, students, grades))"),
    # Mixed: existential with binary
    ("Some cat likes some dog.", "exists x.(exists y.(Cat(x) & Dog(y) & Likes(x, y)))"),
    # Ground disjunction
    ("John is tall or Mary is smart.", "(Tall(john) | Smart(mary))"),
    # Negated ground
    ("John does not like Mary.", "-Likes(john, mary)"),
    # Complex antecedent
    ("All large animals that eat meat are predators.", "all x.((Large(x) & Animal(x) & EatsMeat(x)) -> Predator(x))"),
]


def gate1_hand_picked(verbose: bool = True):
    """Gate 1: Generate v2 suites for 20 hand-picked premises, inspect structure."""
    print("=" * 70)
    print("GATE 1: Hand-picked premises (20)")
    print("=" * 70)
    print()

    passed = 0
    failed = 0

    for nl, fol in HAND_PICKED:
        result = generate_test_suite_from_gold(
            fol, nl=nl, verify_round_trip=True, with_contrastives=True, timeout_s=5
        )
        if result.error:
            print(f"  FAIL: {nl[:50]}")
            print(f"        FOL: {fol}")
            print(f"        Error: {result.error}")
            failed += 1
        else:
            passed += 1
            if verbose:
                print(f"  OK: {nl[:50]}")
                print(f"      FOL: {fol}")
                print(f"      Positives: {result.num_positives}, Contrastives: {result.num_contrastives}")
                if result.suite:
                    for p in result.suite.positives[:3]:
                        print(f"        + {p.fol}")
                    if result.num_positives > 3:
                        print(f"        ... +{result.num_positives - 3} more")
                    for c in result.suite.contrastives[:2]:
                        print(f"        - [{c.mutation_kind}] {c.fol}")
                    if result.num_contrastives > 2:
                        print(f"        ... +{result.num_contrastives - 2} more")
                print()

    print(f"\nGate 1 result: {passed}/{passed+failed} passed")
    gate_pass = failed == 0
    print(f"Gate 1: {'PASS' if gate_pass else 'FAIL'}")
    return gate_pass


def gate2_full_corpus(fast: bool = False):
    """Gate 2: All RT-verified premises generate valid v2 suites."""
    print()
    print("=" * 70)
    print("GATE 2: Full corpus suite generation")
    print("=" * 70)
    print()

    print("Loading FOLIO train split...")
    ds = load_dataset("tasksource/folio", split="train")

    # Dedup premises
    unique_premises: dict = {}
    for row in ds:
        premises_nl = (row.get("premises", "") or "").split("\n")
        premises_fol = (row.get("premises-FOL", "") or "").split("\n")
        for nl, fol in zip(premises_nl, premises_fol):
            nl = nl.strip()
            fol = fol.strip()
            if nl and fol and nl not in unique_premises:
                unique_premises[nl] = fol

    total = len(unique_premises)
    print(f"Unique premises: {total}")

    # Phase 1: Parse and RT-verify (identify the working set)
    rt_verified = []
    parse_failed = 0
    rt_failed = 0

    print("Parsing and RT-verifying...")
    t0 = time.time()
    for i, (nl, raw_fol) in enumerate(unique_premises.items()):
        if (i + 1) % 200 == 0:
            print(f"  [{i+1}/{total}]...")

        try:
            ext = parse_gold_fol(raw_fol, nl=nl)
        except ParseError:
            parse_failed += 1
            continue

        compiled = compile_canonical_fol(ext)
        normalized = normalize_fol_string(raw_fol)
        fwd = check_entailment(compiled, normalized, timeout=5)
        bwd = check_entailment(normalized, compiled, timeout=5)

        if fwd is True and bwd is True:
            rt_verified.append((nl, raw_fol))
        else:
            rt_failed += 1

    elapsed_parse = time.time() - t0
    print(f"Parse + RT check done in {elapsed_parse:.1f}s")
    print(f"  RT-verified: {len(rt_verified)}")
    print(f"  Parse failed: {parse_failed}")
    print(f"  RT failed: {rt_failed}")
    print()

    # Phase 2: Generate test suites for all RT-verified
    # In fast mode, skip contrastives (much faster)
    print(f"Generating v2 test suites ({'fast mode - no contrastives' if fast else 'full with contrastives'})...")
    suite_success = 0
    suite_error = 0
    error_reasons = Counter()
    total_positives = 0
    total_contrastives = 0
    zero_positive_count = 0

    t1 = time.time()
    for i, (nl, raw_fol) in enumerate(rt_verified):
        if (i + 1) % 200 == 0:
            print(f"  [{i+1}/{len(rt_verified)}]...")

        result = generate_test_suite_from_gold(
            raw_fol, nl=nl,
            verify_round_trip=False,  # Already verified above
            with_contrastives=not fast,
            timeout_s=5,
        )

        if result.error:
            suite_error += 1
            error_reasons[result.error[:50]] += 1
        else:
            suite_success += 1
            total_positives += result.num_positives
            total_contrastives += result.num_contrastives
            if result.num_positives == 0:
                zero_positive_count += 1

    elapsed_suite = time.time() - t1
    print(f"Suite generation done in {elapsed_suite:.1f}s")
    print()
    print(f"Results:")
    print(f"  Success: {suite_success}/{len(rt_verified)} ({100*suite_success/len(rt_verified):.1f}%)")
    print(f"  Errors: {suite_error}")
    if error_reasons:
        print(f"  Error breakdown:")
        for reason, count in error_reasons.most_common(5):
            print(f"    {reason}: {count}")
    print(f"  Avg positives: {total_positives/suite_success:.1f}")
    print(f"  Avg contrastives: {total_contrastives/suite_success:.1f}")
    if zero_positive_count:
        print(f"  WARNING: {zero_positive_count} suites with 0 positives")
    print()

    gate_pass = suite_success == len(rt_verified) and zero_positive_count == 0
    print(f"Gate 2: {'PASS' if gate_pass else 'FAIL'}")
    print(f"  (100% suite generation from RT-verified set: {gate_pass})")
    return gate_pass


def gate3_self_score(fast: bool = False, sample_size: int = 0):
    """Gate 3: Gold FOL scores recall=1.0 on its own v2 suite (≥95%)."""
    print()
    print("=" * 70)
    print("GATE 3: Gold self-score (recall=1.0)")
    print("=" * 70)
    print()

    print("Loading FOLIO train split...")
    ds = load_dataset("tasksource/folio", split="train")

    unique_premises: dict = {}
    for row in ds:
        premises_nl = (row.get("premises", "") or "").split("\n")
        premises_fol = (row.get("premises-FOL", "") or "").split("\n")
        for nl, fol in zip(premises_nl, premises_fol):
            nl = nl.strip()
            fol = fol.strip()
            if nl and fol and nl not in unique_premises:
                unique_premises[nl] = fol

    # First pass: get RT-verified set
    rt_verified = []
    print("Identifying RT-verified premises...")
    for i, (nl, raw_fol) in enumerate(unique_premises.items()):
        if (i + 1) % 200 == 0:
            print(f"  [{i+1}/{len(unique_premises)}]...")
        try:
            ext = parse_gold_fol(raw_fol, nl=nl)
        except ParseError:
            continue

        compiled = compile_canonical_fol(ext)
        normalized = normalize_fol_string(raw_fol)
        fwd = check_entailment(compiled, normalized, timeout=5)
        bwd = check_entailment(normalized, compiled, timeout=5)
        if fwd is True and bwd is True:
            rt_verified.append((nl, raw_fol))

    print(f"RT-verified premises: {len(rt_verified)}")

    if sample_size > 0 and sample_size < len(rt_verified):
        import random
        random.seed(42)
        rt_verified = random.sample(rt_verified, sample_size)
        print(f"Sampling {sample_size} for self-score test")

    # Score each gold FOL against its own suite
    print(f"\nScoring gold against own v2 suites...")
    perfect_recall = 0
    imperfect_recall = 0
    score_errors = 0
    imperfect_details = []

    t0 = time.time()
    for i, (nl, raw_fol) in enumerate(rt_verified):
        if (i + 1) % 100 == 0:
            print(f"  [{i+1}/{len(rt_verified)}]...")

        result = generate_test_suite_from_gold(
            raw_fol, nl=nl,
            verify_round_trip=False,
            with_contrastives=False,  # Only test positives for self-score
            timeout_s=5,
        )
        if result.error or result.suite is None:
            score_errors += 1
            continue

        # Score the gold FOL (normalized) against its own test suite
        normalized = normalize_fol_string(raw_fol)
        try:
            report = score(result.suite, normalized, timeout_s=5)
        except Exception as e:
            score_errors += 1
            continue

        if report.recall == 1.0:
            perfect_recall += 1
        else:
            imperfect_recall += 1
            if len(imperfect_details) < 20:
                imperfect_details.append({
                    "nl": nl[:80],
                    "fol": raw_fol[:120],
                    "recall": report.recall,
                    "positives_entailed": report.positives_entailed,
                    "positives_total": report.positives_total,
                    "failed_tests": [
                        (kind, fol_str)
                        for kind, fol_str, verdict in report.per_test_results
                        if verdict != "entailed"
                    ],
                })

    elapsed = time.time() - t0
    scored_total = perfect_recall + imperfect_recall
    print(f"\nSelf-score complete in {elapsed:.1f}s")
    print(f"  Scored: {scored_total}")
    print(f"  Score errors: {score_errors}")
    print(f"  Perfect recall (1.0): {perfect_recall} ({100*perfect_recall/scored_total:.1f}%)")
    print(f"  Imperfect recall: {imperfect_recall} ({100*imperfect_recall/scored_total:.1f}%)")

    if imperfect_details:
        print(f"\n  Imperfect recall samples (first {len(imperfect_details)}):")
        for d in imperfect_details[:10]:
            print(f"    NL: {d['nl']}")
            print(f"    FOL: {d['fol']}")
            print(f"    Recall: {d['recall']:.3f} ({d['positives_entailed']}/{d['positives_total']})")
            if d["failed_tests"]:
                for kind, fol_str in d["failed_tests"][:2]:
                    print(f"      Failed: {fol_str[:80]}")
            print()

    perfect_rate = perfect_recall / scored_total if scored_total else 0
    gate_pass = perfect_rate >= 0.95
    print(f"Gate 3: {'PASS' if gate_pass else 'FAIL'}")
    print(f"  (Perfect recall rate: {100*perfect_rate:.1f}%, target: >= 95%)")

    # Save detailed report
    report_data = {
        "scored_total": scored_total,
        "perfect_recall": perfect_recall,
        "imperfect_recall": imperfect_recall,
        "score_errors": score_errors,
        "perfect_rate": perfect_rate,
        "gate_pass": gate_pass,
        "imperfect_details": imperfect_details,
    }
    out_path = Path("reports/stage2_self_score.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report_data, indent=2, default=str))
    print(f"\nDetailed report saved to: {out_path}")

    return gate_pass


def main():
    parser = argparse.ArgumentParser(description="Stage 2 validation gates")
    parser.add_argument(
        "--gate", choices=["1", "2", "3", "all"], default="all",
        help="Which gate to run (default: all)"
    )
    parser.add_argument(
        "--fast", action="store_true",
        help="Fast mode: skip contrastives in gate 2, smaller sample in gate 3"
    )
    parser.add_argument(
        "--sample", type=int, default=0,
        help="Sample size for gate 3 (0 = all, useful for quick checks)"
    )
    args = parser.parse_args()

    if not is_vampire_available():
        print("ERROR: Vampire is required for Stage 2 validation.")
        sys.exit(1)

    results = {}

    if args.gate in ("1", "all"):
        results["gate1"] = gate1_hand_picked()

    if args.gate in ("2", "all"):
        results["gate2"] = gate2_full_corpus(fast=args.fast)

    if args.gate in ("3", "all"):
        results["gate3"] = gate3_self_score(fast=args.fast, sample_size=args.sample)

    # Summary
    print()
    print("=" * 70)
    print("STAGE 2 SUMMARY")
    print("=" * 70)
    for gate, passed in results.items():
        print(f"  {gate}: {'PASS' if passed else 'FAIL'}")
    all_pass = all(results.values())
    print(f"\n  Overall: {'ALL GATES PASS' if all_pass else 'SOME GATES FAILED'}")


if __name__ == "__main__":
    main()
