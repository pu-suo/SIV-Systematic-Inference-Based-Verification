"""Generate the metric disagreement analysis for Tier 3 (redesigned).

Instead of contrived monolithic candidates, this script identifies natural
cases in the FOLIO evaluation where SIV and BLEU disagree — cases where
BLEU says "this is a decent translation" but SIV says "this misses critical
structure." Cross-references with the categorization to separate genuine
structural catches from vocabulary divergence.

Produces worked examples for the paper's qualitative section (Figure 2 /
Table 3).

Usage:
    python scripts/generate_metric_disagreement.py
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))


def load_categorization(path: str) -> Dict[str, Dict[str, str]]:
    """Load categorization indexed by story_id + nl prefix."""
    cats = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            key = row["story_id"] + "|" + row["nl"][:50]
            cats[key] = row
    return cats


def load_baseline_metrics(path: str) -> List[Dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data


def main() -> int:
    metrics_path = _REPO_ROOT / "reports" / "baseline_metrics.json"
    cat_path = _REPO_ROOT / "reports" / "folio_categorization.csv"
    output_path = _REPO_ROOT / "reports" / "metric_disagreement.json"

    if not metrics_path.exists():
        print("Run compute_baseline_metrics.py first.", file=sys.stderr)
        return 1
    if not cat_path.exists():
        print("Run categorize_folio_results.py first.", file=sys.stderr)
        return 1

    metrics = load_baseline_metrics(str(metrics_path))
    cats = load_categorization(str(cat_path))

    # ── Build disagreement cases ──

    # Case A: SIV=0, BLEU high → "BLEU says good, SIV says bad"
    siv_zero_bleu_high = []
    for m in metrics:
        if m["siv_recall"] is None or m["siv_recall"] > 0.0:
            continue
        if m["bleu"] < 0.25:
            continue
        key = str(m["story_id"]) + "|" + m["nl"][:50]
        cat_row = cats.get(key, {})
        category = cat_row.get("category", "unknown")
        m_enriched = {
            **m,
            "category": category,
            "subcategory": cat_row.get("subcategory", ""),
            "disagreement_type": "bleu_high_siv_zero",
        }
        siv_zero_bleu_high.append(m_enriched)

    siv_zero_bleu_high.sort(key=lambda x: -x["bleu"])

    # Case B: SIV=1.0, BLEU low → "SIV says perfect, BLEU says bad"
    # (these show BLEU's vocabulary sensitivity)
    siv_perfect_bleu_low = []
    for m in metrics:
        if m["siv_recall"] is None or m["siv_recall"] < 1.0:
            continue
        if m["bleu"] > 0.5:
            continue
        key = str(m["story_id"]) + "|" + m["nl"][:50]
        cat_row = cats.get(key, {})
        m_enriched = {
            **m,
            "category": cat_row.get("category", "unknown"),
            "subcategory": cat_row.get("subcategory", ""),
            "disagreement_type": "siv_perfect_bleu_low",
        }
        siv_perfect_bleu_low.append(m_enriched)

    siv_perfect_bleu_low.sort(key=lambda x: x["bleu"])

    # ── Build report ──

    structural_cats = ["restrictor_collapse", "entity_flattening", "quantifier_mismatch"]

    report = {
        "summary": {
            "total_scored_premises": len(metrics),
            "siv_zero_bleu_above_0.25": len(siv_zero_bleu_high),
            "siv_zero_bleu_above_0.50": len([x for x in siv_zero_bleu_high if x["bleu"] > 0.5]),
            "structural_catches_with_high_bleu": len(
                [x for x in siv_zero_bleu_high if x["category"] in structural_cats]
            ),
            "siv_perfect_bleu_below_0.50": len(siv_perfect_bleu_low),
        },
        "headline_cases": {
            "description": (
                "Cases where SIV catches a structural error (restrictor collapse, "
                "entity flattening, or quantifier mismatch) but BLEU scores the "
                "FOLIO gold translation above 0.25. These are the 'SIV is right, "
                "BLEU is wrong' cases for the paper."
            ),
            "cases": [
                x for x in siv_zero_bleu_high if x["category"] in structural_cats
            ],
        },
        "bleu_high_siv_zero_by_category": {},
        "siv_perfect_bleu_low": siv_perfect_bleu_low[:10],
    }

    # Group case A by category
    from collections import Counter
    cat_groups = {}
    for x in siv_zero_bleu_high:
        cat = x["category"]
        if cat not in cat_groups:
            cat_groups[cat] = []
        cat_groups[cat].append(x)

    report["bleu_high_siv_zero_by_category"] = {
        cat: {
            "count": len(cases),
            "mean_bleu": sum(c["bleu"] for c in cases) / len(cases),
            "examples": cases[:3],
        }
        for cat, cases in sorted(cat_groups.items(), key=lambda x: -len(x[1]))
    }

    # Write report
    output_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"Wrote {output_path}")

    # Print summary
    print(f"\n=== Metric Disagreement Summary ===")
    s = report["summary"]
    print(f"Total scored premises: {s['total_scored_premises']}")
    print(f"SIV=0 + BLEU>0.25: {s['siv_zero_bleu_above_0.25']}")
    print(f"SIV=0 + BLEU>0.50: {s['siv_zero_bleu_above_0.50']}")
    print(f"Structural catches with high BLEU: {s['structural_catches_with_high_bleu']}")
    print(f"SIV=1.0 + BLEU<0.50: {s['siv_perfect_bleu_below_0.50']}")

    print(f"\n=== By category (SIV=0, BLEU>0.25) ===")
    for cat, info in report["bleu_high_siv_zero_by_category"].items():
        print(f"  {cat}: {info['count']} (mean BLEU={info['mean_bleu']:.3f})")

    print(f"\n=== Headline cases (structural catches, BLEU>0.25) ===")
    for case in report["headline_cases"]["cases"]:
        print(f"  Story {case['story_id']}: BLEU={case['bleu']:.3f}, category={case['category']}")
        print(f"    NL: {case['nl'][:80]}")
        print(f"    GOLD: {case['folio_gold_fol'][:80]}")
        print(f"    SIV:  {case['siv_canonical_fol'][:80]}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
