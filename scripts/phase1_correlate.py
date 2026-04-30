"""Phase 1.3 — Correlation analysis: AUC-ROC, point-biserial, paired bootstrap.

Joins entailment results with metric scores and computes:
  - Primary: AUC-ROC of each metric predicting binary entailment correctness
  - Secondary: Point-biserial correlation (rpb) with bootstrap 95% CIs
  - Significance: Paired bootstrap test (SIV-min-recall vs each competitor)

Usage:
    python scripts/phase1_correlate.py \\
      --entailment-results reports/phase1/entailment_results.jsonl \\
      --metric-scores reports/phase1/metric_scores.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))


# ── Metric columns to analyze ─────────────────────────────────────────────────

METRIC_COLUMNS = [
    "bleu_mean", "bleu_min",
    "bertscore_mean", "bertscore_min",
    "malls_le_raw_mean", "malls_le_aligned_mean",
    "brunello_lt_raw_mean", "brunello_lt_aligned_mean",
    "siv_mean_recall", "siv_min_recall",
    "siv_mean_f1", "siv_min_f1",
]


# ── Statistical functions ──────────────────────────────────────────────────────

def auc_roc(correct: np.ndarray, scores: np.ndarray) -> float:
    """Compute AUC-ROC. Falls back to manual computation if sklearn unavailable."""
    try:
        from sklearn.metrics import roc_auc_score
        return float(roc_auc_score(correct, scores))
    except (ImportError, ValueError):
        # Manual AUC via sorted thresholds
        order = np.argsort(-scores)
        y = correct[order]
        tp = np.cumsum(y)
        fp = np.cumsum(1 - y)
        tpr = tp / tp[-1] if tp[-1] > 0 else tp
        fpr = fp / fp[-1] if fp[-1] > 0 else fp
        return float(np.trapz(tpr, fpr))


def point_biserial(correct: np.ndarray, scores: np.ndarray) -> Tuple[float, float]:
    """Point-biserial correlation between binary correct and continuous scores."""
    from scipy.stats import pointbiserialr
    r, p = pointbiserialr(correct, scores)
    return float(r), float(p)


def bootstrap_ci(
    correct: np.ndarray,
    scores: np.ndarray,
    n_bootstrap: int = 1000,
    alpha: float = 0.05,
    seed: int = 42,
) -> Dict[str, float]:
    """Bootstrap 95% CI for AUC-ROC and rpb."""
    rng = np.random.RandomState(seed)
    n = len(correct)
    auc_samples = []
    rpb_samples = []

    for _ in range(n_bootstrap):
        idx = rng.randint(0, n, size=n)
        c = correct[idx]
        s = scores[idx]
        # Need both classes for AUC
        if c.sum() == 0 or c.sum() == n:
            continue
        auc_samples.append(auc_roc(c, s))
        r, _ = point_biserial(c, s)
        rpb_samples.append(r)

    auc_arr = np.array(auc_samples) if auc_samples else np.array([0.5])
    rpb_arr = np.array(rpb_samples) if rpb_samples else np.array([0.0])

    return {
        "auc_ci_lower": float(np.percentile(auc_arr, 100 * alpha / 2)),
        "auc_ci_upper": float(np.percentile(auc_arr, 100 * (1 - alpha / 2))),
        "rpb_ci_lower": float(np.percentile(rpb_arr, 100 * alpha / 2)),
        "rpb_ci_upper": float(np.percentile(rpb_arr, 100 * (1 - alpha / 2))),
    }


def paired_bootstrap_test(
    correct: np.ndarray,
    scores_a: np.ndarray,
    scores_b: np.ndarray,
    n_bootstrap: int = 1000,
    seed: int = 42,
) -> float:
    """Paired bootstrap test: p-value for AUC(A) > AUC(B)."""
    rng = np.random.RandomState(seed)
    n = len(correct)
    delta_count = 0
    total = 0

    for _ in range(n_bootstrap):
        idx = rng.randint(0, n, size=n)
        c = correct[idx]
        if c.sum() == 0 or c.sum() == n:
            continue
        auc_a = auc_roc(c, scores_a[idx])
        auc_b = auc_roc(c, scores_b[idx])
        if auc_a - auc_b <= 0:
            delta_count += 1
        total += 1

    return delta_count / total if total > 0 else 1.0


# ── Data joining ───────────────────────────────────────────────────────────────

def join_results(
    entailment_path: Path,
    metrics_path: Path,
) -> List[Dict[str, Any]]:
    """Join entailment results with metric scores on (example_id, translator)."""
    ent_map = {}
    for line in entailment_path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        key = (row["example_id"], row["translator"])
        ent_map[key] = row

    joined = []
    for line in metrics_path.read_text().splitlines():
        if not line.strip():
            continue
        m = json.loads(line)
        key = (m["example_id"], m["translator"])
        ent = ent_map.get(key)
        if ent is None:
            continue
        combined = {
            "example_id": m["example_id"],
            "story_id": m["story_id"],
            "translator": m["translator"],
            "correct": 1 if ent["correct"] else 0,
            "timeout": ent.get("timeout_count", 0) > 0,
        }
        for col in METRIC_COLUMNS:
            combined[col] = m.get(col)
        joined.append(combined)

    return joined


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--entailment-results", type=str, required=True)
    ap.add_argument("--metric-scores", type=str, required=True)
    ap.add_argument("--output", type=str,
                    default=str(_REPO_ROOT / "reports" / "phase1" / "correlation_results.json"))
    ap.add_argument("--n-bootstrap", type=int, default=1000)
    args = ap.parse_args()

    # Join data
    joined = join_results(Path(args.entailment_results), Path(args.metric_scores))
    sys.stderr.write(f"[correlate] Joined {len(joined)} rows\n")

    # Exclude timeouts
    no_timeout = [r for r in joined if not r["timeout"]]
    sys.stderr.write(f"[correlate] After timeout exclusion: {len(no_timeout)} rows\n")

    timeout_rate = 1 - len(no_timeout) / len(joined) if joined else 0
    sys.stderr.write(f"[correlate] Timeout rate: {timeout_rate:.3f}\n")

    # Define scopes
    scopes = {
        "all_excluding_gold": [r for r in no_timeout if r["translator"] != "gold"],
        "all_including_gold": no_timeout,
    }
    # Per-translator scopes
    translators = sorted(set(r["translator"] for r in no_timeout))
    for t in translators:
        scopes[f"translator_{t}"] = [r for r in no_timeout if r["translator"] == t]

    results = {
        "n_total": len(joined),
        "n_after_timeout_exclusion": len(no_timeout),
        "timeout_rate": timeout_rate,
        "scopes": {},
    }

    # Reference metric for paired tests
    ref_metric = "siv_min_recall"

    for scope_name, rows in scopes.items():
        correct = np.array([r["correct"] for r in rows], dtype=float)
        n = len(rows)
        n_correct = int(correct.sum())

        sys.stderr.write(f"\n[correlate] Scope: {scope_name} (n={n}, correct={n_correct})\n")

        if n < 10 or n_correct == 0 or n_correct == n:
            sys.stderr.write(f"  Skipping: insufficient variance\n")
            results["scopes"][scope_name] = {"n": n, "skipped": True}
            continue

        scope_results = {"n": n, "n_correct": n_correct, "metrics": {}}

        # Get reference scores for paired test
        ref_scores = np.array([r.get(ref_metric, 0) or 0 for r in rows], dtype=float)

        for metric in METRIC_COLUMNS:
            scores = np.array([r.get(metric, 0) or 0 for r in rows], dtype=float)

            # Skip if all NaN/zero
            if scores.sum() == 0 and not (metric.startswith("malls_le_raw") or metric.startswith("brunello_lt_raw")):
                scope_results["metrics"][metric] = {"skipped": True, "reason": "all_zero"}
                continue

            auc = auc_roc(correct, scores)
            rpb, rpb_p = point_biserial(correct, scores)
            ci = bootstrap_ci(correct, scores, n_bootstrap=args.n_bootstrap)

            entry = {
                "auc_roc": round(auc, 4),
                "rpb": round(rpb, 4),
                "rpb_p_value": round(rpb_p, 6),
                **{k: round(v, 4) for k, v in ci.items()},
            }

            # Paired significance test vs reference
            if metric != ref_metric:
                p_val = paired_bootstrap_test(
                    correct, ref_scores, scores,
                    n_bootstrap=args.n_bootstrap,
                )
                entry["p_vs_siv_min_recall"] = round(p_val, 4)

            scope_results["metrics"][metric] = entry

            sys.stderr.write(
                f"  {metric:30s}  AUC={auc:.4f}  rpb={rpb:.4f}  "
                f"CI=[{ci['rpb_ci_lower']:.4f}, {ci['rpb_ci_upper']:.4f}]\n"
            )

        results["scopes"][scope_name] = scope_results

    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2))
    sys.stderr.write(f"\n[correlate] Wrote {output_path}\n")

    # Also write a CSV summary table
    csv_path = output_path.with_suffix(".csv")
    primary_scope = "all_excluding_gold"
    if primary_scope in results["scopes"] and not results["scopes"][primary_scope].get("skipped"):
        with csv_path.open("w") as f:
            f.write("metric,auc_roc,rpb,rpb_ci_lower,rpb_ci_upper,p_vs_siv_min_recall\n")
            metrics = results["scopes"][primary_scope]["metrics"]
            for metric in METRIC_COLUMNS:
                if metric not in metrics or metrics[metric].get("skipped"):
                    continue
                m = metrics[metric]
                p = m.get("p_vs_siv_min_recall", "---")
                f.write(
                    f"{metric},{m['auc_roc']},{m['rpb']},"
                    f"{m['rpb_ci_lower']},{m['rpb_ci_upper']},{p}\n"
                )
        sys.stderr.write(f"[correlate] Wrote {csv_path}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
