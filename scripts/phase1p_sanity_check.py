"""Phase 1P sanity check: verify SIV-soft scores gold > Tier B perturbations.

Pulls 10 pairs per Tier B operator (50 total), scores both gold and perturbed
with SIV soft-mode, reports per-operator and overall win rates.

Also times Vampire calls for wall-time estimation before full scoring.

GATE: overall win rate >= 80%, no single operator below 60%.

Usage:
    python scripts/phase1p_sanity_check.py
"""
from __future__ import annotations

import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))


def main() -> int:
    test_suites_path = _REPO_ROOT / "reports" / "phase1p" / "test_suites.jsonl"
    candidates_path = _REPO_ROOT / "reports" / "phase1p" / "candidates_v1.jsonl"
    output_path = _REPO_ROOT / "reports" / "phase1p" / "sanity_check.json"

    # Load test suites keyed by premise_id
    from scripts.score_candidates import load_test_suites, _reconstruct_test_suite, score_soft
    suites = load_test_suites(test_suites_path)
    sys.stderr.write(f"[sanity] Loaded {len(suites)} test suites\n")

    # Load candidates
    candidates = []
    for line in candidates_path.read_text().splitlines():
        if line.strip():
            candidates.append(json.loads(line))
    sys.stderr.write(f"[sanity] Loaded {len(candidates)} candidates\n")

    # Group by premise_id
    by_premise: Dict[str, Dict[str, List]] = defaultdict(lambda: {"gold": [], "tierB": []})
    for c in candidates:
        pid = c["premise_id"]
        if c["candidate_type"] == "C_gold":
            by_premise[pid]["gold"].append(c)
        elif c["candidate_type"] == "C_pert_tierB":
            by_premise[pid]["tierB"].append(c)

    # Group Tier B candidates by operator
    TIER_B_OPS = ["B_arg_swap", "B_restrictor_drop", "B_restrictor_add",
                  "B_scope_flip", "B_quantifier_swap"]

    by_op: Dict[str, List] = defaultdict(list)
    for pid, groups in by_premise.items():
        if not groups["gold"] or pid not in suites:
            continue
        for tb in groups["tierB"]:
            op = tb.get("perturbation_operator", "")
            if op in TIER_B_OPS:
                by_op[op].append((pid, groups["gold"][0], tb))

    sys.stderr.write(f"[sanity] Tier B pairs by operator:\n")
    for op in TIER_B_OPS:
        sys.stderr.write(f"  {op}: {len(by_op[op])} pairs available\n")

    # Sample 10 per operator
    rng = random.Random(42)
    samples = []
    for op in TIER_B_OPS:
        pool = by_op[op]
        if len(pool) < 10:
            sys.stderr.write(f"  WARNING: {op} has only {len(pool)} pairs (need 10)\n")
            selected = pool
        else:
            selected = rng.sample(pool, 10)
        samples.extend([(op, pid, gold, pert) for pid, gold, pert in selected])

    sys.stderr.write(f"[sanity] Scoring {len(samples)} pairs...\n")

    # Score each pair
    results = []
    timings = []

    for i, (op, pid, gold_cand, pert_cand) in enumerate(samples):
        suite_dict = suites[pid]
        suite = _reconstruct_test_suite(suite_dict)
        canonical = suite_dict.get("canonical_fol", "")

        # Score gold
        t0 = time.time()
        gold_score = score_soft(suite, gold_cand["candidate_fol"], canonical, timeout_s=10)
        t_gold = time.time() - t0

        # Score perturbed
        t0 = time.time()
        pert_score = score_soft(suite, pert_cand["candidate_fol"], canonical, timeout_s=10)
        t_pert = time.time() - t0

        gold_recall = gold_score.get("recall", 0)
        pert_recall = pert_score.get("recall", 0)
        win = gold_recall > pert_recall

        results.append({
            "operator": op,
            "premise_id": pid,
            "gold_recall": gold_recall,
            "pert_recall": pert_recall,
            "win": win,
            "gap": gold_recall - pert_recall,
        })
        timings.append(t_gold + t_pert)

        sys.stderr.write(
            f"\r[sanity] {i+1}/{len(samples)} scored "
            f"({op}: gold={gold_recall:.2f} pert={pert_recall:.2f} "
            f"{'WIN' if win else 'LOSS'} {t_gold+t_pert:.1f}s)"
        )
        sys.stderr.flush()

    sys.stderr.write("\n\n")

    # Compute per-operator and overall stats
    per_op = {}
    for op in TIER_B_OPS:
        op_results = [r for r in results if r["operator"] == op]
        if not op_results:
            per_op[op] = {"n": 0, "win_rate": 0, "mean_gap": 0}
            continue
        wins = sum(r["win"] for r in op_results)
        gaps = [r["gap"] for r in op_results]
        per_op[op] = {
            "n": len(op_results),
            "wins": wins,
            "win_rate": round(wins / len(op_results), 4),
            "mean_gap": round(sum(gaps) / len(gaps), 4),
        }

    total_wins = sum(r["win"] for r in results)
    overall_win_rate = total_wins / len(results) if results else 0

    # Timing stats
    mean_time = sum(timings) / len(timings) if timings else 0
    sorted_timings = sorted(timings)
    p95_time = sorted_timings[int(0.95 * len(sorted_timings))] if timings else 0
    estimated_total_8k = mean_time * 8286

    output = {
        "n_samples": len(samples),
        "overall_win_rate": round(overall_win_rate, 4),
        "overall_wins": total_wins,
        "per_operator": per_op,
        "timing": {
            "mean_per_pair_s": round(mean_time, 2),
            "p95_per_pair_s": round(p95_time, 2),
            "estimated_total_8286_candidates_hours": round(estimated_total_8k / 3600, 1),
        },
        "gate_pass": overall_win_rate >= 0.80,
        "operator_flags": {
            op: per_op[op]["win_rate"] < 0.60
            for op in TIER_B_OPS if op in per_op and per_op[op]["n"] > 0
        },
        "results": results,
    }

    # Print summary
    sys.stderr.write("=== SANITY CHECK RESULTS ===\n")
    sys.stderr.write(f"Overall win rate: {overall_win_rate:.1%} ({total_wins}/{len(results)})\n")
    sys.stderr.write(f"Gate threshold: 80%  -> {'PASS' if output['gate_pass'] else 'FAIL'}\n\n")

    sys.stderr.write("Per-operator:\n")
    for op in TIER_B_OPS:
        s = per_op.get(op, {})
        wr = s.get("win_rate", 0)
        flag = " *** BELOW 60%" if wr < 0.60 and s.get("n", 0) > 0 else ""
        sys.stderr.write(f"  {op:25s}: {wr:.1%} ({s.get('wins',0)}/{s.get('n',0)}) "
                         f"mean_gap={s.get('mean_gap',0):+.3f}{flag}\n")

    sys.stderr.write(f"\nTiming:\n")
    sys.stderr.write(f"  Mean per pair: {mean_time:.2f}s\n")
    sys.stderr.write(f"  P95 per pair: {p95_time:.2f}s\n")
    sys.stderr.write(f"  Estimated total for {8286} candidates: "
                     f"{estimated_total_8k/3600:.1f} hours\n")

    output_path.write_text(json.dumps(output, indent=2))
    sys.stderr.write(f"\nWrote {output_path}\n")

    return 0 if output["gate_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
