"""Phase 1.5 — Qualitative failure analysis: categorize metric disagreements.

Examines cases where metrics disagree with entailment correctness:
  1. SIV right, others wrong — SIV captures structural correctness
  2. SIV wrong, others right — SIV failure modes
  3. SIV high but entailment fails — SIV false positives
  4. All metrics low, entailment fails — common failure cases

Usage:
    python scripts/phase1_failure_analysis.py \\
      --entailment-results reports/phase1/entailment_results.jsonl \\
      --metric-scores reports/phase1/metric_scores.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))


def join_data(
    entailment_path: Path,
    metrics_path: Path,
) -> List[Dict[str, Any]]:
    """Join entailment results with metric scores."""
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
        combined = {**m, **ent}
        joined.append(combined)

    return joined


def categorize(rows: List[Dict[str, Any]], max_per_bucket: int = 10) -> Dict[str, Any]:
    """Categorize examples into disagreement buckets."""

    def _siv_score(r):
        return r.get("siv_mean_recall") or 0

    def _bleu_score(r):
        return r.get("bleu_mean") or 0

    def _bertscore_score(r):
        return r.get("bertscore_mean") or 0

    # Exclude gold translator
    model_rows = [r for r in rows if r["translator"] != "gold"]

    # Thresholds for "high" vs "low"
    siv_threshold = 0.5
    surface_threshold = 0.3

    buckets = {
        "siv_right_others_wrong": [],
        "siv_wrong_others_right": [],
        "siv_high_entailment_fails": [],
        "all_low_entailment_fails": [],
    }

    for r in model_rows:
        correct = r.get("correct", False)
        siv = _siv_score(r)
        bleu = _bleu_score(r)
        bert = _bertscore_score(r)

        # SIV right, others wrong: high SIV, correct entailment, low BLEU/BERTScore
        if correct and siv >= siv_threshold and bleu < surface_threshold:
            buckets["siv_right_others_wrong"].append(r)

        # SIV wrong, others right: low SIV, correct entailment, high surface metrics
        if correct and siv < siv_threshold and (bleu >= surface_threshold or bert >= 0.8):
            buckets["siv_wrong_others_right"].append(r)

        # SIV high but entailment fails (false positive)
        if not correct and siv >= siv_threshold:
            buckets["siv_high_entailment_fails"].append(r)

        # All low, entailment fails
        if not correct and siv < siv_threshold and bleu < surface_threshold:
            buckets["all_low_entailment_fails"].append(r)

    # Format output: take top N per bucket, extract key info
    output = {}
    for bucket_name, items in buckets.items():
        # Sort by interestingness (SIV score descending for false positives, etc.)
        if bucket_name == "siv_high_entailment_fails":
            items.sort(key=lambda r: -_siv_score(r))
        elif bucket_name == "siv_wrong_others_right":
            items.sort(key=lambda r: _siv_score(r))
        else:
            items.sort(key=lambda r: -_siv_score(r))

        selected = items[:max_per_bucket]
        formatted = []
        for r in selected:
            entry = {
                "story_id": r.get("story_id"),
                "example_id": r.get("example_id"),
                "translator": r.get("translator"),
                "correct": r.get("correct"),
                "verdict": r.get("verdict"),
                "gold_label": r.get("gold_label"),
                "siv_mean_recall": r.get("siv_mean_recall"),
                "siv_min_recall": r.get("siv_min_recall"),
                "bleu_mean": r.get("bleu_mean"),
                "bertscore_mean": r.get("bertscore_mean"),
                "malls_le_aligned_mean": r.get("malls_le_aligned_mean"),
                "n_premises": r.get("n_premises"),
            }
            # Include per-premise breakdown if available
            per_premise = r.get("per_premise_scores", [])
            if per_premise:
                entry["premise_summary"] = [
                    {
                        "idx": p.get("premise_idx"),
                        "siv_recall": p.get("siv_recall"),
                        "bleu": p.get("bleu"),
                    }
                    for p in per_premise[:6]  # Truncate for readability
                ]
            formatted.append(entry)

        output[bucket_name] = {
            "total_in_bucket": len(items),
            "shown": len(formatted),
            "examples": formatted,
        }

    return output


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--entailment-results", type=str, required=True)
    ap.add_argument("--metric-scores", type=str, required=True)
    ap.add_argument("--output", type=str,
                    default=str(_REPO_ROOT / "reports" / "phase1" / "failure_analysis.json"))
    ap.add_argument("--max-per-bucket", type=int, default=10)
    args = ap.parse_args()

    joined = join_data(Path(args.entailment_results), Path(args.metric_scores))
    sys.stderr.write(f"[failure] Joined {len(joined)} rows\n")

    results = categorize(joined, max_per_bucket=args.max_per_bucket)

    # Summary
    sys.stderr.write("[failure] Bucket sizes:\n")
    for name, info in results.items():
        sys.stderr.write(f"  {name}: {info['total_in_bucket']} examples\n")

    # Write
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2))
    sys.stderr.write(f"[failure] Wrote {output_path}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
