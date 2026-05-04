"""
Stage 4: Re-score Exp 2 candidates with v2 (gold-derived) suites.

Headline-preservation gate. Locked Exp 2 has ρ = 0.856. Re-score with v2:
  - ρ ≥ 0.81: headline preserved, move on
  - ρ ∈ [0.78, 0.81): investigate, decompose by category
  - ρ < 0.78: stop and analyze

Also logs per-premise score deltas (v1 vs v2) for diagnostics.

Run: python scripts/stage4_rescore_exp2.py
"""
from __future__ import annotations

import json
import logging
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import List, Optional

import numpy as np
from scipy import stats as scipy_stats

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from experiments.common import (
    align_symbols,
    extract_symbols_from_fol,
    rewrite_fol_strings,
    rewrite_test_suite,
)
from siv.compiler import compile_canonical_fol
from siv.contrastive_generator import derive_witness_axioms
from siv.fol_parser import parse_gold_fol
from siv.gold_suite_generator import generate_test_suite_from_gold
from siv.scorer import ScoreReport, score
from siv.vampire_interface import is_vampire_available

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

EXP2_DIR = _REPO_ROOT / "reports" / "experiments" / "exp2"
OUT_DIR = _REPO_ROOT / "reports" / "stage4"


def load_exp2_data():
    """Load curated premises and scored candidates from Exp 2."""
    premises = {}
    for line in (EXP2_DIR / "curated_premises.jsonl").read_text().strip().split("\n"):
        row = json.loads(line)
        premises[row["premise_id"]] = row

    scored = []
    for line in (EXP2_DIR / "scored_candidates.jsonl").read_text().strip().split("\n"):
        if line.strip():
            scored.append(json.loads(line))

    return premises, scored


def score_candidate_v2(
    v2_suite,
    v2_canonical_fol: str,
    candidate_fol: str,
    timeout: int = 10,
    threshold: float = 0.6,
) -> Optional[ScoreReport]:
    """Score candidate against v2 suite using soft alignment (same pipeline as Exp 2)."""
    try:
        siv_symbols = extract_symbols_from_fol(v2_canonical_fol)
        cand_symbols = extract_symbols_from_fol(candidate_fol)
        alignment = align_symbols(siv_symbols, cand_symbols, threshold=threshold)

        rewritten_suite = rewrite_test_suite(v2_suite, alignment)

        raw_witnesses = derive_witness_axioms(v2_suite.extraction)
        rewritten_witnesses = rewrite_fol_strings(raw_witnesses, alignment)

        return score(
            rewritten_suite, candidate_fol, timeout_s=timeout,
            witness_axioms_override=rewritten_witnesses,
        )
    except Exception as e:
        logger.warning("v2 scoring failed: %s", e)
        return None


def compute_rank_correlation(scored_v2: list) -> dict:
    """Compute Spearman ρ using the same methodology as Exp 2 Step 5."""
    # Ground-truth ranks: gold=1, overstrong=2, partial=2, overweak=3, gibberish=4
    gt_ranks = {"gold": 1, "overstrong": 2, "partial": 2, "overweak": 3, "gibberish": 4}

    by_premise = defaultdict(dict)
    for row in scored_v2:
        by_premise[row["premise_id"]][row["candidate_type"]] = row["v2_scores"]

    rho_per_premise = []
    premise_ids_used = []

    for pid, type_scores in by_premise.items():
        non_gold_types = [t for t in ["overstrong", "partial", "overweak", "gibberish"]
                          if t in type_scores]
        if len(non_gold_types) < 3:
            continue

        premise_ids_used.append(pid)
        gt_ranks_vec = [gt_ranks[t] for t in non_gold_types]

        metric_scores = []
        for t in non_gold_types:
            val = type_scores[t].get("siv_soft_recall")
            metric_scores.append(val if val is not None else 0.0)

        if len(set(metric_scores)) > 1:
            rho, _ = scipy_stats.spearmanr(metric_scores, [-r for r in gt_ranks_vec])
            rho_per_premise.append(rho)
        else:
            rho_per_premise.append(0.0)

    rhos = np.array(rho_per_premise)
    mean_rho = float(rhos.mean())

    # Bootstrap CI
    rng = np.random.RandomState(42)
    boot = [rng.choice(rhos, size=len(rhos), replace=True).mean() for _ in range(1000)]
    ci_lo = float(np.percentile(boot, 2.5))
    ci_hi = float(np.percentile(boot, 97.5))

    return {
        "mean_rho": round(mean_rho, 4),
        "ci_lo": round(ci_lo, 4),
        "ci_hi": round(ci_hi, 4),
        "n_premises": len(rhos),
        "per_premise_rhos": {pid: float(r) for pid, r in zip(premise_ids_used, rho_per_premise)},
    }


def main():
    if not is_vampire_available():
        print("ERROR: Vampire is required for Stage 4.")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    premises, scored_v1 = load_exp2_data()
    logger.info("Loaded %d premises, %d scored candidates", len(premises), len(scored_v1))

    # ── Step 1: Generate v2 suites for all Exp 2 premises ──
    print()
    print("=" * 70)
    print("STAGE 4: Re-score Exp 2 with v2 suites")
    print("=" * 70)
    print()

    print("Generating v2 test suites for Exp 2 premises...")
    v2_suites = {}  # premise_id -> (TestSuite, canonical_fol)
    v2_gen_failures = []

    for pid, pdata in premises.items():
        result = generate_test_suite_from_gold(
            pdata["gold_fol"], nl=pdata["nl"],
            verify_round_trip=True,
            with_contrastives=True,
            timeout_s=10,
        )
        if result.error or result.suite is None:
            v2_gen_failures.append((pid, result.error))
            continue

        ext = parse_gold_fol(pdata["gold_fol"], nl=pdata["nl"])
        canonical = compile_canonical_fol(ext)
        v2_suites[pid] = (result.suite, canonical)

    print(f"  v2 suites generated: {len(v2_suites)}/{len(premises)}")
    if v2_gen_failures:
        print(f"  Failures: {len(v2_gen_failures)}")
        for pid, err in v2_gen_failures:
            print(f"    {pid}: {err}")
    print()

    # Suite comparison stats
    v2_pos_counts = []
    v2_con_counts = []
    for pid, (suite, _) in v2_suites.items():
        v2_pos_counts.append(len(suite.positives))
        v2_con_counts.append(len(suite.contrastives))
    print(f"  v2 suite stats:")
    print(f"    Avg positives: {np.mean(v2_pos_counts):.1f} (v1 avg: {np.mean([p['n_positives'] for p in premises.values()]):.1f})")
    print(f"    Avg contrastives: {np.mean(v2_con_counts):.1f} (v1 avg: {np.mean([p['n_contrastives'] for p in premises.values()]):.1f})")
    print()

    # ── Step 2: Re-score all candidates against v2 suites ──
    print("Scoring candidates against v2 suites...")
    scored_v2 = []
    score_errors = 0

    t0 = time.time()
    for i, row in enumerate(scored_v1):
        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(scored_v1)}]...")

        pid = row["premise_id"]
        if pid not in v2_suites:
            continue

        suite, canonical = v2_suites[pid]
        candidate_fol = row["candidate_fol"]
        candidate_type = row["candidate_type"]

        # For gold type, use the compiled canonical (same as v1 behavior)
        if candidate_type == "gold":
            candidate_fol_to_score = canonical
        else:
            candidate_fol_to_score = candidate_fol

        report = score_candidate_v2(
            suite, canonical, candidate_fol_to_score, timeout=10
        )

        v2_scores = {}
        if report is not None:
            v2_scores = {
                "siv_soft_recall": report.recall,
                "siv_soft_precision": report.precision,
                "siv_soft_f1": report.f1,
            }
        else:
            score_errors += 1
            v2_scores = {"siv_soft_recall": None, "siv_soft_precision": None, "siv_soft_f1": None}

        scored_v2.append({
            "premise_id": pid,
            "candidate_type": candidate_type,
            "candidate_fol": row["candidate_fol"],
            "v1_scores": row["scores"],
            "v2_scores": v2_scores,
        })

    elapsed = time.time() - t0
    print(f"  Scoring complete in {elapsed:.1f}s")
    print(f"  Scored: {len(scored_v2)}, Errors: {score_errors}")
    print()

    # ── Step 3: Mean scores by type (v2) ──
    print("Mean v2 recall by candidate type:")
    by_type = defaultdict(list)
    for row in scored_v2:
        val = row["v2_scores"].get("siv_soft_recall")
        if val is not None:
            by_type[row["candidate_type"]].append(val)

    type_order = ["gold", "overstrong", "partial", "overweak", "gibberish"]
    for t in type_order:
        vals = by_type.get(t, [])
        if vals:
            print(f"  {t:12s}: {np.mean(vals):.4f} (n={len(vals)})")
    print()

    # ── Step 4: Rank correlation ──
    corr = compute_rank_correlation(scored_v2)
    v2_rho = corr["mean_rho"]

    print("=" * 70)
    print("HEADLINE: v2 Spearman ρ")
    print("=" * 70)
    print(f"  v1 ρ (locked): 0.8563 [0.8236, 0.8811]")
    print(f"  v2 ρ:          {v2_rho:.4f} [{corr['ci_lo']:.4f}, {corr['ci_hi']:.4f}]")
    print(f"  n_premises:    {corr['n_premises']}")
    print()

    # Gate decision
    if v2_rho >= 0.81:
        gate = "PASS"
        msg = "Headline preserved. Move on."
    elif v2_rho >= 0.78:
        gate = "INVESTIGATE"
        msg = "Possibly real shift. Decompose by premise category."
    else:
        gate = "STOP"
        msg = "Surface and analyze before declaring rework complete."

    print(f"  Gate: {gate}")
    print(f"  {msg}")
    print()

    # ── Step 5: Per-premise score deltas ──
    print("Per-premise score deltas (v1 vs v2 recall):")
    deltas_by_premise = defaultdict(list)
    for row in scored_v2:
        v1_recall = row["v1_scores"].get("siv_soft_recall")
        v2_recall = row["v2_scores"].get("siv_soft_recall")
        if v1_recall is not None and v2_recall is not None:
            delta = v2_recall - v1_recall
            deltas_by_premise[row["premise_id"]].append({
                "type": row["candidate_type"],
                "v1": v1_recall,
                "v2": v2_recall,
                "delta": delta,
            })

    # Summary stats
    all_deltas = []
    for pid, items in deltas_by_premise.items():
        for item in items:
            all_deltas.append(item["delta"])

    all_deltas_arr = np.array(all_deltas)
    print(f"  Total comparisons: {len(all_deltas)}")
    print(f"  Mean delta: {all_deltas_arr.mean():+.4f}")
    print(f"  Std delta: {all_deltas_arr.std():.4f}")
    print(f"  Median delta: {np.median(all_deltas_arr):+.4f}")
    print(f"  Max positive: {all_deltas_arr.max():+.4f}")
    print(f"  Max negative: {all_deltas_arr.min():+.4f}")
    print()

    # Mean delta by candidate type
    print("  Mean delta by type:")
    delta_by_type = defaultdict(list)
    for row in scored_v2:
        v1_r = row["v1_scores"].get("siv_soft_recall")
        v2_r = row["v2_scores"].get("siv_soft_recall")
        if v1_r is not None and v2_r is not None:
            delta_by_type[row["candidate_type"]].append(v2_r - v1_r)
    for t in type_order:
        vals = delta_by_type.get(t, [])
        if vals:
            print(f"    {t:12s}: {np.mean(vals):+.4f} (n={len(vals)})")
    print()

    # Premises with largest absolute deltas
    premise_mean_delta = {}
    for pid, items in deltas_by_premise.items():
        deltas = [item["delta"] for item in items]
        premise_mean_delta[pid] = np.mean(deltas)

    sorted_premises = sorted(premise_mean_delta.items(), key=lambda x: abs(x[1]), reverse=True)
    print("  Top 10 premises by |mean delta|:")
    for pid, mean_d in sorted_premises[:10]:
        nl = premises[pid]["nl"][:60]
        print(f"    {pid}: delta={mean_d:+.4f}  {nl}")
    print()

    # ── Step 6: Save detailed report ──
    report_data = {
        "v1_rho": 0.8563,
        "v2_rho": v2_rho,
        "v2_ci_lo": corr["ci_lo"],
        "v2_ci_hi": corr["ci_hi"],
        "n_premises": corr["n_premises"],
        "gate": gate,
        "mean_by_type_v2": {
            t: {"mean": float(np.mean(vals)), "n": len(vals)}
            for t, vals in by_type.items()
        },
        "delta_by_type": {
            t: {"mean_delta": float(np.mean(vals)), "n": len(vals)}
            for t, vals in delta_by_type.items()
        },
        "per_premise_rho": corr["per_premise_rhos"],
        "v2_suite_stats": {
            "avg_positives": float(np.mean(v2_pos_counts)),
            "avg_contrastives": float(np.mean(v2_con_counts)),
        },
        "score_errors": score_errors,
        "v2_gen_failures": v2_gen_failures,
    }

    out_path = OUT_DIR / "rescore_exp2.json"
    out_path.write_text(json.dumps(report_data, indent=2, default=str))
    print(f"Detailed report saved to: {out_path}")

    # Save per-premise deltas for investigation
    deltas_path = OUT_DIR / "per_premise_deltas.jsonl"
    with open(deltas_path, "w") as f:
        for row in scored_v2:
            f.write(json.dumps(row, default=str) + "\n")
    print(f"Per-premise deltas saved to: {deltas_path}")


if __name__ == "__main__":
    main()
