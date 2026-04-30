"""Phase 1.4 — Localization analysis: can per-premise metrics identify the broken premise?

Two-stage construction:
  Stage 1: Identify load-bearing (story, premise, operator) tuples by perturbing
           each premise with each Tier B operator and checking if entailment flips.
  Stage 2: For each load-bearing tuple, compute per-premise metric scores and
           check if the lowest-scoring premise matches the perturbed one.

All metrics (SIV, BLEU, BERTScore, MALLS-LE, Brunello-LT) get localization
scores as baselines, with chance (1/n) for comparison.

Usage:
    python scripts/phase1_localize.py \\
      --split train --timeout-s 10
    python scripts/phase1_localize.py \\
      --split train --limit 10 --skip-bertscore --skip-siv  # dry run
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from siv.fol_utils import normalize_fol_string, parse_fol
from siv.vampire_interface import prove_strict


# ── Data loading ───────────────────────────────────────────────────────────────

def load_folio_stories(split: str) -> List[Dict[str, Any]]:
    """Load unique FOLIO stories with premises and all their conclusions."""
    from datasets import load_dataset

    ds = load_dataset("tasksource/folio", split=split)
    stories: Dict[int, Dict[str, Any]] = {}

    for row in ds:
        sid = row.get("story_id")
        nl_parts = [p.strip() for p in row["premises"].split("\n") if p.strip()]
        fol_parts = [p.strip() for p in row["premises-FOL"].split("\n") if p.strip()]
        if len(nl_parts) != len(fol_parts):
            continue

        if sid not in stories:
            stories[sid] = {
                "story_id": sid,
                "premises_nl": nl_parts,
                "premises_fol": fol_parts,
                "conclusions": [],
            }

        stories[sid]["conclusions"].append({
            "conclusion_fol": row.get("conclusion-FOL", ""),
            "gold_label": row.get("label", ""),
            "example_id": row.get("example_id", ""),
        })

    return list(stories.values())


# ── Stage 1: Identify load-bearing premises ────────────────────────────────────

LABEL_TO_VERDICT = {"True": "entailment", "False": "contradiction", "Uncertain": "neutral"}


def find_load_bearing_premises(
    story: Dict[str, Any],
    timeout: int = 10,
) -> List[Dict[str, Any]]:
    """Find (premise_idx, operator) tuples where perturbation flips entailment.

    Only operates on conclusions where gold entailment is correct.
    """
    from siv.nltk_perturbations import NotApplicable, select_perturbation
    from siv.aligner import extract_symbols_from_fol

    premises_fol = [normalize_fol_string(f) for f in story["premises_fol"]]
    n = len(premises_fol)

    # Extract story context for perturbation
    all_preds: Set[str] = set()
    all_consts: Set[str] = set()
    for f in premises_fol:
        syms = extract_symbols_from_fol(f)
        all_preds.update(syms["predicates"].keys())
        all_consts.update(syms["constants"])

    load_bearing = []

    for conc_info in story["conclusions"]:
        conc_fol = normalize_fol_string(conc_info["conclusion_fol"])
        gold_label = conc_info["gold_label"]
        expected_verdict = LABEL_TO_VERDICT.get(gold_label, "neutral")

        # Check if gold entailment is correct
        verdict, _ = prove_strict(premises_fol, conc_fol, timeout=timeout)
        if verdict != expected_verdict:
            continue  # Gold doesn't work; skip

        # Try perturbing each premise with each Tier B operator
        for k in range(n):
            expr = parse_fol(premises_fol[k])
            if expr is None:
                continue

            rng = random.Random(42 + k)
            # Try the perturbation — select_perturbation tries all operators in tier
            try:
                perturbed_expr, op_name = select_perturbation(
                    "B", expr, rng,
                    story_predicates=sorted(all_preds),
                    story_constants=sorted(all_consts),
                )
            except NotApplicable:
                continue

            perturbed_fol = str(perturbed_expr)
            perturbed_premises = list(premises_fol)
            perturbed_premises[k] = perturbed_fol

            new_verdict, _ = prove_strict(perturbed_premises, conc_fol, timeout=timeout)
            if new_verdict != expected_verdict:
                load_bearing.append({
                    "story_id": story["story_id"],
                    "example_id": conc_info["example_id"],
                    "premise_idx": k,
                    "operator": op_name,
                    "gold_verdict": expected_verdict,
                    "perturbed_verdict": new_verdict,
                    "perturbed_fol": perturbed_fol,
                    "perturbed_premises": perturbed_premises,
                    "premises_fol_gold": premises_fol,
                    "premises_nl": story["premises_nl"],
                    "conclusion_fol": conc_fol,
                })

    return load_bearing


# ── Stage 2: Localization accuracy ─────────────────────────────────────────────

def compute_localization(
    tuples: List[Dict[str, Any]],
    skip_bertscore: bool = False,
    skip_siv: bool = False,
    skip_equivalence: bool = False,
    timeout_s: int = 10,
    siv_client=None,
) -> Dict[str, Any]:
    """For each load-bearing tuple, check if each metric's argmin = perturbed premise."""

    metrics_to_check = ["bleu"]
    if not skip_bertscore:
        metrics_to_check.append("bertscore")
    if not skip_siv:
        metrics_to_check.append("siv_recall")
    if not skip_equivalence:
        metrics_to_check.extend(["malls_le_aligned", "brunello_lt_aligned"])

    correct_counts = {m: 0 for m in metrics_to_check}
    rank_sums = {m: 0.0 for m in metrics_to_check}
    total = 0

    for t in tuples:
        perturbed_idx = t["premise_idx"]
        n = len(t["perturbed_premises"])
        perturbed_premises = t["perturbed_premises"]
        gold_premises = t["premises_fol_gold"]

        per_premise_scores: Dict[str, List[Optional[float]]] = {m: [] for m in metrics_to_check}

        for i in range(n):
            cand = perturbed_premises[i]
            gold = gold_premises[i]

            # BLEU
            if "bleu" in metrics_to_check:
                from scripts.phase1_compute_metrics import compute_bleu
                per_premise_scores["bleu"].append(compute_bleu(cand, gold))

            # BERTScore (individual, not batched for simplicity)
            if "bertscore" in metrics_to_check:
                from bert_score import score as bs
                _, _, F1 = bs([cand], [gold], lang="en", verbose=False,
                              rescale_with_baseline=False)
                per_premise_scores["bertscore"].append(F1[0].item())

            # SIV
            if "siv_recall" in metrics_to_check and siv_client is not None:
                from scripts.phase1_compute_metrics import score_premise_siv
                nl = t["premises_nl"][i] if i < len(t["premises_nl"]) else ""
                siv_result = score_premise_siv(nl, cand, siv_client, timeout_s)
                per_premise_scores["siv_recall"].append(
                    siv_result["recall"] if siv_result else None
                )

            # MALLS-LE aligned
            if "malls_le_aligned" in metrics_to_check:
                from siv.malls_le import malls_le_equivalence_aligned
                per_premise_scores["malls_le_aligned"].append(
                    malls_le_equivalence_aligned(cand, gold, timeout=timeout_s)
                )

            # Brunello-LT aligned
            if "brunello_lt_aligned" in metrics_to_check:
                from siv.brunello_lt import brunello_lt_equivalence_aligned
                per_premise_scores["brunello_lt_aligned"].append(
                    brunello_lt_equivalence_aligned(cand, gold, timeout=timeout_s)
                )

        # Check localization for each metric
        for m in metrics_to_check:
            scores = per_premise_scores[m]
            # Replace None with a neutral value (0.5 for recall-like, 0.0 for others)
            filled = [s if s is not None else 0.5 for s in scores]
            if not filled:
                continue
            argmin = min(range(len(filled)), key=lambda j: filled[j])
            if argmin == perturbed_idx:
                correct_counts[m] += 1
            # Rank: 1-indexed rank of the perturbed premise (lower is better)
            sorted_indices = sorted(range(len(filled)), key=lambda j: filled[j])
            rank = sorted_indices.index(perturbed_idx) + 1
            rank_sums[m] += rank

        total += 1

    # Compile results
    n_premises_avg = sum(len(t["perturbed_premises"]) for t in tuples) / len(tuples) if tuples else 0

    return {
        "n_tuples": total,
        "n_premises_avg": round(n_premises_avg, 1),
        "chance_accuracy": round(1.0 / n_premises_avg, 4) if n_premises_avg > 0 else 0,
        "chance_mean_rank": round(n_premises_avg / 2, 1) if n_premises_avg > 0 else 0,
        "metrics": {
            m: {
                "localization_accuracy": round(correct_counts[m] / total, 4) if total > 0 else 0,
                "mean_rank": round(rank_sums[m] / total, 2) if total > 0 else 0,
            }
            for m in metrics_to_check
        },
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", type=str, default="train")
    ap.add_argument("--timeout-s", type=int, default=10)
    ap.add_argument("--limit", type=int, default=None,
                    help="Process only first N stories")
    ap.add_argument("--output", type=str,
                    default=str(_REPO_ROOT / "reports" / "phase1" / "localization_results.json"))
    ap.add_argument("--skip-bertscore", action="store_true")
    ap.add_argument("--skip-siv", action="store_true")
    ap.add_argument("--skip-equivalence", action="store_true")
    args = ap.parse_args()

    # Load stories
    stories = load_folio_stories(args.split)
    sys.stderr.write(f"[localize] Loaded {len(stories)} unique stories\n")

    if args.limit:
        stories = stories[:args.limit]

    # Stage 1: Find load-bearing premises
    sys.stderr.write("[localize] Stage 1: Identifying load-bearing premises...\n")
    all_tuples = []
    t0 = time.time()

    for i, story in enumerate(stories):
        lb = find_load_bearing_premises(story, timeout=args.timeout_s)
        all_tuples.extend(lb)

        if (i + 1) % 10 == 0 or i + 1 == len(stories):
            elapsed = time.time() - t0
            sys.stderr.write(
                f"  {i + 1}/{len(stories)} stories processed, "
                f"{len(all_tuples)} load-bearing tuples found "
                f"(elapsed={elapsed:.0f}s)\n"
            )

    sys.stderr.write(
        f"[localize] Stage 1 complete: {len(all_tuples)} load-bearing tuples "
        f"from {len(stories)} stories\n"
    )

    if not all_tuples:
        sys.stderr.write("[localize] No load-bearing tuples found. Exiting.\n")
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps({"n_tuples": 0, "error": "no_load_bearing_tuples"}))
        return 0

    # Initialize SIV client if needed
    siv_client = None
    if not args.skip_siv:
        import os
        from dotenv import load_dotenv
        load_dotenv(_REPO_ROOT / ".env")
        if os.environ.get("OPENAI_API_KEY"):
            from openai import OpenAI
            from siv.frozen_client import FrozenClient
            siv_client = FrozenClient(OpenAI())
        else:
            sys.stderr.write("[localize] OPENAI_API_KEY not set. Skipping SIV.\n")
            args.skip_siv = True

    # Stage 2: Localization accuracy
    sys.stderr.write("[localize] Stage 2: Computing localization accuracy...\n")
    results = compute_localization(
        all_tuples,
        skip_bertscore=args.skip_bertscore,
        skip_siv=args.skip_siv,
        skip_equivalence=args.skip_equivalence,
        timeout_s=args.timeout_s,
        siv_client=siv_client,
    )

    # Operator breakdown
    by_operator = defaultdict(list)
    for t in all_tuples:
        by_operator[t["operator"]].append(t)

    results["by_operator"] = {
        op: {"count": len(tuples)}
        for op, tuples in sorted(by_operator.items())
    }

    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2))

    # Print summary
    sys.stderr.write(f"\n[localize] Results (n={results['n_tuples']}):\n")
    sys.stderr.write(f"  Chance: accuracy={results['chance_accuracy']:.4f}  "
                     f"mean_rank={results['chance_mean_rank']}\n")
    for m, v in results["metrics"].items():
        sys.stderr.write(f"  {m:25s}  accuracy={v['localization_accuracy']:.4f}  "
                         f"mean_rank={v['mean_rank']:.2f}\n")

    sys.stderr.write(f"\n[localize] Wrote {output_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
