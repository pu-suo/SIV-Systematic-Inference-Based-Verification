"""Generate blinded forced-choice annotation sheets for Tier 1 human study.

Selects premises from the categorization output, creates randomized A/B pairs
(FOLIO gold vs SIV canonical), and outputs two files:
  - annotation_sheets.csv: what annotators see (blinded)
  - annotation_key.csv: hidden mapping for analysis

Usage:
    python scripts/generate_annotation_set.py
    python scripts/generate_annotation_set.py \
        --categorization reports/folio_categorization.csv \
        --n-vocab-divergence 20 --n-calibration 10
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path
from typing import Any, Dict, List

_REPO_ROOT = Path(__file__).parent.parent


def load_categorization(path: str) -> List[Dict[str, str]]:
    with open(path) as f:
        return list(csv.DictReader(f))


def select_annotation_set(
    rows: List[Dict[str, str]],
    n_vocab_divergence: int = 20,
    n_calibration: int = 10,
    seed: int = 42,
) -> List[Dict[str, Any]]:
    """Select premises for annotation from categorization output.

    Selection strategy:
    - ALL restrictor_collapse cases (headline)
    - ALL entity_flattening cases (secondary)
    - ALL quantifier_mismatch cases (tertiary)
    - n_vocab_divergence from vocab_divergence_total (honest limitation)
    - n_calibration from perfect_agreement (calibration anchors)
    """
    rng = random.Random(seed)

    structural_cats = ["restrictor_collapse", "entity_flattening", "quantifier_mismatch"]
    selected = []

    # All structural catch cases
    for row in rows:
        if row["category"] in structural_cats:
            selected.append({
                **row,
                "selection_reason": f"structural_catch ({row['category']})",
            })

    # Sample vocab_divergence_total
    vocab_total = [r for r in rows if r["category"] == "vocab_divergence_total"]
    rng.shuffle(vocab_total)
    for row in vocab_total[:n_vocab_divergence]:
        selected.append({
            **row,
            "selection_reason": "vocab_divergence_sample",
        })

    # Sample perfect_agreement (calibration)
    perfect = [r for r in rows if r["category"] == "perfect_agreement"]
    rng.shuffle(perfect)
    for row in perfect[:n_calibration]:
        selected.append({
            **row,
            "selection_reason": "calibration_anchor",
        })

    return selected


def generate_sheets(
    selected: List[Dict[str, Any]],
    seed: int = 42,
) -> tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """Generate blinded annotation sheets and the corresponding key.

    For each premise, randomly assigns FOLIO gold and SIV canonical to
    "Translation A" and "Translation B".
    """
    rng = random.Random(seed)

    sheets = []
    keys = []

    for i, row in enumerate(selected):
        premise_id = f"P{i+1:03d}"
        nl = row["nl"]
        gold_fol = row.get("folio_gold_fol", "")
        siv_fol = row.get("siv_canonical_fol", "")

        # Randomly assign A/B
        if rng.random() < 0.5:
            trans_a, trans_b = gold_fol, siv_fol
            a_is = "folio_gold"
            b_is = "siv_canonical"
        else:
            trans_a, trans_b = siv_fol, gold_fol
            a_is = "siv_canonical"
            b_is = "folio_gold"

        sheets.append({
            "premise_id": premise_id,
            "nl": nl,
            "translation_a": trans_a,
            "translation_b": trans_b,
            "preference": "",  # To be filled by annotator: A, B, or Tie
        })

        keys.append({
            "premise_id": premise_id,
            "story_id": row.get("story_id", ""),
            "nl": nl,
            "translation_a_source": a_is,
            "translation_b_source": b_is,
            "category": row.get("category", ""),
            "subcategory": row.get("subcategory", ""),
            "selection_reason": row.get("selection_reason", ""),
            "recall": row.get("recall", ""),
            "overlap_ratio": row.get("overlap_ratio", ""),
        })

    return sheets, keys


# ── Main ─────────────────────────────────────────────────────────────────────

SHEET_COLUMNS = ["premise_id", "nl", "translation_a", "translation_b", "preference"]

KEY_COLUMNS = [
    "premise_id", "story_id", "nl",
    "translation_a_source", "translation_b_source",
    "category", "subcategory", "selection_reason",
    "recall", "overlap_ratio",
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--categorization", type=str,
        default=str(_REPO_ROOT / "reports" / "folio_categorization.csv"),
    )
    ap.add_argument("--n-vocab-divergence", type=int, default=20)
    ap.add_argument("--n-calibration", type=int, default=10)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--output-dir", type=str,
        default=str(_REPO_ROOT / "reports"),
    )
    args = ap.parse_args()

    rows = load_categorization(args.categorization)
    selected = select_annotation_set(
        rows,
        n_vocab_divergence=args.n_vocab_divergence,
        n_calibration=args.n_calibration,
        seed=args.seed,
    )

    sheets, keys = generate_sheets(selected, seed=args.seed)

    # Write annotation sheets (what annotators see)
    sheets_path = Path(args.output_dir) / "annotation_sheets.csv"
    with sheets_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=SHEET_COLUMNS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(sheets)

    # Write key (hidden mapping)
    key_path = Path(args.output_dir) / "annotation_key.csv"
    with key_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=KEY_COLUMNS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(keys)

    print(f"Wrote {sheets_path} ({len(sheets)} premises)")
    print(f"Wrote {key_path}")

    # Summary
    from collections import Counter
    reasons = Counter(k["selection_reason"] for k in keys)
    cats = Counter(k["category"] for k in keys)
    a_sources = Counter(k["translation_a_source"] for k in keys)

    print(f"\nSelection breakdown:")
    for reason, count in reasons.most_common():
        print(f"  {reason}: {count}")

    print(f"\nCategory breakdown:")
    for cat, count in cats.most_common():
        print(f"  {cat}: {count}")

    print(f"\nBlinding check (should be ~50/50):")
    for src, count in a_sources.most_common():
        print(f"  Translation A = {src}: {count} ({count/len(keys):.0%})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
