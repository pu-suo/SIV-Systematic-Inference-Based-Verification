"""
Coverage report for the deterministic gold FOL parser (Stage 1).

Loads all unique FOLIO train premises, attempts parse_gold_fol() on each,
and reports three buckets:
  1. Converted + round-trip passes → evaluation set
  2. Converted + round-trip FAILS → investigation bucket
  3. Rejected → categorized by reason

Run: python scripts/parser_coverage_report.py
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datasets import load_dataset

from siv.compiler import compile_canonical_fol
from siv.fol_parser import ParseError, parse_gold_fol
from siv.fol_utils import normalize_fol_string, parse_fol
from siv.vampire_interface import check_entailment, is_vampire_available


def main():
    print("Loading FOLIO train split...")
    ds = load_dataset("tasksource/folio", split="train")

    # Dedup premises
    unique_premises: dict = {}  # nl -> (raw_fol, normalized_fol)
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

    # Track results
    converted = []  # (nl, fol, compiled)
    rejected = []  # (nl, fol, reason_category, message)
    round_trip_pass = []
    round_trip_fail = []

    rejection_categories = Counter()

    t0 = time.time()
    for i, (nl, raw_fol) in enumerate(unique_premises.items()):
        if (i + 1) % 200 == 0:
            print(f"  [{i+1}/{total}]...")

        try:
            ext = parse_gold_fol(raw_fol, nl=nl)
            compiled = compile_canonical_fol(ext)
            converted.append((nl, raw_fol, compiled))
        except ParseError as e:
            msg = str(e)
            if "NLTK parse failure" in msg:
                cat = "nltk_parse_failure"
            elif "free individual variables" in msg:
                cat = "free_indvar"
            elif "degenerate" in msg:
                cat = "degenerate_pattern"
            elif "args length" in msg and "!= declared arity" in msg:
                cat = "predicate_arity_inconsistency"
            elif "validation failure" in msg:
                cat = "validation_failure"
            elif "unsupported" in msg:
                cat = "unsupported_expression"
            else:
                cat = "other"
            rejected.append((nl, raw_fol, cat, msg))
            rejection_categories[cat] += 1

    elapsed = time.time() - t0
    print(f"Parsing complete in {elapsed:.1f}s")
    print(f"  Converted: {len(converted)}")
    print(f"  Rejected: {len(rejected)}")
    print()

    # Round-trip verification via Vampire
    vampire_ok = is_vampire_available()
    if vampire_ok:
        print("Running round-trip Vampire equivalence checks...")
        for i, (nl, raw_fol, compiled) in enumerate(converted):
            if (i + 1) % 200 == 0:
                print(f"  [{i+1}/{len(converted)}]...")

            normalized_gold = normalize_fol_string(raw_fol)

            # Check: compiled entails gold AND gold entails compiled
            fwd = check_entailment(compiled, normalized_gold, timeout=5)
            bwd = check_entailment(normalized_gold, compiled, timeout=5)

            if fwd is True and bwd is True:
                round_trip_pass.append((nl, raw_fol, compiled))
            else:
                round_trip_fail.append((nl, raw_fol, compiled, fwd, bwd))
    else:
        print("WARNING: Vampire not available. Skipping round-trip checks.")
        round_trip_pass = converted
        round_trip_fail = []

    # Report
    print()
    print("=" * 70)
    print("PARSER COVERAGE REPORT")
    print("=" * 70)
    print()
    print(f"Total unique FOLIO train premises: {total}")
    print(f"Converted successfully: {len(converted)} ({100*len(converted)/total:.1f}%)")
    print(f"Rejected: {len(rejected)} ({100*len(rejected)/total:.1f}%)")
    print()

    if vampire_ok:
        rt_rate = (
            100 * len(round_trip_fail) / len(converted) if converted else 0
        )
        print(f"Round-trip verification (Vampire):")
        print(f"  Pass: {len(round_trip_pass)} ({100*len(round_trip_pass)/len(converted):.1f}%)")
        print(f"  FAIL: {len(round_trip_fail)} ({rt_rate:.1f}%)")
        if rt_rate > 3.0:
            print(f"  *** WARNING: Round-trip failure rate {rt_rate:.1f}% > 3% threshold ***")
        print()

    print("Rejection breakdown:")
    for cat, count in rejection_categories.most_common():
        print(f"  {cat}: {count} ({100*count/total:.1f}%)")
    print()

    # Save detailed report
    report = {
        "total_premises": total,
        "converted": len(converted),
        "rejected": len(rejected),
        "round_trip_pass": len(round_trip_pass),
        "round_trip_fail": len(round_trip_fail),
        "round_trip_fail_rate": (
            len(round_trip_fail) / len(converted) if converted else 0
        ),
        "rejection_breakdown": dict(rejection_categories),
        "vampire_available": vampire_ok,
        "rejected_samples": [
            {"nl": nl[:100], "fol": fol[:150], "category": cat, "message": msg[:200]}
            for nl, fol, cat, msg in rejected[:50]
        ],
        "round_trip_failures": [
            {"nl": nl[:100], "compiled": compiled[:150], "fwd": fwd, "bwd": bwd}
            for nl, raw_fol, compiled, fwd, bwd in round_trip_fail[:30]
        ],
    }

    out_path = Path("reports/parser_coverage_report.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"Detailed report saved to: {out_path}")

    # Stage 1 completion gates
    print()
    print("=" * 70)
    print("STAGE 1 COMPLETION GATES")
    print("=" * 70)
    conversion_rate = len(converted) / total
    print(f"  Conversion rate: {100*conversion_rate:.1f}% (target: >= 89.5%): "
          f"{'PASS' if conversion_rate >= 0.895 else 'FAIL'}")
    if vampire_ok and converted:
        rt_fail_rate = len(round_trip_fail) / len(converted)
        print(f"  Round-trip fail rate: {100*rt_fail_rate:.1f}% (target: < 3%): "
              f"{'PASS' if rt_fail_rate < 0.03 else 'FAIL'}")


if __name__ == "__main__":
    main()
