"""Generate Tier 2 perturbation candidates and compute metric sensitivity.

For a stratified sample of premises, applies each of the six mutation
operators individually, scores each mutant with SIV and BLEU, and outputs
a sensitivity table showing per-operator metric deltas.

No human annotation needed — the perturbation IS the ground truth (a
deliberate corruption), so the question is whether the metric detects it.

Usage:
    python scripts/generate_perturbation_candidates.py
    python scripts/generate_perturbation_candidates.py --n-premises 15
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).parent.parent
load_dotenv(_REPO_ROOT / ".env")

import os
sys.path.insert(0, str(_REPO_ROOT))

if not os.environ.get("OPENAI_API_KEY"):
    sys.stderr.write(
        f"[perturbation] OPENAI_API_KEY not set. Configure it in {_REPO_ROOT / '.env'}\n"
    )
    sys.exit(2)

from datasets import load_dataset
from openai import OpenAI

from siv.compiler import _a_formula, compile_canonical_fol, compile_sentence_test_suite
from siv.contrastive_generator import (
    OPERATOR_NAMES,
    classify_structure,
    drop_restrictor_conjunct,
    flip_connective,
    flip_quantifier,
    negate_atom,
    replace_subformula_with_negation,
    swap_binary_args,
)
from siv.extractor import extract_sentence
from siv.frozen_client import FrozenClient
from siv.schema import SchemaViolation
from siv.scorer import score

from scripts.compute_baseline_metrics import compute_bleu

_OPERATORS = {
    "negate_atom": negate_atom,
    "swap_binary_args": swap_binary_args,
    "flip_quantifier": flip_quantifier,
    "drop_restrictor_conjunct": drop_restrictor_conjunct,
    "flip_connective": flip_connective,
    "replace_subformula_with_negation": replace_subformula_with_negation,
}


# ── Premise selection (stratified by structural class) ───────────────────────

TARGET_CLASSES = [
    "simple_universal",
    "compound_restrictor_universal",
    "ground_instance",
    "simple_existential",
    "other",
]


def select_premises(
    report_path: str,
    n_premises: int = 12,
) -> List[Dict[str, Any]]:
    """Select premises stratified by structural class.

    Prioritizes premises with high self-consistency (recall >= 0.9) to ensure
    the test suite is reliable. Samples across structural classes.
    """
    data = json.loads(Path(report_path).read_text(encoding="utf-8"))

    # Group by structural class — no self-consistency filter to avoid
    # biasing toward structurally simpler premises (audit fix 2d).
    by_class: Dict[str, List[Dict]] = defaultdict(list)
    for p in data["per_pair"]:
        by_class[p["structural_class"]].append(p)

    # Sample proportionally
    selected = []
    per_class = max(2, n_premises // len(TARGET_CLASSES))
    for cls in TARGET_CLASSES:
        candidates = by_class.get(cls, [])
        selected.extend(candidates[:per_class])
        if len(selected) >= n_premises:
            break

    # Fill remaining from any class
    if len(selected) < n_premises:
        all_remaining = [p for ps in by_class.values() for p in ps if p not in selected]
        selected.extend(all_remaining[: n_premises - len(selected)])

    return selected[:n_premises]


# ── Per-premise perturbation ─────────────────────────────────────────────────

def perturb_premise(
    p: Dict[str, Any],
    client: Any,
    timeout_s: int = 10,
) -> List[Dict[str, Any]]:
    """Apply all six operators to a premise and score each mutant."""
    nl = p["nl"]

    # Re-extract to get the full SentenceExtraction object
    try:
        extraction = extract_sentence(nl, client)
    except Exception as e:
        sys.stderr.write(f"[perturbation] extraction failed for '{nl[:60]}': {e}\n")
        return []

    canonical = compile_canonical_fol(extraction)

    try:
        suite = compile_sentence_test_suite(extraction, timeout_s=timeout_s)
    except Exception as e:
        sys.stderr.write(f"[perturbation] suite compilation failed: {e}\n")
        return []

    # Score the canonical (baseline)
    try:
        baseline_report = score(suite, canonical, timeout_s=timeout_s)
    except Exception as e:
        sys.stderr.write(f"[perturbation] baseline scoring failed: {e}\n")
        return []

    results = []
    mutation_stats = {op: {"attempted": 0, "schema_fail": 0, "score_fail": 0, "duplicate": 0}
                      for op in OPERATOR_NAMES}

    # Add baseline row (self-BLEU is 1.0 by definition, not by computation)
    results.append({
        "story_id": p["story_id"],
        "nl": nl,
        "structural_class": p["structural_class"],
        "operator": "baseline",
        "canonical_fol": canonical,
        "mutant_fol": canonical,
        "siv_recall": baseline_report.recall,
        "siv_precision": baseline_report.precision,
        "siv_f1": baseline_report.f1,
        "bleu_vs_canonical": 1.0,
        "siv_recall_delta": 0.0,
        "bleu_delta": 0.0,
    })

    # Apply each operator
    for op_name in OPERATOR_NAMES:
        op = _OPERATORS[op_name]
        mutants = op(extraction.formula)

        if not mutants:
            continue

        # Take first valid mutant per operator (representative, not exhaustive)
        for mutant_formula in mutants:
            mutation_stats[op_name]["attempted"] += 1
            try:
                mutant_fol = _a_formula(mutant_formula)
            except SchemaViolation:
                mutation_stats[op_name]["schema_fail"] += 1
                continue

            if mutant_fol == canonical:
                mutation_stats[op_name]["duplicate"] += 1
                continue

            # Score mutant against the original test suite
            try:
                mutant_report = score(suite, mutant_fol, timeout_s=timeout_s)
            except Exception:
                mutation_stats[op_name]["score_fail"] += 1
                continue

            mutant_bleu = compute_bleu(mutant_fol, canonical)

            results.append({
                "story_id": p["story_id"],
                "nl": nl,
                "structural_class": p["structural_class"],
                "operator": op_name,
                "canonical_fol": canonical,
                "mutant_fol": mutant_fol,
                "siv_recall": mutant_report.recall,
                "siv_precision": mutant_report.precision,
                "siv_f1": mutant_report.f1,
                "bleu_vs_canonical": mutant_bleu,
                "siv_recall_delta": mutant_report.recall - baseline_report.recall,
                "bleu_delta": mutant_bleu - 1.0,
            })

            break  # One mutant per operator per premise

    # Log mutation stats
    total_attempted = sum(s["attempted"] for s in mutation_stats.values())
    total_dropped = sum(s["schema_fail"] + s["score_fail"] + s["duplicate"]
                        for s in mutation_stats.values())
    if total_dropped > 0:
        sys.stderr.write(
            f"[perturbation]   mutation stats: {total_attempted} attempted, "
            f"{total_dropped} dropped ("
            + ", ".join(f"{op}: {s['schema_fail']}schema/{s['score_fail']}score/{s['duplicate']}dup"
                        for op, s in mutation_stats.items()
                        if s['schema_fail'] + s['score_fail'] + s['duplicate'] > 0)
            + ")\n"
        )

    return results


# ── Main ─────────────────────────────────────────────────────────────────────

COLUMNS = [
    "story_id", "nl", "structural_class", "operator",
    "canonical_fol", "mutant_fol",
    "siv_recall", "siv_precision", "siv_f1",
    "bleu_vs_canonical",
    "siv_recall_delta", "bleu_delta",
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n-premises", type=int, default=12)
    ap.add_argument("--timeout-s", type=int, default=10)
    ap.add_argument(
        "--report", type=str,
        default=str(_REPO_ROOT / "reports" / "folio_agreement.json"),
    )
    ap.add_argument(
        "--output", type=str,
        default=str(_REPO_ROOT / "reports" / "perturbation_sensitivity"),
    )
    args = ap.parse_args()

    premises = select_premises(args.report, args.n_premises)
    sys.stderr.write(
        f"[perturbation] selected {len(premises)} premises across "
        f"{len(set(p['structural_class'] for p in premises))} structural classes\n"
    )

    client = FrozenClient(OpenAI())
    all_results: List[Dict[str, Any]] = []

    t0 = time.time()
    for i, p in enumerate(premises):
        sys.stderr.write(
            f"[perturbation] {i+1}/{len(premises)}: {p['nl'][:60]}...\n"
        )
        results = perturb_premise(p, client, timeout_s=args.timeout_s)
        all_results.extend(results)

    dt = time.time() - t0
    sys.stderr.write(f"[perturbation] done in {dt:.0f}s, {len(all_results)} total rows\n")

    # Write CSV
    csv_path = Path(args.output + ".csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(all_results)

    # Write JSON
    json_path = Path(args.output + ".json")
    json_path.write_text(json.dumps(all_results, indent=2, default=str))

    print(f"Wrote {csv_path} and {json_path}")

    # Summary: per-operator average deltas
    print("\n=== Sensitivity Summary ===")
    print(f"{'Operator':<38} {'SIV Δrecall':>12} {'BLEU Δ':>10} {'N':>4}")
    print("-" * 68)

    for op_name in ["baseline"] + OPERATOR_NAMES:
        op_rows = [r for r in all_results if r["operator"] == op_name]
        if not op_rows:
            continue
        avg_siv_delta = mean(r["siv_recall_delta"] for r in op_rows)
        avg_bleu_delta = mean(r["bleu_delta"] for r in op_rows)
        print(f"{op_name:<38} {avg_siv_delta:>+12.4f} {avg_bleu_delta:>+10.4f} {len(op_rows):>4}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
