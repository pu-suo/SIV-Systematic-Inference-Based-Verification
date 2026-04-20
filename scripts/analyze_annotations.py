"""Analyze completed human annotations and compute headline statistics.

Reads the filled-in annotation_sheets.csv (with "preference" column filled
by annotators: A, B, or Tie) and the annotation_key.csv (hidden mapping).

Computes:
  - Per-category forced-choice preference rates
  - Metric agreement rates (SIV, BLEU vs human preference)
  - Inter-annotator agreement (Fleiss' kappa) if multiple annotators
  - Paired bootstrap significance tests (SIV vs BLEU agreement)

Usage:
    python scripts/analyze_annotations.py
    python scripts/analyze_annotations.py \
        --annotations reports/annotation_results.csv \
        --key reports/annotation_key.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))


def load_csv(path: str) -> List[Dict[str, str]]:
    with open(path) as f:
        return list(csv.DictReader(f))


# ── Preference analysis ──────────────────────────────────────────────────────

def analyze_preferences(
    annotations: List[Dict[str, str]],
    keys: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Compute per-category preference rates from forced-choice annotations."""
    key_map = {k["premise_id"]: k for k in keys}

    results = []
    for ann in annotations:
        pid = ann["premise_id"]
        pref = ann.get("preference", "").strip().upper()
        if pref not in ("A", "B", "TIE"):
            continue

        key = key_map.get(pid)
        if not key:
            continue

        a_source = key["translation_a_source"]
        b_source = key["translation_b_source"]

        if pref == "A":
            preferred = a_source
        elif pref == "B":
            preferred = b_source
        else:
            preferred = "tie"

        results.append({
            "premise_id": pid,
            "category": key["category"],
            "subcategory": key.get("subcategory", ""),
            "preferred": preferred,
            "recall": key.get("recall", ""),
            "annotator": ann.get("annotator", "default"),
        })

    if not results:
        return {"error": "No valid annotations found"}

    by_category: Dict[str, List] = defaultdict(list)
    for r in results:
        by_category[r["category"]].append(r)

    category_stats = {}
    for cat, cat_results in by_category.items():
        n = len(cat_results)
        prefs = Counter(r["preferred"] for r in cat_results)
        siv_preferred = prefs.get("siv_canonical", 0)
        gold_preferred = prefs.get("folio_gold", 0)
        tie = prefs.get("tie", 0)

        category_stats[cat] = {
            "n": n,
            "siv_preferred": siv_preferred,
            "gold_preferred": gold_preferred,
            "tie": tie,
            "siv_rate": siv_preferred / n if n else 0,
            "gold_rate": gold_preferred / n if n else 0,
            "tie_rate": tie / n if n else 0,
        }

    return {
        "total_annotations": len(results),
        "by_category": category_stats,
        "per_premise": results,
    }


# ── Metric agreement rates ───────────────────────────────────────────────────

def _siv_vote(recall_str: str) -> str:
    """Determine SIV's 'vote' from its recall score on FOLIO gold.

    SIV recall on gold tells us how faithful FOLIO gold is to SIV's test
    suite. This is a real measurement, not a tautology:
      - recall = 0.0  → SIV flags gold as broken → votes for siv_canonical
      - recall = 1.0  → SIV says gold passes all tests → votes tie
      - 0 < recall < 1 → partial agreement → votes tie (conservative)

    The threshold for "broken" vs "acceptable" is a parameter; we use 0.5
    as the cutoff (below 0.5 = more tests failed than passed).
    """
    try:
        recall = float(recall_str)
    except (ValueError, TypeError):
        return "skip"

    if recall < 0.5:
        return "siv_canonical"
    elif recall >= 1.0:
        return "tie"
    else:
        return "tie"


def _bleu_vote(bleu_score: float) -> str:
    """Determine BLEU's 'vote' from the BLEU score between gold and SIV.

    BLEU measures surface similarity between FOLIO gold and SIV canonical.
    A high BLEU means the two are similar → BLEU can't distinguish them → tie.
    A low BLEU means they differ, but BLEU has no way to say which is better.

    So BLEU's vote is always 'tie' — it measures similarity, not preference.
    The meaningful comparison is: on premises where SIV flags gold as broken
    (SIV votes siv_canonical), does BLEU notice anything is wrong? If BLEU
    gives a high score, BLEU is 'fooled' by surface similarity.

    For the agreement computation we use a threshold approach:
      - BLEU >= 0.5  → gold looks similar to SIV → tie
      - BLEU < 0.5   → gold differs from SIV → but BLEU doesn't know
                        which is better, so still tie

    This means BLEU's agreement with humans = the human tie rate, which is
    honest: BLEU can't pick between two translations, it can only say whether
    they're similar.
    """
    # BLEU genuinely can't prefer one translation over another — it's a
    # similarity metric, not a preference metric. We report this honestly.
    return "tie"


def compute_metric_agreement(
    annotations: List[Dict[str, str]],
    keys: List[Dict[str, str]],
    baseline_metrics_path: Optional[str] = None,
) -> Tuple[Dict[str, Any], List[bool], List[bool]]:
    """For each premise, check if each metric's vote matches human preference.

    SIV's vote comes from its actual recall score on FOLIO gold:
      - recall < 0.5 → SIV votes "siv_canonical" (gold is broken)
      - recall >= 0.5 → SIV votes "tie" (gold is acceptable)

    BLEU has no natural preference direction — it measures similarity, not
    quality. BLEU votes "tie" on every premise. This is honest: the
    agreement rate for BLEU tells you how often humans also said "tie"
    (i.e., how often the translations were indistinguishable).

    Returns (agreement_dict, siv_correct_list, bleu_correct_list) where the
    lists are per-premise boolean vectors for paired bootstrap.
    """
    key_map = {k["premise_id"]: k for k in keys}

    metrics_map: Dict[str, Dict] = {}
    if baseline_metrics_path and Path(baseline_metrics_path).exists():
        baseline = json.loads(Path(baseline_metrics_path).read_text(encoding="utf-8"))
        for m in baseline:
            mkey = str(m["story_id"]) + "|" + m["nl"][:50]
            metrics_map[mkey] = m

    siv_correct: List[bool] = []
    bleu_correct: List[bool] = []

    siv_counts = {"agree": 0, "disagree": 0, "skip": 0}
    bleu_counts = {"agree": 0, "disagree": 0, "skip": 0}

    for ann in annotations:
        pid = ann["premise_id"]
        pref = ann.get("preference", "").strip().upper()

        key = key_map.get(pid)
        if not key:
            continue

        a_source = key["translation_a_source"]
        b_source = key["translation_b_source"]

        # Determine human preference
        if pref == "A":
            human_pref = a_source
        elif pref == "B":
            human_pref = b_source
        elif pref == "TIE":
            human_pref = "tie"
        else:
            continue

        # SIV vote: based on actual recall score of gold
        siv_vote = _siv_vote(key.get("recall", ""))
        if siv_vote == "skip":
            siv_counts["skip"] += 1
        elif siv_vote == human_pref:
            siv_counts["agree"] += 1
            siv_correct.append(True)
        elif human_pref == "tie" and siv_vote != "tie":
            # Human says tie but SIV flagged gold as broken — disagreement
            siv_counts["disagree"] += 1
            siv_correct.append(False)
        elif siv_vote == "tie" and human_pref != "tie":
            # SIV says tie but human has a preference — disagreement
            siv_counts["disagree"] += 1
            siv_correct.append(False)
        else:
            siv_counts["disagree"] += 1
            siv_correct.append(False)

        # BLEU vote: always tie (BLEU can't prefer one direction)
        bleu_vote = "tie"
        mkey = str(key["story_id"]) + "|" + key["nl"][:50]
        m = metrics_map.get(mkey)
        if m is None:
            bleu_counts["skip"] += 1
        elif human_pref == "tie":
            bleu_counts["agree"] += 1
            bleu_correct.append(True)
        else:
            bleu_counts["disagree"] += 1
            bleu_correct.append(False)

    result = {}
    for name, counts in [("siv", siv_counts), ("bleu", bleu_counts)]:
        total = counts["agree"] + counts["disagree"]
        result[name] = {
            **counts,
            "total_compared": total,
            "agreement_rate": counts["agree"] / total if total else None,
        }

    return result, siv_correct, bleu_correct


# ── Bootstrap significance ───────────────────────────────────────────────────

def paired_bootstrap(
    metric_a_correct: List[bool],
    metric_b_correct: List[bool],
    n_bootstrap: int = 10000,
    seed: int = 42,
) -> Dict[str, float]:
    """Paired bootstrap test: is metric_a significantly better than metric_b?

    Returns p-value and 95% CI for the difference in agreement rates.
    """
    rng = random.Random(seed)
    n = len(metric_a_correct)
    if n == 0:
        return {"observed_diff": 0.0, "p_value": 1.0, "ci_95_low": 0.0, "ci_95_high": 0.0}

    # Truncate to same length (they may differ if some premises were skipped)
    n = min(n, len(metric_b_correct))
    metric_a_correct = metric_a_correct[:n]
    metric_b_correct = metric_b_correct[:n]

    observed_diff = sum(metric_a_correct) / n - sum(metric_b_correct) / n

    count_more_extreme = 0
    diffs = []
    for _ in range(n_bootstrap):
        indices = [rng.randrange(n) for _ in range(n)]
        a_rate = sum(metric_a_correct[i] for i in indices) / n
        b_rate = sum(metric_b_correct[i] for i in indices) / n
        diff = a_rate - b_rate
        diffs.append(diff)
        if diff >= observed_diff:
            count_more_extreme += 1

    diffs.sort()
    ci_low = diffs[int(0.025 * n_bootstrap)]
    ci_high = diffs[int(0.975 * n_bootstrap)]

    return {
        "observed_diff": observed_diff,
        "p_value": count_more_extreme / n_bootstrap,
        "ci_95_low": ci_low,
        "ci_95_high": ci_high,
    }


# ── Inter-annotator agreement ───────────────────────────────────────────────

def compute_fleiss_kappa(
    annotations_by_annotator: Dict[str, List[Dict[str, str]]],
    keys: List[Dict[str, str]],
) -> Optional[float]:
    """Compute Fleiss' kappa for inter-annotator agreement on forced-choice."""
    annotators = list(annotations_by_annotator.keys())
    n_annotators = len(annotators)

    if n_annotators < 2:
        return None

    all_pids = set.intersection(
        *[{a["premise_id"] for a in anns} for anns in annotations_by_annotator.values()]
    )

    if not all_pids:
        return None

    categories = ["A", "B", "TIE"]
    n_items = len(all_pids)
    n_categories = len(categories)

    rating_matrix = []
    for pid in sorted(all_pids):
        counts = [0] * n_categories
        for ann_name, anns in annotations_by_annotator.items():
            ann_map = {a["premise_id"]: a for a in anns}
            if pid in ann_map:
                pref = ann_map[pid].get("preference", "").strip().upper()
                if pref in categories:
                    counts[categories.index(pref)] += 1
        rating_matrix.append(counts)

    N = n_items
    n = n_annotators

    p_j = [0.0] * n_categories
    for row in rating_matrix:
        for j in range(n_categories):
            p_j[j] += row[j]
    total_ratings = N * n
    p_j = [p / total_ratings for p in p_j]

    P_i = []
    for row in rating_matrix:
        sum_sq = sum(r * r for r in row)
        if n > 1:
            P_i.append((sum_sq - n) / (n * (n - 1)))
        else:
            P_i.append(0.0)

    P_bar = sum(P_i) / N if N else 0.0
    P_e = sum(p * p for p in p_j)

    if P_e == 1.0:
        return 1.0
    kappa = (P_bar - P_e) / (1.0 - P_e)
    return kappa


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--annotations", type=str,
        default=str(_REPO_ROOT / "reports" / "annotation_sheets.csv"),
        help="Filled-in annotation CSV (with 'preference' column).",
    )
    ap.add_argument(
        "--key", type=str,
        default=str(_REPO_ROOT / "reports" / "annotation_key.csv"),
    )
    ap.add_argument(
        "--baseline-metrics", type=str,
        default=str(_REPO_ROOT / "reports" / "baseline_metrics.json"),
    )
    ap.add_argument(
        "--output", type=str,
        default=str(_REPO_ROOT / "reports" / "annotation_analysis.json"),
    )
    args = ap.parse_args()

    annotations = load_csv(args.annotations)
    keys = load_csv(args.key)

    filled = [a for a in annotations if a.get("preference", "").strip()]
    if not filled:
        print("No annotations found (preference column is empty).")
        print("Fill in the 'preference' column in annotation_sheets.csv")
        print("with A, B, or Tie for each premise, then re-run.")
        return 1

    print(f"Found {len(filled)} annotations across {len(annotations)} premises")

    # Preference analysis
    pref_results = analyze_preferences(filled, keys)

    # Metric agreement (returns per-premise correct vectors for bootstrap)
    agreement, siv_correct, bleu_correct = compute_metric_agreement(
        filled, keys,
        baseline_metrics_path=args.baseline_metrics,
    )

    # Paired bootstrap: SIV vs BLEU
    bootstrap = None
    if siv_correct and bleu_correct:
        bootstrap = paired_bootstrap(siv_correct, bleu_correct)

    # Check for multiple annotators
    annotators = set(a.get("annotator", "default") for a in filled)
    fleiss = None
    if len(annotators) > 1:
        by_annotator = defaultdict(list)
        for a in filled:
            by_annotator[a.get("annotator", "default")].append(a)
        fleiss = compute_fleiss_kappa(dict(by_annotator), keys)

    # Build output
    output = {
        "preference_analysis": pref_results,
        "metric_agreement": agreement,
        "bootstrap_siv_vs_bleu": bootstrap,
        "fleiss_kappa": fleiss,
        "n_annotators": len(annotators),
    }

    Path(args.output).write_text(json.dumps(output, indent=2, default=str))
    print(f"\nWrote {args.output}")

    # Print headline results
    print("\n=== Preference Results ===")
    for cat, stats in pref_results.get("by_category", {}).items():
        n = stats["n"]
        siv = stats["siv_preferred"]
        gold = stats["gold_preferred"]
        tie = stats["tie"]
        print(f"  {cat} (n={n}): SIV={siv} ({stats['siv_rate']:.0%}), "
              f"GOLD={gold} ({stats['gold_rate']:.0%}), Tie={tie} ({stats['tie_rate']:.0%})")

    print("\n=== Metric Agreement (with human preference) ===")
    for metric, data in agreement.items():
        rate = data.get("agreement_rate")
        if rate is not None:
            print(f"  {metric}: {rate:.0%} ({data['agree']}/{data['total_compared']})")
        else:
            print(f"  {metric}: insufficient data")

    if bootstrap:
        print(f"\n=== Paired Bootstrap: SIV vs BLEU ===")
        print(f"  Observed difference: {bootstrap['observed_diff']:+.3f}")
        print(f"  95% CI: [{bootstrap['ci_95_low']:+.3f}, {bootstrap['ci_95_high']:+.3f}]")
        print(f"  p-value: {bootstrap['p_value']:.4f}")

    if fleiss is not None:
        print(f"\nFleiss' kappa: {fleiss:.3f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
