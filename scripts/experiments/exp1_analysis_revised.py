"""Experiment 1 — Revised Step 5 analysis.

Replaces the AUC-based Table 1.5a (which was a setup artifact) with honest
per-operator score distribution analysis. Adds threshold-based detection rates,
box-plot figure, and B_restrictor_drop investigation.

Reads: reports/experiments/exp1/scored_candidates.jsonl (unmodified)
Writes:
  - per_operator_score_distribution.{csv,json}
  - per_operator.{csv,json} (revised detection rates)
  - score_gap_distributions.png (kept, regenerated)
  - score_distributions_by_operator.png (new box-plot)
  - b_restrictor_drop_investigation.jsonl
  - b_restrictor_drop_investigation.md
  - per_tier_auc.deprecated.{csv,json} (moved)

Usage:
    python scripts/experiments/exp1_analysis_revised.py
"""
from __future__ import annotations

import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from scripts.experiments.common import load_test_suites, is_contrastive_eligible

EXP1_DIR = _REPO_ROOT / "reports" / "experiments" / "exp1"
CACHE_PATH = _REPO_ROOT / "reports" / "test_suites" / "test_suites.jsonl"

OPERATORS = ["B_arg_swap", "B_negation_drop", "B_scope_flip", "B_restrictor_drop", "D_random"]

# Metrics to analyze
METRIC_KEYS = {
    "bleu": "bleu",
    "bertscore": "bertscore",
    "malls_le_raw": "malls_le_raw",
    "malls_le_aligned": "malls_le_aligned",
    "brunello_lt_raw": "brunello_lt_raw",
    "brunello_lt_aligned": "brunello_lt_aligned",
    "siv_soft_recall": "siv_soft_recall",
    "siv_soft_f1": "siv_soft_f1",
    "siv_soft_min_recall": "siv_soft_min_recall",
}

# Detection thresholds per metric (perturbation detected if score < threshold)
DETECTION_THRESHOLDS = {
    "bleu": 0.8,
    "bertscore": 0.8,
    "malls_le_raw": 1.0,
    "malls_le_aligned": 1.0,
    "brunello_lt_raw": 1.0,
    "brunello_lt_aligned": 1.0,
    "siv_soft_recall": 0.8,
    "siv_soft_f1": 0.8,
    "siv_soft_min_recall": 0.8,
}

# Continuous metrics for high_score_rate computation
CONTINUOUS_METRICS = {"bleu", "bertscore", "siv_soft_recall", "siv_soft_f1", "siv_soft_min_recall"}
HIGH_SCORE_THRESHOLD = 0.8


def load_scored() -> List[dict]:
    scored = []
    with open(EXP1_DIR / "scored_candidates.jsonl") as f:
        for line in f:
            scored.append(json.loads(line))
    return scored


def _deprecate_old_auc():
    """Move old AUC files to .deprecated."""
    for ext in ["csv", "json"]:
        src = EXP1_DIR / f"per_tier_auc.{ext}"
        dst = EXP1_DIR / f"per_tier_auc.deprecated.{ext}"
        if src.exists():
            os.rename(src, dst)


# ═══════════════════════════════════════════════════════════════════════════
# Part 1 — Per-operator score distribution
# ═══════════════════════════════════════════════════════════════════════════

def part1_score_distribution(scored: List[dict]):
    """Compute per-operator, per-metric score distributions (excluding gold rows)."""
    print("Part 1: Per-operator score distribution")

    # Group perturbation rows by operator
    by_operator: Dict[str, List[dict]] = defaultdict(list)
    for s in scored:
        if s["candidate_type"] != "gold":
            by_operator[s["candidate_type"]].append(s)

    results = []
    for op in OPERATORS:
        rows = by_operator.get(op, [])
        if not rows:
            results.append({"operator": op, "metrics": {}})
            continue

        metrics_data = {}
        for metric_name, metric_key in METRIC_KEYS.items():
            vals = [r["scores"].get(metric_key) for r in rows]
            vals = [v for v in vals if v is not None]
            n = len(vals)

            if n == 0:
                metrics_data[metric_name] = {
                    "n": 0, "mean": None, "median": None,
                    "p25": None, "p75": None, "high_score_rate": None,
                }
                continue

            arr = np.array(vals)
            entry = {
                "n": n,
                "mean": round(float(arr.mean()), 4),
                "median": round(float(np.median(arr)), 4),
                "p25": round(float(np.percentile(arr, 25)), 4),
                "p75": round(float(np.percentile(arr, 75)), 4),
            }
            if metric_name in CONTINUOUS_METRICS:
                entry["high_score_rate"] = round(float((arr >= HIGH_SCORE_THRESHOLD).mean()), 4)
            else:
                entry["high_score_rate"] = None

            metrics_data[metric_name] = entry

        results.append({"operator": op, "metrics": metrics_data})

    # Write JSON
    with open(EXP1_DIR / "per_operator_score_distribution.json", "w") as f:
        json.dump(results, f, indent=2)

    # Write CSV (flattened)
    csv_rows = []
    for r in results:
        for metric_name, data in r["metrics"].items():
            csv_rows.append({
                "operator": r["operator"],
                "metric": metric_name,
                **(data if data else {}),
            })

    if csv_rows:
        fieldnames = ["operator", "metric", "n", "mean", "median", "p25", "p75", "high_score_rate"]
        with open(EXP1_DIR / "per_operator_score_distribution.csv", "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(csv_rows)

    # Print summary
    print("\n  High-score rate (>= 0.8) — fraction of perturbations that 'look correct':")
    print(f"  {'Operator':<20s} {'BLEU':<8s} {'BERTSc':<8s} {'SIV-rec':<8s} {'SIV-F1':<8s}")
    for r in results:
        m = r["metrics"]
        bleu_hsr = m.get("bleu", {}).get("high_score_rate")
        bert_hsr = m.get("bertscore", {}).get("high_score_rate")
        siv_r_hsr = m.get("siv_soft_recall", {}).get("high_score_rate")
        siv_f1_hsr = m.get("siv_soft_f1", {}).get("high_score_rate")
        print(f"  {r['operator']:<20s} "
              f"{_fmt(bleu_hsr):<8s} {_fmt(bert_hsr):<8s} "
              f"{_fmt(siv_r_hsr):<8s} {_fmt(siv_f1_hsr):<8s}")

    return results


# ═══════════════════════════════════════════════════════════════════════════
# Part 2 — Threshold-based detection rates
# ═══════════════════════════════════════════════════════════════════════════

def part2_detection_rates(scored: List[dict]):
    """Detection rate = fraction of perturbations where M(perturbation) < threshold."""
    print("\nPart 2: Threshold-based detection rates")

    by_operator: Dict[str, List[dict]] = defaultdict(list)
    for s in scored:
        if s["candidate_type"] != "gold":
            by_operator[s["candidate_type"]].append(s)

    det_rows = []
    for op in OPERATORS:
        rows = by_operator.get(op, [])
        row_data: Dict[str, Any] = {"operator": op}

        for metric_name, metric_key in METRIC_KEYS.items():
            threshold = DETECTION_THRESHOLDS[metric_name]
            vals = [r["scores"].get(metric_key) for r in rows]
            vals = [v for v in vals if v is not None]
            n = len(vals)

            if n == 0:
                row_data[metric_name] = None
                continue

            detected = sum(1 for v in vals if v < threshold)
            row_data[metric_name] = round(detected / n, 4)

        row_data["n"] = len(rows)
        det_rows.append(row_data)

    # Write JSON
    with open(EXP1_DIR / "per_operator.json", "w") as f:
        json.dump(det_rows, f, indent=2)

    # Write CSV
    fieldnames = ["operator", "n"] + list(METRIC_KEYS.keys())
    with open(EXP1_DIR / "per_operator.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(det_rows)

    # Print summary
    print(f"\n  Detection rates (M < threshold):")
    print(f"  {'Operator':<20s} {'n':<5s} {'BLEU':<8s} {'BERTSc':<8s} "
          f"{'MALLS-a':<8s} {'Brun-a':<8s} {'SIV-rec':<8s} {'SIV-F1':<8s}")
    for r in det_rows:
        print(f"  {r['operator']:<20s} {r.get('n',''):<5} "
              f"{_fmt(r.get('bleu')):<8s} {_fmt(r.get('bertscore')):<8s} "
              f"{_fmt(r.get('malls_le_aligned')):<8s} {_fmt(r.get('brunello_lt_aligned')):<8s} "
              f"{_fmt(r.get('siv_soft_recall')):<8s} {_fmt(r.get('siv_soft_f1')):<8s}")

    return det_rows


# ═══════════════════════════════════════════════════════════════════════════
# Part 3 — Figures
# ═══════════════════════════════════════════════════════════════════════════

def part3_figures(scored: List[dict]):
    """Generate score-gap and box-plot figures."""
    print("\nPart 3: Generating figures")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  matplotlib not available; skipping figures")
        return

    # Group by premise and type
    by_premise: Dict[str, Dict[str, dict]] = defaultdict(dict)
    for s in scored:
        by_premise[s["premise_id"]][s["candidate_type"]] = s

    # ── Figure A: Score-gap distributions (revised, kept from original) ──

    FIGURE_METRICS = [
        ("BLEU", "bleu"),
        ("BERTScore", "bertscore"),
        ("MALLS-LE-aligned", "malls_le_aligned"),
        ("SIV-soft (recall)", "siv_soft_recall"),
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
            ax.axvline(mean_gap, color="blue", linestyle="-", linewidth=1,
                       label=f"mean={mean_gap:.3f}")
            ax.legend(fontsize=8)
        ax.set_title(metric_display, fontsize=10)
        ax.set_xlabel("M(gold) − M(perturbation)")
    axes[0].set_ylabel("Count")
    fig.suptitle("Score-gap distributions (Tier-B operators)", fontsize=12)
    fig.tight_layout()
    fig.savefig(EXP1_DIR / "score_gap_distributions.png", dpi=150)
    plt.close(fig)
    print("  Saved score_gap_distributions.png")

    # ── Figure B: Box-plots of absolute perturbation scores by operator ──

    BOX_METRICS = [
        ("BLEU", "bleu"),
        ("BERTScore", "bertscore"),
        ("MALLS-LE-aligned", "malls_le_aligned"),
        ("SIV-soft (recall)", "siv_soft_recall"),
        ("SIV-soft (F1)", "siv_soft_f1"),
    ]

    fig, axes = plt.subplots(1, len(BOX_METRICS), figsize=(18, 5), sharey=True)

    for ax, (metric_display, metric_key) in zip(axes, BOX_METRICS):
        data_by_op = []
        labels = []
        for op in OPERATORS:
            vals = []
            for s in scored:
                if s["candidate_type"] == op:
                    v = s["scores"].get(metric_key)
                    if v is not None:
                        vals.append(v)
            if vals:
                data_by_op.append(vals)
                labels.append(op.replace("B_", "").replace("D_", ""))

        if data_by_op:
            bp = ax.boxplot(data_by_op, labels=labels, patch_artist=True)
            for patch in bp["boxes"]:
                patch.set_facecolor("lightblue")
            ax.axhline(0.8, color="red", linestyle="--", linewidth=0.8, alpha=0.7)
            ax.set_ylim(-0.05, 1.05)
        ax.set_title(metric_display, fontsize=10)
        ax.tick_params(axis="x", rotation=45)

    axes[0].set_ylabel("Score on perturbation")
    fig.suptitle("Perturbation scores by operator (red line = 0.8 threshold)", fontsize=12)
    fig.tight_layout()
    fig.savefig(EXP1_DIR / "score_distributions_by_operator.png", dpi=150)
    plt.close(fig)
    print("  Saved score_distributions_by_operator.png")


# ═══════════════════════════════════════════════════════════════════════════
# Part 4 — B_restrictor_drop investigation
# ═══════════════════════════════════════════════════════════════════════════

def part4_restrictor_investigation(scored: List[dict]):
    """Deep investigation of B_restrictor_drop 0% detection."""
    print("\nPart 4: B_restrictor_drop investigation")

    suites = load_test_suites(CACHE_PATH)

    # Find all B_restrictor_drop rows
    restrictor_rows = [s for s in scored if s["candidate_type"] == "B_restrictor_drop"]
    print(f"  B_restrictor_drop rows: {len(restrictor_rows)}")

    investigation = []
    for s in restrictor_rows:
        pid = s["premise_id"]
        row = suites.get(pid, {})

        entry = {
            "premise_id": pid,
            "canonical_fol": row.get("canonical_fol", ""),
            "perturbed_fol": s["candidate_fol"],
            "siv_soft_recall": s["scores"].get("siv_soft_recall"),
            "siv_soft_precision": s["scores"].get("siv_soft_f1"),  # Need to derive
            "siv_soft_f1": s["scores"].get("siv_soft_f1"),
            "n_positives_in_test_suite": len(row.get("positives", [])),
            "n_contrastives_in_test_suite": len(row.get("contrastives", [])),
            "is_contrastive_eligible": is_contrastive_eligible(row),
        }

        # Get actual precision from per_test_results if available
        ptr = s["scores"].get("siv_soft_per_test_results")
        if ptr:
            contrastive_tests = [t for t in ptr if t["kind"] == "contrastive"]
            if contrastive_tests:
                rejected = sum(1 for t in contrastive_tests if t["verdict"] != "entailed")
                entry["siv_soft_precision"] = round(rejected / len(contrastive_tests), 4)
                # Recompute F1
                rec = entry["siv_soft_recall"] or 0
                prec = entry["siv_soft_precision"]
                if rec + prec > 0:
                    entry["siv_soft_f1_recomputed"] = round(2 * rec * prec / (rec + prec), 4)
                else:
                    entry["siv_soft_f1_recomputed"] = 0.0
            else:
                entry["siv_soft_precision"] = None
                entry["siv_soft_f1_recomputed"] = None
        else:
            entry["siv_soft_f1_recomputed"] = None

        investigation.append(entry)

    # Write JSONL
    with open(EXP1_DIR / "b_restrictor_drop_investigation.jsonl", "w") as f:
        for entry in investigation:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # Analyze buckets
    eligible = [e for e in investigation if e["is_contrastive_eligible"]]
    not_eligible = [e for e in investigation if not e["is_contrastive_eligible"]]

    # For eligible: does precision drop?
    prec_catches = 0
    prec_misses = 0
    for e in eligible:
        prec = e.get("siv_soft_precision")
        if prec is not None and prec < 1.0:
            prec_catches += 1
        else:
            prec_misses += 1

    # For not-eligible: is recall=1.0 expected?
    recall_one = sum(1 for e in not_eligible if e["siv_soft_recall"] == 1.0)
    recall_zero = sum(1 for e in not_eligible if e["siv_soft_recall"] == 0.0)

    # Summary
    lines = [
        "# B_restrictor_drop Investigation",
        "",
        f"Total B_restrictor_drop candidates scored: {len(investigation)}",
        f"Contrastive-eligible: {len(eligible)}",
        f"Not contrastive-eligible: {len(not_eligible)}",
        "",
        "## Contrastive-eligible premises",
        "",
    ]

    if eligible:
        lines.append(f"Of {len(eligible)} contrastive-eligible premises:")
        lines.append(f"- Precision < 1.0 (contrastives caught weakening): {prec_catches}")
        lines.append(f"- Precision = 1.0 (contrastives did NOT catch): {prec_misses}")
        lines.append("")

        if prec_catches > 0:
            lines.append("Examples where contrastives caught the weakening:")
            for e in eligible:
                prec = e.get("siv_soft_precision")
                if prec is not None and prec < 1.0:
                    lines.append(f"  - {e['premise_id']}: precision={prec:.3f}, "
                                 f"recall={e['siv_soft_recall']:.3f}, "
                                 f"F1={e.get('siv_soft_f1_recomputed', 'N/A')}")
            lines.append("")
    else:
        lines.append("No contrastive-eligible premises in this set.")
        lines.append("")

    lines.extend([
        "## Non-contrastive-eligible premises",
        "",
        f"Of {len(not_eligible)} non-eligible premises:",
        f"- recall = 1.0: {recall_one} (perturbation satisfies all positive probes — structural limitation)",
        f"- recall = 0.0: {recall_zero} (alignment failure — separate issue)",
        f"- other recall: {len(not_eligible) - recall_one - recall_zero}",
        "",
        "## Classification",
        "",
    ])

    # Determine which bucket applies
    if prec_catches > len(eligible) * 0.3:
        bucket = "a"
        lines.append(f"**Bucket (a)**: Contrastives catch some/many ({prec_catches}/{len(eligible)}).")
        lines.append("Use F1 as the SIV headline for this operator, not min_recall.")
    elif len(eligible) < len(investigation) * 0.3:
        bucket = "b"
        lines.append(f"**Bucket (b)**: Contrastives are mostly empty for these premises "
                     f"({len(not_eligible)}/{len(investigation)} non-eligible).")
        lines.append("SIV cannot detect overweak when contrastive coverage is thin.")
        lines.append("This is a real limitation. The paper's limitations section acknowledges:")
        lines.append(f"  'Overweak detection requires contrastive eligibility "
                     f"(corpus rate: ~82.3%).'")
        lines.append("Experiment 2 (graded correctness) addresses this gap directly.")
    else:
        bucket = "c"
        lines.append(f"**Bucket (c)**: Contrastives exist but don't fire.")
        lines.append("Investigate further: possible blind spot in contrastive generation for "
                     "restrictor-drop patterns.")

    lines.extend([
        "",
        "## Recommendation",
        "",
    ])

    if bucket == "a":
        lines.append("Re-report Part 2 detection table using SIV-soft F1 for B_restrictor_drop.")
    elif bucket == "b":
        lines.append("Report B_restrictor_drop as a known limitation (overweak without contrastives).")
        lines.append("Do NOT report an inflated detection number. Report recall=1.0 honestly with")
        lines.append("the caveat that this reflects structural coverage, not metric failure.")
    else:
        lines.append("Investigate contrastive scoring path before reporting any B_restrictor_drop number.")

    with open(EXP1_DIR / "b_restrictor_drop_investigation.md", "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"  Eligible: {len(eligible)}, catches: {prec_catches}, misses: {prec_misses}")
    print(f"  Non-eligible: {len(not_eligible)}, recall=1.0: {recall_one}")
    print(f"  Classification: Bucket ({bucket})")

    return bucket


# ═══════════════════════════════════════════════════════════════════════════
# Part 5 — Revise run_metadata.json
# ═══════════════════════════════════════════════════════════════════════════

def part5_metadata(bucket: str):
    """Update run_metadata.json with revised analysis notes."""
    print("\nPart 5: Updating run_metadata.json")

    meta_path = EXP1_DIR / "run_metadata.json"
    with open(meta_path) as f:
        meta = json.load(f)

    meta["deviations"] = [
        "Jaccard threshold relaxed from 0.6 to 0.5 (spec section 1.1 acceptance clause)",
        "Full predicate-alignment requirement added after smoke test investigation "
        "(yield 368, below spec 400-700 range)",
        "Broken-gold criterion 6 uses per-premise evidence only "
        "(parse failure or free-variable gold), not story-level heuristic",
        "B_scope_flip N=1 (only 1 premise in aligned subset has nested mixed quantifiers)",
    ]

    meta["analysis_notes"] = [
        "Table 1.5a AUC analysis discarded as setup artifact: gold included in candidate "
        "set as reference, so all reference-based metrics trivially achieve AUC=1.0 "
        "against themselves.",
        "Replaced with per-operator score-distribution analysis (per_operator_score_distribution.json) "
        "which shows how each metric scores perturbations directly.",
        "Detection rates use symmetric thresholds: 0.8 for continuous metrics, 1.0 for "
        "binary equivalence metrics.",
        f"B_restrictor_drop classified as bucket ({bucket}). "
        + ("Contrastives catch weakening — use F1." if bucket == "a"
           else "Overweak detection requires contrastive coverage — documented limitation."
           if bucket == "b"
           else "Further investigation needed."),
    ]

    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print("  Updated run_metadata.json")


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _fmt(v) -> str:
    if v is None:
        return "—"
    return f"{v:.3f}"


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("Experiment 1 — Revised Step 5 Analysis")
    print("=" * 60)

    # Deprecate old AUC files
    _deprecate_old_auc()

    # Load scored data
    scored = load_scored()
    print(f"\nLoaded {len(scored)} scored rows")

    # Run all parts
    part1_score_distribution(scored)
    part2_detection_rates(scored)
    part3_figures(scored)
    bucket = part4_restrictor_investigation(scored)
    part5_metadata(bucket)

    print("\n" + "=" * 60)
    print("Analysis complete. All outputs in reports/experiments/exp1/")
    print("=" * 60)


if __name__ == "__main__":
    main()
