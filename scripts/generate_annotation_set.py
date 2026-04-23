"""Generate blinded forced-choice annotation sheets for Tier 1 human study.

Selects premises from the categorization output (joined with baseline metrics),
creates randomized A/B pairs (FOLIO gold vs SIV canonical), and outputs:
  - annotation_sheets.csv: what annotators see (blinded)
  - annotation_key.csv: hidden mapping for analysis

Selection is BLEU-aware: the paper's claim is that SIV flags divergences BLEU
misses, so we draw primarily from cases where the metrics disagree.

Usage:
    python scripts/generate_annotation_set.py \
        --categorization reports/folio_categorization_after_prompt_fix.csv \
        --baselines reports/baseline_metrics_after_prompt_fix.json
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).parent.parent


def load_categorization(path: str) -> List[Dict[str, str]]:
    with open(path) as f:
        return list(csv.DictReader(f))


def load_baselines(path: str) -> Dict[tuple, Dict[str, Any]]:
    """Load baseline metrics keyed by (story_id, nl) for join."""
    with open(path) as f:
        rows = json.load(f)
    return {(str(r["story_id"]), r["nl"]): r for r in rows}


def join_rows(
    cat_rows: List[Dict[str, str]],
    baselines: Dict[tuple, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Left-join categorization rows with baseline metrics on (story_id, nl).

    Rows without a baseline match (parse errors, extraction failures) get
    bleu=None and are excluded from BLEU-dependent buckets downstream.
    """
    joined = []
    for row in cat_rows:
        key = (str(row["story_id"]), row["nl"])
        b = baselines.get(key)
        merged = dict(row)
        if b is not None:
            merged["bleu"] = b.get("bleu")
            merged["exact_match"] = b.get("exact_match")
            # Prefer baseline JSON's siv_recall if the CSV's is missing/empty
            if not merged.get("recall"):
                merged["recall"] = b.get("siv_recall")
            # Pull FOLs from baselines if categorization lacked them
            if not merged.get("folio_gold_fol"):
                merged["folio_gold_fol"] = b.get("folio_gold_fol", "")
            if not merged.get("siv_canonical_fol"):
                merged["siv_canonical_fol"] = b.get("siv_canonical_fol", "")
        else:
            merged["bleu"] = None
            merged["exact_match"] = None
        joined.append(merged)
    return joined


def _siv_recall(row: Dict[str, Any]) -> Optional[float]:
    v = row.get("recall")
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _bleu(row: Dict[str, Any]) -> Optional[float]:
    v = row.get("bleu")
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def select_annotation_set(
    rows: List[Dict[str, Any]],
    n_headline: int = 40,
    n_inverse: int = 13,
    n_vocab_divergence: int = 20,
    n_calibration_good: int = 10,
    n_calibration_bad: int = 10,
    bleu_high: float = 0.5,
    bleu_low: float = 0.5,
    bleu_good_floor: float = 0.7,
    bleu_bad_ceiling: float = 0.2,
    seed: int = 42,
) -> List[Dict[str, Any]]:
    """Select premises for annotation, stratified across metric-disagreement
    buckets.

    Buckets (in order, dedup by (story_id, nl)):
      1. Structural catches: all restrictor_collapse / entity_flattening /
         quantifier_mismatch cases (headline exemplars, regardless of BLEU).
      2. High-BLEU SIV failures: siv_recall==0 and bleu>=bleu_high. The core
         disagreement signal — BLEU says "fine," SIV says "divergent."
      3. Low-BLEU SIV successes: siv_recall==1.0 and bleu<bleu_low. Inverse
         disagreement — BLEU penalizes vocab, SIV correctly ignores.
      4. Vocab divergence sample: from vocab_divergence_total; the honest
         limitation of SIV's lexical-exactness principle.
      5. Calibration (both-agree-good): perfect_agreement with bleu>=0.7.
      6. Calibration (both-agree-bad): siv_recall==0 AND bleu<=0.2 —
         genuine translation errors both metrics flag.
    """
    rng = random.Random(seed)

    structural_cats = {"restrictor_collapse", "entity_flattening", "quantifier_mismatch"}
    selected: List[Dict[str, Any]] = []
    seen: set = set()

    def key(r: Dict[str, Any]) -> tuple:
        return (str(r.get("story_id", "")), r.get("nl", ""))

    def add(r: Dict[str, Any], reason: str) -> bool:
        k = key(r)
        if k in seen:
            return False
        seen.add(k)
        selected.append({**r, "selection_reason": reason})
        return True

    # 1. Structural catches — always include all of them
    structural = [r for r in rows if r.get("category") in structural_cats]
    for r in structural:
        add(r, f"structural_catch ({r['category']})")

    # 2. High-BLEU SIV failures (the main disagreement signal)
    high_bleu_fails = [
        r for r in rows
        if _siv_recall(r) == 0.0
        and _bleu(r) is not None
        and _bleu(r) >= bleu_high
        and r.get("category") not in {"parse_error"}
    ]
    rng.shuffle(high_bleu_fails)
    for r in high_bleu_fails[:n_headline]:
        add(r, "high_bleu_siv_fail")

    # 3. Low-BLEU SIV successes (inverse disagreement)
    low_bleu_successes = [
        r for r in rows
        if _siv_recall(r) == 1.0
        and _bleu(r) is not None
        and _bleu(r) < bleu_low
    ]
    rng.shuffle(low_bleu_successes)
    for r in low_bleu_successes[:n_inverse]:
        add(r, "low_bleu_siv_success")

    # 4. Vocab divergence sample (honest limitation)
    vocab = [r for r in rows if r.get("category") == "vocab_divergence_total"]
    rng.shuffle(vocab)
    added = 0
    for r in vocab:
        if added >= n_vocab_divergence:
            break
        if add(r, "vocab_divergence_sample"):
            added += 1

    # 5. Calibration: both agree the translation is good
    good = [
        r for r in rows
        if r.get("category") == "perfect_agreement"
        and _bleu(r) is not None
        and _bleu(r) >= bleu_good_floor
    ]
    rng.shuffle(good)
    added = 0
    for r in good:
        if added >= n_calibration_good:
            break
        if add(r, "calibration_good"):
            added += 1

    # 6. Calibration: both agree the translation is bad
    bad = [
        r for r in rows
        if _siv_recall(r) == 0.0
        and _bleu(r) is not None
        and _bleu(r) <= bleu_bad_ceiling
        and r.get("category") not in {"parse_error"}
    ]
    rng.shuffle(bad)
    added = 0
    for r in bad:
        if added >= n_calibration_bad:
            break
        if add(r, "calibration_bad"):
            added += 1

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

        if rng.random() < 0.5:
            trans_a, trans_b = gold_fol, siv_fol
            a_is, b_is = "folio_gold", "siv_canonical"
        else:
            trans_a, trans_b = siv_fol, gold_fol
            a_is, b_is = "siv_canonical", "folio_gold"

        sheets.append({
            "premise_id": premise_id,
            "nl": nl,
            "translation_a": trans_a,
            "translation_b": trans_b,
            "preference": "",  # annotator fills: A, B, Tie, or BothWrong
        })

        bleu_val = row.get("bleu")
        keys.append({
            "premise_id": premise_id,
            "story_id": row.get("story_id", ""),
            "nl": nl,
            "translation_a_source": a_is,
            "translation_b_source": b_is,
            "category": row.get("category", ""),
            "subcategory": row.get("subcategory", ""),
            "selection_reason": row.get("selection_reason", ""),
            "siv_recall": row.get("recall", ""),
            "bleu": f"{bleu_val:.4f}" if isinstance(bleu_val, (int, float)) else "",
            "overlap_ratio": row.get("overlap_ratio", ""),
        })

    return sheets, keys


SHEET_COLUMNS = ["premise_id", "nl", "translation_a", "translation_b", "preference"]

KEY_COLUMNS = [
    "premise_id", "story_id", "nl",
    "translation_a_source", "translation_b_source",
    "category", "subcategory", "selection_reason",
    "siv_recall", "bleu", "overlap_ratio",
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--categorization", type=str,
        default=str(_REPO_ROOT / "reports" / "folio_categorization_after_prompt_fix.csv"),
    )
    ap.add_argument(
        "--baselines", type=str,
        default=str(_REPO_ROOT / "reports" / "baseline_metrics_after_prompt_fix.json"),
    )
    ap.add_argument("--n-headline", type=int, default=40,
                    help="high-BLEU SIV-fail cases (core disagreement signal)")
    ap.add_argument("--n-inverse", type=int, default=13,
                    help="low-BLEU SIV-success cases (inverse disagreement)")
    ap.add_argument("--n-vocab-divergence", type=int, default=20)
    ap.add_argument("--n-calibration-good", type=int, default=10)
    ap.add_argument("--n-calibration-bad", type=int, default=10)
    ap.add_argument("--bleu-high", type=float, default=0.5)
    ap.add_argument("--bleu-low", type=float, default=0.5)
    ap.add_argument("--bleu-good-floor", type=float, default=0.7)
    ap.add_argument("--bleu-bad-ceiling", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--output-dir", type=str,
        default=str(_REPO_ROOT / "reports"),
    )
    args = ap.parse_args()

    cat_rows = load_categorization(args.categorization)
    baselines = load_baselines(args.baselines)
    rows = join_rows(cat_rows, baselines)

    joined_with_bleu = sum(1 for r in rows if r.get("bleu") is not None)
    print(f"Loaded {len(cat_rows)} categorization rows, "
          f"{len(baselines)} baseline rows, "
          f"{joined_with_bleu} joined with BLEU.")

    selected = select_annotation_set(
        rows,
        n_headline=args.n_headline,
        n_inverse=args.n_inverse,
        n_vocab_divergence=args.n_vocab_divergence,
        n_calibration_good=args.n_calibration_good,
        n_calibration_bad=args.n_calibration_bad,
        bleu_high=args.bleu_high,
        bleu_low=args.bleu_low,
        bleu_good_floor=args.bleu_good_floor,
        bleu_bad_ceiling=args.bleu_bad_ceiling,
        seed=args.seed,
    )

    sheets, keys = generate_sheets(selected, seed=args.seed)

    sheets_path = Path(args.output_dir) / "annotation_sheets.csv"
    with sheets_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=SHEET_COLUMNS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(sheets)

    key_path = Path(args.output_dir) / "annotation_key.csv"
    with key_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=KEY_COLUMNS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(keys)

    print(f"\nWrote {sheets_path} ({len(sheets)} premises)")
    print(f"Wrote {key_path}")

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
