"""Compute baseline metrics (BLEU, BERTScore, exact match) for FOL candidates.

Takes a folio_agreement.json report and computes BLEU, BERTScore, and exact
match between each FOLIO gold FOL and SIV canonical FOL (as reference).
Can also score arbitrary candidate lists from JSON input.

Usage:
    # Score FOLIO evaluation results
    python scripts/compute_baseline_metrics.py

    # Score from custom candidates JSON
    python scripts/compute_baseline_metrics.py \
        --input reports/candidates.json \
        --output reports/baseline_scores.csv

    # Just compute BLEU for a quick check (skip BERTScore which is slow)
    python scripts/compute_baseline_metrics.py --skip-bertscore
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from siv.fol_utils import normalize_fol_string


# ── BLEU scoring ─────────────────────────────────────────────────────────────

def _tokenize_fol(fol: str) -> List[str]:
    """Tokenize a FOL string for BLEU computation.

    Splits on whitespace, parentheses, commas, and logical operators to
    produce meaningful tokens for n-gram overlap computation.

    Handles both ASCII operators (->  &  |  -) and Unicode operators
    (∀ ∃ ∧ ∨ → ↔ ¬) so that normalization failures don't produce
    single-token noise.
    """
    import re
    # Normalize Unicode operators to ASCII first
    from siv.fol_utils import normalize_fol_string
    fol = normalize_fol_string(fol)
    # Insert spaces around parens, commas, and operators
    fol = re.sub(r"([(),.])", r" \1 ", fol)
    fol = re.sub(r"(->|<->|&|\||-)", r" \1 ", fol)
    return [t for t in fol.split() if t]


def compute_bleu(candidate: str, reference: str) -> float:
    """Compute sentence-level BLEU between candidate and reference FOL strings.

    Uses sacrebleu's sentence_bleu for reproducibility. Falls back to a
    simple unigram precision if sacrebleu is unavailable.
    """
    try:
        from sacrebleu.metrics import BLEU
        bleu = BLEU(effective_order=True)
        # sacrebleu expects raw strings; it tokenizes internally
        # but for FOL we need custom tokenization
        cand_tokens = " ".join(_tokenize_fol(candidate))
        ref_tokens = " ".join(_tokenize_fol(reference))
        result = bleu.sentence_score(cand_tokens, [ref_tokens])
        return result.score / 100.0  # Normalize to 0-1
    except ImportError:
        # Fallback: simple unigram precision
        cand_toks = _tokenize_fol(candidate)
        ref_toks = _tokenize_fol(reference)
        if not cand_toks:
            return 0.0
        ref_set = set(ref_toks)
        matches = sum(1 for t in cand_toks if t in ref_set)
        return matches / len(cand_toks)


# ── BERTScore ────────────────────────────────────────────────────────────────

_bertscore_model = None


def compute_bertscore(candidate: str, reference: str) -> float:
    """Compute BERTScore F1 between candidate and reference FOL strings."""
    try:
        from bert_score import score as bert_score_fn
        P, R, F1 = bert_score_fn(
            [candidate], [reference],
            lang="en", verbose=False,
            rescale_with_baseline=False,
        )
        return F1[0].item()
    except ImportError:
        return -1.0  # Sentinel: BERTScore not available


# ── Exact match ──────────────────────────────────────────────────────────────

def compute_exact_match(candidate: str, reference: str) -> float:
    """Normalized exact match: 1.0 if normalized strings are identical, else 0.0."""
    c = normalize_fol_string(candidate).strip()
    r = normalize_fol_string(reference).strip()
    return 1.0 if c == r else 0.0


# ── Batch scoring ────────────────────────────────────────────────────────────

def score_pair(
    candidate: str,
    reference: str,
    skip_bertscore: bool = False,
) -> Dict[str, float]:
    """Score a single (candidate, reference) pair with all metrics."""
    result = {
        "bleu": compute_bleu(candidate, reference),
        "exact_match": compute_exact_match(candidate, reference),
    }
    if not skip_bertscore:
        result["bertscore_f1"] = compute_bertscore(candidate, reference)
    return result


def score_folio_report(
    report_path: str,
    skip_bertscore: bool = False,
) -> List[Dict[str, Any]]:
    """Score all premises in a folio_agreement.json report.

    For each premise, computes BLEU/BERTScore/exact_match between:
    - FOLIO gold FOL (candidate) vs SIV canonical FOL (reference)

    This direction (gold as candidate, SIV as reference) matches the SIV
    evaluation framing: we're measuring how well FOLIO gold performs relative
    to SIV's decomposition.
    """
    data = json.loads(Path(report_path).read_text(encoding="utf-8"))
    results = []

    for p in data["per_pair"]:
        ff = p["folio_faithfulness"]
        if ff.get("parse_error"):
            continue

        gold_fol = normalize_fol_string(ff["gold_fol_raw"])
        siv_fol = p["canonical_fol"]

        siv_score = ff.get("score", {})
        siv_recall = siv_score.get("recall") if siv_score else None

        metrics = score_pair(gold_fol, siv_fol, skip_bertscore=skip_bertscore)

        results.append({
            "story_id": p["story_id"],
            "nl": p["nl"],
            "folio_gold_fol": ff["gold_fol_raw"],
            "siv_canonical_fol": siv_fol,
            "siv_recall": siv_recall,
            "siv_precision": siv_score.get("precision") if siv_score else None,
            "siv_f1": siv_score.get("f1") if siv_score else None,
            **metrics,
        })

    return results


def score_candidates_json(
    input_path: str,
    skip_bertscore: bool = False,
) -> List[Dict[str, Any]]:
    """Score candidates from a JSON file with structure:
    [{"candidate_fol": "...", "reference_fol": "...", ...}, ...]
    """
    data = json.loads(Path(input_path).read_text(encoding="utf-8"))
    results = []
    for item in data:
        candidate = item["candidate_fol"]
        reference = item["reference_fol"]
        metrics = score_pair(candidate, reference, skip_bertscore=skip_bertscore)
        results.append({**item, **metrics})
    return results


# ── Main ─────────────────────────────────────────────────────────────────────

FOLIO_COLUMNS = [
    "story_id", "nl", "folio_gold_fol", "siv_canonical_fol",
    "siv_recall", "siv_precision", "siv_f1",
    "bleu", "exact_match", "bertscore_f1",
]

CANDIDATE_COLUMNS = [
    "candidate_fol", "reference_fol", "bleu", "exact_match", "bertscore_f1",
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--input", type=str,
        default=str(_REPO_ROOT / "reports" / "folio_agreement.json"),
        help="Path to folio_agreement JSON or candidates JSON.",
    )
    ap.add_argument(
        "--output", type=str,
        default=str(_REPO_ROOT / "reports" / "baseline_metrics.csv"),
        help="Output CSV path.",
    )
    ap.add_argument(
        "--mode", choices=["folio", "candidates"], default="folio",
        help="Input mode: 'folio' for folio_agreement.json, 'candidates' for custom JSON.",
    )
    ap.add_argument(
        "--skip-bertscore", action="store_true",
        help="Skip BERTScore computation (slow, requires GPU).",
    )
    args = ap.parse_args()

    print(f"Scoring from {args.input}...")

    if args.mode == "folio":
        results = score_folio_report(args.input, skip_bertscore=args.skip_bertscore)
        columns = [c for c in FOLIO_COLUMNS if not (args.skip_bertscore and c == "bertscore_f1")]
    else:
        results = score_candidates_json(args.input, skip_bertscore=args.skip_bertscore)
        columns = [c for c in CANDIDATE_COLUMNS if not (args.skip_bertscore and c == "bertscore_f1")]

    # Write CSV
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, quoting=csv.QUOTE_ALL, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    # Also write JSON for programmatic use
    json_path = out_path.with_suffix(".json")
    json_path.write_text(json.dumps(results, indent=2, default=str))

    print(f"Wrote {out_path} ({len(results)} rows)")
    print(f"Wrote {json_path}")

    # Summary statistics
    if results:
        bleu_scores = [r["bleu"] for r in results]
        em_scores = [r["exact_match"] for r in results]
        print(f"\nBLEU: mean={sum(bleu_scores)/len(bleu_scores):.4f}, "
              f"min={min(bleu_scores):.4f}, max={max(bleu_scores):.4f}")
        print(f"Exact match: {sum(em_scores)}/{len(em_scores)} "
              f"({sum(em_scores)/len(em_scores):.1%})")

        if not args.skip_bertscore and "bertscore_f1" in results[0]:
            bs_scores = [r["bertscore_f1"] for r in results if r["bertscore_f1"] >= 0]
            if bs_scores:
                print(f"BERTScore F1: mean={sum(bs_scores)/len(bs_scores):.4f}, "
                      f"min={min(bs_scores):.4f}, max={max(bs_scores):.4f}")

        # Show SIV vs BLEU disagreement cases
        if "siv_recall" in results[0]:
            disagree = [r for r in results
                        if r.get("siv_recall") is not None
                        and r["siv_recall"] == 0.0
                        and r["bleu"] > 0.3]
            print(f"\nMetric disagreement: {len(disagree)} cases where SIV_recall=0 but BLEU>0.3")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
