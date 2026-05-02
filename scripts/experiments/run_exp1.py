"""Experiment 1 — Binary Correctness (parity demonstration).

Claim: On the standard logical-correctness task, SIV is at least as good as
the strongest reference-based baselines (MALLS-LE-aligned, Brunello-LT-aligned),
and all three crush surface metrics (BLEU, BERTScore).

Steps:
  1. Generate aligned-subset manifest
  2. Generate candidates via perturbation operators
  3. Run smoke test
  4. Score all candidates with all metrics
  5. Primary analysis (tables + figure)
  6. Check acceptance criteria

Usage:
    python scripts/experiments/run_exp1.py --step 1
    python scripts/experiments/run_exp1.py --step 2
    python scripts/experiments/run_exp1.py --step 3
    python scripts/experiments/run_exp1.py --step 4
    python scripts/experiments/run_exp1.py --step 5
    python scripts/experiments/run_exp1.py --step all
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from scripts.experiments.common import (
    auc_roc,
    is_contrastive_eligible,
    load_test_suites,
    paired_bootstrap_ci,
    paired_permutation_p,
    passes_aligned_subset_filter,
    score_bertscore,
    score_bleu,
    score_brunello_lt_aligned,
    score_brunello_lt_raw,
    score_malls_le_aligned,
    score_malls_le_raw,
    score_siv_soft,
    score_siv_strict,
)
from siv.fol_utils import free_individual_variables, normalize_fol_string, parse_fol
from siv.nltk_perturbations import (
    B_arg_swap,
    B_restrictor_drop,
    B_scope_flip,
    C_negation_drop,
    D_random_predicates,
    NotApplicable,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

EXP1_DIR = _REPO_ROOT / "reports" / "experiments" / "exp1"
CACHE_PATH = _REPO_ROOT / "reports" / "test_suites" / "test_suites.jsonl"
FAILURE_ANALYSIS_PATH = _REPO_ROOT / "reports" / "phase1_pillar1" / "failure_analysis.json"
ENTAILMENT_RESULTS_PATH = _REPO_ROOT / "reports" / "phase1_pillar1" / "entailment_results.jsonl"

SEED = 42
JACCARD_THRESHOLD = 0.5  # Relaxed from 0.6 per spec §1.1 acceptance clause
SMOKE_N = 30
SIV_TIMEOUT = 10

# Perturbation operators: (candidate_index, candidate_type, function, needs_rng)
OPERATORS = [
    (1, "B_arg_swap", B_arg_swap, False),
    (2, "B_negation_drop", C_negation_drop, False),
    (3, "B_scope_flip", B_scope_flip, False),
    (4, "B_restrictor_drop", B_restrictor_drop, False),
    (5, "D_random", D_random_predicates, True),
]


# ═══════════════════════════════════════════════════════════════════════════
# Step 1 — Aligned-subset manifest
# ═══════════════════════════════════════════════════════════════════════════

def _build_broken_gold_set(suites: Dict[str, dict]) -> frozenset:
    """Build the broken-gold premise ID set for criterion 6.

    Per-premise evidence only (not story-level heuristics):
      - Gold FOL fails to parse (syntax error)
      - Gold FOL has free individual variables
    """
    broken_ids: Set[str] = set()

    parse_fail = 0
    fv_count = 0
    for pid, row in suites.items():
        gold = row.get("gold_fol", "")
        if not gold or parse_fol(gold) is None:
            broken_ids.add(pid)
            parse_fail += 1
            continue
        fv = free_individual_variables(gold)
        if fv:
            broken_ids.add(pid)
            fv_count += 1

    logger.info("Broken-gold (per-premise): %d parse failures, %d free-var, "
                "%d total", parse_fail, fv_count, len(broken_ids))

    return frozenset(broken_ids)


def step1_aligned_subset():
    """Generate the aligned-subset manifest."""
    logger.info("Step 1: Building aligned-subset manifest")
    suites = load_test_suites(CACHE_PATH)
    broken_gold = _build_broken_gold_set(suites)

    manifest = []
    for pid, row in sorted(suites.items()):
        gold = row.get("gold_fol", "")
        passes, criteria = passes_aligned_subset_filter(
            row, gold,
            broken_gold_ids=broken_gold,
            jaccard_threshold=JACCARD_THRESHOLD,
            require_full_alignment=True,
        )
        manifest.append({
            "premise_id": pid,
            "passes": passes,
            "criteria": criteria,
            "siv_canonical_fol": row.get("canonical_fol", ""),
            "gold_fol": gold,
        })

    EXP1_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EXP1_DIR / "aligned_subset_manifest.jsonl"
    with open(out_path, "w") as f:
        for entry in manifest:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    n_pass = sum(1 for e in manifest if e["passes"])
    logger.info("Aligned-subset manifest: %d/%d pass (Jaccard threshold=%.1f)",
                n_pass, len(manifest), JACCARD_THRESHOLD)

    if n_pass < 400:
        logger.warning("Yield %d < 400. Consider relaxing Jaccard further.", n_pass)
    elif n_pass > 700:
        logger.warning("Yield %d > 700. Consider tightening filters.", n_pass)
    else:
        logger.info("Yield in acceptable range [400, 700].")

    return manifest


# ═══════════════════════════════════════════════════════════════════════════
# Step 2 — Candidate construction
# ═══════════════════════════════════════════════════════════════════════════

def step2_candidates():
    """Generate candidates via perturbation operators on gold FOL."""
    logger.info("Step 2: Generating candidates")

    manifest_path = EXP1_DIR / "aligned_subset_manifest.jsonl"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Run step 1 first: {manifest_path}")

    manifest = []
    with open(manifest_path) as f:
        for line in f:
            manifest.append(json.loads(line))

    aligned = [e for e in manifest if e["passes"]]
    logger.info("Aligned subset: %d premises", len(aligned))

    rng = random.Random(SEED)
    candidates = []
    dropped = 0

    for entry in aligned:
        pid = entry["premise_id"]
        gold_fol_str = entry["gold_fol"]

        # Parse gold FOL
        gold_expr = parse_fol(gold_fol_str)
        if gold_expr is None:
            logger.warning("Cannot parse gold FOL for %s, skipping", pid)
            dropped += 1
            continue

        # Candidate 0: gold itself
        candidates.append({
            "premise_id": pid,
            "candidate_index": 0,
            "candidate_type": "gold",
            "candidate_fol": gold_fol_str,
            "applicable": True,
            "applicability_reason": None,
        })

        # Apply perturbation operators (indices 1-5)
        tier_b_applicable = 0
        premise_candidates = []

        for cand_idx, cand_type, operator, needs_rng in OPERATORS:
            try:
                if needs_rng:
                    perturbed_expr = operator(gold_expr, rng)
                else:
                    perturbed_expr = operator(gold_expr)
                perturbed_fol = str(perturbed_expr)
                premise_candidates.append({
                    "premise_id": pid,
                    "candidate_index": cand_idx,
                    "candidate_type": cand_type,
                    "candidate_fol": perturbed_fol,
                    "applicable": True,
                    "applicability_reason": None,
                })
                if cand_idx <= 4:  # Tier-B operators
                    tier_b_applicable += 1
            except NotApplicable as e:
                premise_candidates.append({
                    "premise_id": pid,
                    "candidate_index": cand_idx,
                    "candidate_type": cand_type,
                    "candidate_fol": None,
                    "applicable": False,
                    "applicability_reason": str(e),
                })

        # Spec: if fewer than 2 Tier-B operators apply, drop the premise
        if tier_b_applicable < 2:
            for c in premise_candidates:
                c["applicable"] = False
                if c["applicability_reason"] is None:
                    c["applicability_reason"] = "premise dropped: <2 Tier-B operators"
            dropped += 1

        candidates.extend(premise_candidates)

    out_path = EXP1_DIR / "candidates.jsonl"
    with open(out_path, "w") as f:
        for c in candidates:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    # Save run metadata
    applicable_count = sum(1 for c in candidates if c["applicable"])
    unique_premises = len(set(c["premise_id"] for c in candidates if c["applicable"]))
    metadata = {
        "seed": SEED,
        "jaccard_threshold": JACCARD_THRESHOLD,
        "aligned_subset_size": len(aligned),
        "premises_dropped_applicability": dropped,
        "premises_with_candidates": unique_premises,
        "total_candidate_rows": len(candidates),
        "applicable_candidate_rows": applicable_count,
        "git_commit": _git_commit(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with open(EXP1_DIR / "run_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    logger.info("Candidates: %d rows (%d applicable) from %d premises",
                len(candidates), applicable_count, unique_premises)
    return candidates


# ═══════════════════════════════════════════════════════════════════════════
# Step 3 — Smoke test
# ═══════════════════════════════════════════════════════════════════════════

def step3_smoke_test():
    """Pull 30 random premises, score gold vs B_arg_swap with SIV-soft."""
    logger.info("Step 3: Running smoke test")

    cand_path = EXP1_DIR / "candidates.jsonl"
    if not cand_path.exists():
        raise FileNotFoundError(f"Run step 2 first: {cand_path}")

    # Load candidates
    candidates = []
    with open(cand_path) as f:
        for line in f:
            candidates.append(json.loads(line))

    # Find premises with applicable gold + B_arg_swap
    by_premise: Dict[str, Dict[str, dict]] = defaultdict(dict)
    for c in candidates:
        if c["applicable"]:
            by_premise[c["premise_id"]][c["candidate_type"]] = c

    eligible = [
        pid for pid, types in by_premise.items()
        if "gold" in types and "B_arg_swap" in types
    ]

    rng = random.Random(SEED)
    sample = rng.sample(eligible, min(SMOKE_N, len(eligible)))
    logger.info("Smoke test: %d premises sampled (from %d eligible)",
                len(sample), len(eligible))

    suites = load_test_suites(CACHE_PATH)

    results = []
    gold_wins = 0

    for pid in sample:
        row = suites.get(pid)
        if row is None:
            logger.warning("No test suite for %s", pid)
            continue

        gold_fol = by_premise[pid]["gold"]["candidate_fol"]
        swap_fol = by_premise[pid]["B_arg_swap"]["candidate_fol"]

        report_gold = score_siv_soft(row, gold_fol, timeout=SIV_TIMEOUT)
        report_swap = score_siv_soft(row, swap_fol, timeout=SIV_TIMEOUT)

        gold_recall = report_gold.recall if report_gold else None
        swap_recall = report_swap.recall if report_swap else None

        win = (gold_recall is not None and swap_recall is not None
               and gold_recall > swap_recall)
        if win:
            gold_wins += 1

        results.append({
            "premise_id": pid,
            "gold_siv_soft_recall": gold_recall,
            "swap_siv_soft_recall": swap_recall,
            "gold_wins": win,
        })

    rate = gold_wins / len(results) if results else 0
    passed = rate >= 0.80

    smoke = {
        "n_sampled": len(sample),
        "n_scored": len(results),
        "gold_wins": gold_wins,
        "win_rate": round(rate, 4),
        "pass_criterion": 0.80,
        "passed": passed,
        "results": results,
    }

    with open(EXP1_DIR / "smoke_test.json", "w") as f:
        json.dump(smoke, f, indent=2)

    logger.info("Smoke test: %d/%d gold wins (%.1f%%) — %s",
                gold_wins, len(results), rate * 100,
                "PASSED" if passed else "FAILED")

    if not passed:
        logger.error("Smoke test FAILED. Do not proceed to step 4.")
        logger.error("Review smoke_test.json for the 30-row score table.")
    return passed


# ═══════════════════════════════════════════════════════════════════════════
# Step 4 — Score all candidates with all metrics
# ═══════════════════════════════════════════════════════════════════════════

def step4_score_all():
    """Score every applicable (premise, candidate) with all 8 metrics."""
    logger.info("Step 4: Scoring all candidates with all metrics")

    # Check smoke test passed
    smoke_path = EXP1_DIR / "smoke_test.json"
    if smoke_path.exists():
        with open(smoke_path) as f:
            smoke = json.load(f)
        if not smoke.get("passed", False):
            logger.error("Smoke test did not pass. Aborting step 4.")
            return

    cand_path = EXP1_DIR / "candidates.jsonl"
    candidates = []
    with open(cand_path) as f:
        for line in f:
            candidates.append(json.loads(line))

    applicable = [c for c in candidates if c["applicable"]]
    logger.info("Scoring %d applicable candidates", len(applicable))

    suites = load_test_suites(CACHE_PATH)

    # Group by premise for efficient suite reuse
    by_premise: Dict[str, List[dict]] = defaultdict(list)
    for c in applicable:
        by_premise[c["premise_id"]].append(c)

    scored = []
    t0 = time.time()

    for i, (pid, premise_cands) in enumerate(sorted(by_premise.items())):
        row = suites.get(pid)
        if row is None:
            logger.warning("No test suite for %s", pid)
            continue

        gold_fol_str = None
        for c in premise_cands:
            if c["candidate_type"] == "gold":
                gold_fol_str = c["candidate_fol"]
                break

        if gold_fol_str is None:
            logger.warning("No gold candidate for %s", pid)
            continue

        for c in premise_cands:
            cand_fol = c["candidate_fol"]
            if cand_fol is None:
                continue

            metric_scores: Dict[str, Any] = {}
            metric_status: Dict[str, str] = {}

            # Surface metrics (vs gold FOL string)
            bleu = score_bleu(cand_fol, gold_fol_str)
            metric_scores["bleu"] = bleu
            if bleu is None:
                metric_status["bleu"] = "error"

            bs = score_bertscore(cand_fol, gold_fol_str)
            metric_scores["bertscore"] = bs
            if bs is None:
                metric_status["bertscore"] = "error"

            # Reference-based logical metrics
            for name, fn in [
                ("malls_le_raw", score_malls_le_raw),
                ("malls_le_aligned", score_malls_le_aligned),
                ("brunello_lt_raw", score_brunello_lt_raw),
                ("brunello_lt_aligned", score_brunello_lt_aligned),
            ]:
                val = fn(cand_fol, gold_fol_str, timeout=SIV_TIMEOUT)
                metric_scores[name] = val
                if val is None:
                    metric_status[name] = "timeout_or_error"

            # SIV metrics
            siv_strict = score_siv_strict(row, cand_fol, timeout=SIV_TIMEOUT)
            if siv_strict is not None:
                metric_scores["siv_strict_recall"] = siv_strict.recall
                metric_scores["siv_strict_f1"] = siv_strict.f1
                prec_s = siv_strict.precision if siv_strict.precision is not None else 1.0
                metric_scores["siv_strict_min_recall"] = min(siv_strict.recall, prec_s)
            else:
                metric_scores["siv_strict_recall"] = None
                metric_scores["siv_strict_f1"] = None
                metric_scores["siv_strict_min_recall"] = None
                metric_status["siv_strict"] = "error"

            siv_soft = score_siv_soft(row, cand_fol, timeout=SIV_TIMEOUT)
            if siv_soft is not None:
                metric_scores["siv_soft_recall"] = siv_soft.recall
                metric_scores["siv_soft_f1"] = siv_soft.f1
                # min_recall = min(recall, precision) as a conservative composite
                prec = siv_soft.precision if siv_soft.precision is not None else 1.0
                metric_scores["siv_soft_min_recall"] = min(siv_soft.recall, prec)
                metric_scores["siv_soft_per_test_results"] = [
                    {"kind": k, "fol": fol, "verdict": v}
                    for k, fol, v in (siv_soft.per_test_results or [])
                ]
            else:
                metric_scores["siv_soft_recall"] = None
                metric_scores["siv_soft_f1"] = None
                metric_scores["siv_soft_min_recall"] = None
                metric_scores["siv_soft_per_test_results"] = None
                metric_status["siv_soft"] = "error"

            scored.append({
                "premise_id": pid,
                "candidate_index": c["candidate_index"],
                "candidate_type": c["candidate_type"],
                "candidate_fol": cand_fol,
                "scores": metric_scores,
                "metric_status": metric_status if metric_status else None,
            })

        if (i + 1) % 50 == 0:
            elapsed = time.time() - t0
            logger.info("  Scored %d/%d premises (%.0fs elapsed)",
                        i + 1, len(by_premise), elapsed)

    out_path = EXP1_DIR / "scored_candidates.jsonl"
    with open(out_path, "w") as f:
        for s in scored:
            f.write(json.dumps(s, ensure_ascii=False, default=str) + "\n")

    elapsed = time.time() - t0
    logger.info("Scoring complete: %d rows in %.1fs", len(scored), elapsed)

    # Update run_metadata
    meta_path = EXP1_DIR / "run_metadata.json"
    if meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)
    else:
        meta = {}
    meta["scoring_wall_time_s"] = round(elapsed, 1)
    meta["scored_rows"] = len(scored)
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# Step 5 — Primary analysis
# ═══════════════════════════════════════════════════════════════════════════

def step5_analysis():
    """Produce per-tier AUC table, per-operator detection rate, and figure."""
    logger.info("Step 5: Running primary analysis")

    scored_path = EXP1_DIR / "scored_candidates.jsonl"
    if not scored_path.exists():
        raise FileNotFoundError(f"Run step 4 first: {scored_path}")

    scored = []
    with open(scored_path) as f:
        for line in f:
            scored.append(json.loads(line))

    # ── Table 1.5a — Per-tier discrimination AUC ────────────────────────

    # For AUC: binary label is "is_gold" (1 if candidate_type=="gold", 0 otherwise)
    METRIC_KEYS = [
        ("BLEU", "bleu"),
        ("BERTScore", "bertscore"),
        ("MALLS-LE-raw", "malls_le_raw"),
        ("MALLS-LE-aligned", "malls_le_aligned"),
        ("Brunello-LT-raw", "brunello_lt_raw"),
        ("Brunello-LT-aligned", "brunello_lt_aligned"),
        ("SIV-strict (mean recall)", "siv_strict_recall"),
        ("SIV-strict (min recall)", "siv_strict_min_recall"),
        ("SIV-soft (mean recall)", "siv_soft_recall"),
        ("SIV-soft (min recall)", "siv_soft_min_recall"),
    ]

    auc_results = []
    ref_scores_arr = None  # SIV-soft min-recall as reference

    for display_name, key in METRIC_KEYS:
        metric_vals = []
        labels = []
        for s in scored:
            val = s["scores"].get(key)
            if val is None:
                continue
            metric_vals.append(val)
            labels.append(1 if s["candidate_type"] == "gold" else 0)

        if len(set(labels)) < 2 or len(labels) < 10:
            auc_results.append({
                "metric": display_name, "auc": None,
                "ci_lower": None, "ci_upper": None, "p_value": None,
            })
            continue

        metric_arr = np.array(metric_vals)
        label_arr = np.array(labels)
        auc_val = auc_roc(metric_arr, label_arr)

        if key == "siv_soft_min_recall":
            ref_scores_arr = metric_arr
            auc_results.append({
                "metric": display_name, "auc": round(auc_val, 4),
                "ci_lower": None, "ci_upper": None,
                "p_value": "reference",
            })
        else:
            # Bootstrap CI and permutation test vs reference
            if ref_scores_arr is not None and len(metric_arr) == len(ref_scores_arr):
                ci_lo, ci_hi = paired_bootstrap_ci(metric_arr, ref_scores_arr)
                p_val = paired_permutation_p(metric_arr, ref_scores_arr)
            else:
                ci_lo, ci_hi, p_val = None, None, None
            auc_results.append({
                "metric": display_name, "auc": round(auc_val, 4),
                "ci_lower": round(ci_lo, 4) if ci_lo is not None else None,
                "ci_upper": round(ci_hi, 4) if ci_hi is not None else None,
                "p_value": round(p_val, 6) if isinstance(p_val, float) else p_val,
            })

    # Process AUC results: compute CI vs reference now that we have it
    if ref_scores_arr is not None:
        # Re-process non-reference metrics with paired stats
        for i, (display_name, key) in enumerate(METRIC_KEYS):
            if key == "siv_soft_min_recall":
                continue
            if auc_results[i]["auc"] is None:
                continue

            metric_vals = []
            ref_vals = []
            labels = []
            for s in scored:
                val = s["scores"].get(key)
                ref_val = s["scores"].get("siv_soft_min_recall")
                if val is None or ref_val is None:
                    continue
                metric_vals.append(val)
                ref_vals.append(ref_val)
                labels.append(1 if s["candidate_type"] == "gold" else 0)

            if len(metric_vals) >= 10:
                m_arr = np.array(metric_vals)
                r_arr = np.array(ref_vals)
                ci_lo, ci_hi = paired_bootstrap_ci(m_arr, r_arr)
                p_val = paired_permutation_p(m_arr, r_arr)
                auc_results[i]["ci_lower"] = round(ci_lo, 4)
                auc_results[i]["ci_upper"] = round(ci_hi, 4)
                auc_results[i]["p_value"] = round(p_val, 6)

    # Write AUC table
    with open(EXP1_DIR / "per_tier_auc.json", "w") as f:
        json.dump(auc_results, f, indent=2)

    with open(EXP1_DIR / "per_tier_auc.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["metric", "auc", "ci_lower", "ci_upper", "p_value"])
        writer.writeheader()
        writer.writerows(auc_results)

    logger.info("Table 1.5a — Per-tier AUC:")
    for r in auc_results:
        logger.info("  %-30s AUC=%-8s p=%s",
                     r["metric"], r["auc"], r["p_value"])

    # ── Table 1.5b — Per-operator detection rate ────────────────────────

    # Group scored by premise
    by_premise: Dict[str, Dict[str, dict]] = defaultdict(dict)
    for s in scored:
        by_premise[s["premise_id"]][s["candidate_type"]] = s

    OPERATOR_NAMES = ["B_arg_swap", "B_negation_drop", "B_scope_flip",
                      "B_restrictor_drop", "D_random"]
    DETECTION_METRICS = [
        ("BLEU", "bleu"),
        ("BERTScore", "bertscore"),
        ("MALLS-LE-aligned", "malls_le_aligned"),
        ("Brunello-LT-aligned", "brunello_lt_aligned"),
        ("SIV-soft (min recall)", "siv_soft_min_recall"),
    ]

    det_rows = []
    for op_name in OPERATOR_NAMES:
        row_data = {"operator": op_name}
        for metric_display, metric_key in DETECTION_METRICS:
            wins = 0
            total = 0
            for pid, types in by_premise.items():
                if "gold" not in types or op_name not in types:
                    continue
                gold_val = types["gold"]["scores"].get(metric_key)
                pert_val = types[op_name]["scores"].get(metric_key)
                if gold_val is None or pert_val is None:
                    continue
                total += 1
                if gold_val > pert_val:
                    wins += 1
            rate = wins / total if total > 0 else None
            row_data[metric_display] = round(rate, 4) if rate is not None else None
        det_rows.append(row_data)

    with open(EXP1_DIR / "per_operator.json", "w") as f:
        json.dump(det_rows, f, indent=2)

    fieldnames = ["operator"] + [d for d, _ in DETECTION_METRICS]
    with open(EXP1_DIR / "per_operator.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(det_rows)

    logger.info("Table 1.5b — Per-operator detection rate:")
    for r in det_rows:
        logger.info("  %-20s %s",
                     r["operator"],
                     "  ".join(f"{k}={v}" for k, v in r.items() if k != "operator"))

    # ── Figure 1.5c — Score-gap distributions ───────────────────────────

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        FIGURE_METRICS = [
            ("BLEU", "bleu"),
            ("BERTScore", "bertscore"),
            ("MALLS-LE-aligned", "malls_le_aligned"),
            ("SIV-soft (min recall)", "siv_soft_min_recall"),
        ]
        TIER_B_OPS = ["B_arg_swap", "B_negation_drop", "B_scope_flip", "B_restrictor_drop"]

        fig, axes = plt.subplots(1, len(FIGURE_METRICS), figsize=(16, 4), sharey=True)

        for ax, (metric_display, metric_key) in zip(axes, FIGURE_METRICS):
            gaps = []
            for pid, types in by_premise.items():
                if "gold" not in types:
                    continue
                gold_val = types["gold"]["scores"].get(metric_key)
                if gold_val is None:
                    continue
                for op in TIER_B_OPS:
                    if op not in types:
                        continue
                    pert_val = types[op]["scores"].get(metric_key)
                    if pert_val is None:
                        continue
                    gaps.append(gold_val - pert_val)

            if gaps:
                ax.hist(gaps, bins=30, alpha=0.7, edgecolor="black", linewidth=0.5)
                ax.axvline(0, color="red", linestyle="--", linewidth=1)
                mean_gap = np.mean(gaps)
                ax.axvline(mean_gap, color="blue", linestyle="-", linewidth=1, label=f"mean={mean_gap:.3f}")
                ax.legend(fontsize=8)
            ax.set_title(metric_display, fontsize=10)
            ax.set_xlabel("M(gold) − M(perturbation)")

        axes[0].set_ylabel("Count")
        fig.suptitle("Score-gap distributions (Tier-B operators)", fontsize=12)
        fig.tight_layout()
        fig.savefig(EXP1_DIR / "score_gap_distributions.png", dpi=150)
        plt.close(fig)
        logger.info("Figure 1.5c saved to score_gap_distributions.png")
    except ImportError:
        logger.warning("matplotlib not available; skipping figure generation")

    # ── Acceptance check ────────────────────────────────────────────────

    _check_acceptance(auc_results, det_rows)


def _check_acceptance(auc_results: list, det_rows: list):
    """Check if Experiment 1 meets acceptance criteria."""
    logger.info("Step 6: Checking acceptance criteria")

    # Find relevant AUC values
    siv_soft_auc = None
    malls_aligned_auc = None
    brunello_aligned_auc = None
    bleu_auc = None
    bertscore_auc = None

    for r in auc_results:
        if r["metric"] == "SIV-soft (min recall)":
            siv_soft_auc = r["auc"]
        elif r["metric"] == "MALLS-LE-aligned":
            malls_aligned_auc = r["auc"]
        elif r["metric"] == "Brunello-LT-aligned":
            brunello_aligned_auc = r["auc"]
        elif r["metric"] == "BLEU":
            bleu_auc = r["auc"]
        elif r["metric"] == "BERTScore":
            bertscore_auc = r["auc"]

    logger.info("AUC values:")
    logger.info("  SIV-soft (min recall): %s", siv_soft_auc)
    logger.info("  MALLS-LE-aligned:      %s", malls_aligned_auc)
    logger.info("  Brunello-LT-aligned:   %s", brunello_aligned_auc)
    logger.info("  BLEU:                  %s", bleu_auc)
    logger.info("  BERTScore:             %s", bertscore_auc)

    # Check condition (a): SIV tied with or above MALLS/Brunello, crushes BLEU/BERTScore
    # Check condition (b): SIV above all on ≥2 of 4 Tier-B operators
    siv_key = "SIV-soft (min recall)"
    tier_b_ops = ["B_arg_swap", "B_negation_drop", "B_scope_flip", "B_restrictor_drop"]
    siv_above_count = 0

    for op_row in det_rows:
        if op_row["operator"] not in tier_b_ops:
            continue
        siv_val = op_row.get(siv_key)
        others = [op_row.get(k) for k in ["BLEU", "BERTScore", "MALLS-LE-aligned", "Brunello-LT-aligned"]]
        others = [v for v in others if v is not None]
        if siv_val is not None and others and siv_val > max(others):
            siv_above_count += 1

    logger.info("SIV-soft above ALL baselines on %d/4 Tier-B operators", siv_above_count)

    if siv_above_count >= 2:
        logger.info("ACCEPTANCE (b): SIV above all baselines on ≥2 Tier-B operators.")
    else:
        logger.info("Condition (b) not met. Check condition (a) manually from AUC table.")


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(_REPO_ROOT),
            text=True,
        ).strip()
    except Exception:
        return "unknown"


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--step", type=str, default="all",
                    choices=["1", "2", "3", "4", "5", "all"],
                    help="Which step to run (default: all)")
    args = ap.parse_args()

    steps = {
        "1": step1_aligned_subset,
        "2": step2_candidates,
        "3": step3_smoke_test,
        "4": step4_score_all,
        "5": step5_analysis,
    }

    if args.step == "all":
        for step_num in ["1", "2", "3", "4", "5"]:
            result = steps[step_num]()
            # Step 3 returns bool; if smoke test fails, stop
            if step_num == "3" and result is False:
                logger.error("Stopping: smoke test failed.")
                return 1
    else:
        result = steps[args.step]()
        if args.step == "3" and result is False:
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
