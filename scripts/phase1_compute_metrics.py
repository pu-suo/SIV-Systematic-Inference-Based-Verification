"""Phase 1.2 — Compute metric scores per (example, translator) pair.

For each entailment result, computes per-premise:
  - SIV soft-mode recall/F1 (via extraction -> test suite -> score)
  - BLEU (vs gold FOL)
  - BERTScore (vs gold FOL)
  - MALLS-LE raw and aligned (bidirectional Vampire entailment)
  - Brunello-LT raw and aligned (Z3 equivalence)

Gold translator rows get perfect scores by definition (no computation needed).
SIV test suites are cached per unique NL premise and reused across translators.

Usage:
    python scripts/phase1_compute_metrics.py \\
      --entailment-results reports/phase1/entailment_results.jsonl \\
      --split train --timeout-s 5

    # Fast run: BLEU + BERTScore only (no Vampire/LLM calls)
    python scripts/phase1_compute_metrics.py \\
      --entailment-results reports/phase1/entailment_results.jsonl \\
      --split train --skip-siv --skip-equivalence

    # Dry run
    python scripts/phase1_compute_metrics.py \\
      --entailment-results reports/phase1/entailment_results.jsonl \\
      --limit 10 --skip-bertscore --skip-siv --skip-equivalence
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from siv.fol_utils import normalize_fol_string


# ── BERTScore calibration ──────────────────────────────────────────────────────

def run_bertscore_calibration() -> Dict[str, float]:
    """Quick sanity check that BERTScore behaves sensibly on FOL strings."""
    from bert_score import score as bs

    pairs = [
        ("P(a)", "P(a)", "identical"),
        ("P(a)", "Q(a)", "different_pred"),
        ("all x.(P(x))", "exists x.(P(x))", "all_vs_exists"),
        ("all x.(P(x) -> Q(x))", "all x.(P(x) -> Q(x))", "same_formula"),
        ("P(a) & Q(b)", "P(a) | Q(b)", "and_vs_or"),
    ]
    cands = [c for c, _, _ in pairs]
    refs = [r for _, r, _ in pairs]
    _, _, F1 = bs(cands, refs, lang="en", verbose=False, rescale_with_baseline=False)

    results = {}
    for (_, _, label), f1 in zip(pairs, F1):
        results[label] = f1.item()
        sys.stderr.write(f"  [calibration] {label}: F1={f1.item():.4f}\n")
    return results


# ── BLEU ───────────────────────────────────────────────────────────────────────

def compute_bleu(candidate: str, reference: str) -> float:
    """Compute sentence-level BLEU between candidate and reference FOL."""
    try:
        from sacrebleu.metrics import BLEU
        bleu = BLEU(effective_order=True)
        cand_tokens = " ".join(_tokenize_fol(candidate))
        ref_tokens = " ".join(_tokenize_fol(reference))
        result = bleu.sentence_score(cand_tokens, [ref_tokens])
        return result.score / 100.0
    except ImportError:
        cand_toks = _tokenize_fol(candidate)
        ref_toks = _tokenize_fol(reference)
        if not cand_toks:
            return 0.0
        ref_set = set(ref_toks)
        return sum(1 for t in cand_toks if t in ref_set) / len(cand_toks)


def _tokenize_fol(fol: str) -> List[str]:
    import re
    fol = normalize_fol_string(fol)
    fol = re.sub(r"([(),.])", r" \1 ", fol)
    fol = re.sub(r"(->|<->|&|\||-)", r" \1 ", fol)
    return [t for t in fol.split() if t]


# ── BERTScore ──────────────────────────────────────────────────────────────────

def compute_bertscore_batch(candidates: List[str], references: List[str]) -> List[float]:
    """Compute BERTScore F1 for parallel lists. Returns list of F1 scores."""
    from bert_score import score as bs
    _, _, F1 = bs(candidates, references, lang="en", verbose=False,
                  rescale_with_baseline=False)
    return [f.item() for f in F1]


# ── SIV Scoring ────────────────────────────────────────────────────────────────

# Cache: NL premise -> (extraction, test_suite, canonical_fol)
_siv_cache: Dict[str, Any] = {}


def _get_siv_artifacts(nl: str, client, timeout_s: int) -> Optional[Dict[str, Any]]:
    """Get or create SIV extraction + test suite for a premise NL string."""
    if nl in _siv_cache:
        return _siv_cache[nl]

    try:
        from siv.extractor import extract_sentence
        from siv.compiler import compile_canonical_fol, compile_sentence_test_suite

        extraction = extract_sentence(nl, client)
        canonical = compile_canonical_fol(extraction)
        suite = compile_sentence_test_suite(extraction, timeout_s=timeout_s)
        result = {
            "extraction": extraction,
            "canonical": canonical,
            "suite": suite,
        }
        _siv_cache[nl] = result
        return result
    except Exception as e:
        sys.stderr.write(f"  [siv] Extraction failed for: {nl[:60]}... ({e})\n")
        _siv_cache[nl] = None
        return None


def score_premise_siv(
    nl: str,
    candidate_fol: str,
    client,
    timeout_s: int,
) -> Optional[Dict[str, float]]:
    """Score a single translated premise against its SIV test suite (soft mode)."""
    artifacts = _get_siv_artifacts(nl, client, timeout_s)
    if artifacts is None:
        return None

    from siv.aligner import (
        align_symbols, extract_symbols_from_fol,
        rewrite_test_suite, rewrite_fol_strings,
    )
    from siv.contrastive_generator import derive_witness_axioms
    from siv.scorer import score

    suite = artifacts["suite"]
    canonical = artifacts["canonical"]

    siv_symbols = extract_symbols_from_fol(canonical)
    cand_symbols = extract_symbols_from_fol(candidate_fol)
    alignment = align_symbols(siv_symbols, cand_symbols)

    rewritten_suite = rewrite_test_suite(suite, alignment)
    raw_witnesses = derive_witness_axioms(suite.extraction)
    rewritten_witnesses = rewrite_fol_strings(raw_witnesses, alignment)

    report = score(
        rewritten_suite, candidate_fol, timeout_s=timeout_s,
        witness_axioms_override=rewritten_witnesses,
    )

    return {
        "recall": report.recall,
        "precision": report.precision,
        "f1": report.f1,
    }


# ── Data Loading ───────────────────────────────────────────────────────────────

def load_folio_gold_map(split: str) -> Dict[str, Dict[str, Any]]:
    """Build a map from story_id to {premises_nl, premises_fol} for gold reference."""
    from datasets import load_dataset

    ds = load_dataset("tasksource/folio", split=split)
    story_map = {}

    for row in ds:
        sid = row.get("story_id")
        if sid in story_map:
            continue
        nl_parts = [p.strip() for p in row["premises"].split("\n") if p.strip()]
        fol_parts = [p.strip() for p in row["premises-FOL"].split("\n") if p.strip()]
        if len(nl_parts) != len(fol_parts):
            continue
        story_map[sid] = {
            "premises_nl": nl_parts,
            "premises_fol": fol_parts,
        }

    return story_map


# ── Helpers ────────────────────────────────────────────────────────────────────

def _safe_mean(vals):
    valid = [v for v in vals if v is not None]
    return sum(valid) / len(valid) if valid else None


def _safe_min(vals):
    valid = [v for v in vals if v is not None]
    return min(valid) if valid else None


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--entailment-results", type=str, required=True)
    ap.add_argument("--split", type=str, default="train")
    ap.add_argument("--timeout-s", type=int, default=5,
                    help="Vampire/Z3 timeout per check (default 5s, lower = faster)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--output", type=str,
                    default=str(_REPO_ROOT / "reports" / "phase1" / "metric_scores.jsonl"))
    ap.add_argument("--skip-bertscore", action="store_true")
    ap.add_argument("--skip-siv", action="store_true",
                    help="Skip SIV scoring (requires LLM API + Vampire)")
    ap.add_argument("--skip-equivalence", action="store_true",
                    help="Skip MALLS-LE and Brunello-LT (Vampire/Z3 calls)")
    args = ap.parse_args()

    # Load entailment results
    ent_results = []
    for line in Path(args.entailment_results).read_text().splitlines():
        if line.strip():
            ent_results.append(json.loads(line))

    if args.limit:
        ent_results = ent_results[:args.limit]

    sys.stderr.write(f"[metrics] {len(ent_results)} rows to process\n")

    # Separate gold vs model rows — gold gets perfect scores, no computation
    gold_rows = [r for r in ent_results if r["translator"] == "gold"]
    model_rows = [r for r in ent_results if r["translator"] != "gold"]
    sys.stderr.write(
        f"[metrics] {len(gold_rows)} gold (trivial), "
        f"{len(model_rows)} model (need computation)\n"
    )

    # Count unique premises to estimate work
    unique_premises_nl = set()
    for r in model_rows:
        story_id = r["story_id"]
        # We'll count after loading gold map
    sys.stderr.write(f"[metrics] Enabled metrics: BLEU=always")
    if not args.skip_bertscore:
        sys.stderr.write(", BERTScore")
    if not args.skip_siv:
        sys.stderr.write(", SIV")
    if not args.skip_equivalence:
        sys.stderr.write(", MALLS-LE, Brunello-LT")
    sys.stderr.write("\n")

    # Load gold reference
    story_map = load_folio_gold_map(args.split)
    sys.stderr.write(f"[metrics] Gold reference for {len(story_map)} stories\n")

    # BERTScore calibration
    if not args.skip_bertscore:
        sys.stderr.write("[metrics] BERTScore calibration:\n")
        run_bertscore_calibration()

    # SIV client
    siv_client = None
    if not args.skip_siv:
        import os
        from dotenv import load_dotenv
        load_dotenv(_REPO_ROOT / ".env")
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key:
            from openai import OpenAI
            from siv.frozen_client import FrozenClient
            siv_client = FrozenClient(OpenAI())
        else:
            sys.stderr.write("[metrics] OPENAI_API_KEY not set. Skipping SIV.\n")
            args.skip_siv = True

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Phase 1: Gold rows (trivial — perfect scores) ─────────────────────────

    results = []
    for row in gold_rows:
        story = story_map.get(row["story_id"])
        if story is None:
            continue
        n = len(story["premises_fol"])
        per_premise = [
            {
                "premise_idx": i,
                "bleu": 1.0,
                "bertscore": 1.0,
                "siv_recall": 1.0,
                "siv_f1": 1.0,
                "malls_le_raw": 1.0,
                "malls_le_aligned": 1.0,
                "brunello_lt_raw": 1.0,
                "brunello_lt_aligned": 1.0,
            }
            for i in range(n)
        ]
        results.append({
            "example_id": row["example_id"],
            "story_id": row["story_id"],
            "translator": "gold",
            "n_premises": n,
            "extraction_failures": 0,
            "siv_mean_recall": 1.0,
            "siv_min_recall": 1.0,
            "siv_mean_f1": 1.0,
            "siv_min_f1": 1.0,
            "bleu_mean": 1.0,
            "bleu_min": 1.0,
            "bertscore_mean": 1.0,
            "bertscore_min": 1.0,
            "malls_le_raw_mean": 1.0,
            "malls_le_aligned_mean": 1.0,
            "brunello_lt_raw_mean": 1.0,
            "brunello_lt_aligned_mean": 1.0,
            "per_premise_scores": per_premise,
        })
    sys.stderr.write(f"[metrics] {len(results)} gold rows done (trivial)\n")

    # ── Phase 2: Model rows (actual computation) ──────────────────────────────

    # Collect BERTScore pairs for batch computation
    bertscore_pairs = []  # (result_idx, premise_idx, cand, gold)
    model_result_start = len(results)

    t0 = time.time()
    for row_idx, row in enumerate(model_rows):
        story = story_map.get(row["story_id"])
        if story is None:
            continue

        premises_fol_translated = row["premises_fol"]
        premises_fol_gold = story["premises_fol"]
        premises_nl = story["premises_nl"]
        n = min(len(premises_fol_translated), len(premises_fol_gold), len(premises_nl))

        per_premise = []

        for i in range(n):
            cand = premises_fol_translated[i]
            gold = premises_fol_gold[i]
            nl = premises_nl[i]

            scores: Dict[str, Any] = {"premise_idx": i}

            # BLEU (instant)
            scores["bleu"] = compute_bleu(cand, gold)

            # SIV (LLM + Vampire)
            if not args.skip_siv and siv_client is not None:
                siv_result = score_premise_siv(nl, cand, siv_client, args.timeout_s)
                if siv_result is not None:
                    scores["siv_recall"] = siv_result["recall"]
                    scores["siv_f1"] = siv_result["f1"]
                else:
                    scores["siv_recall"] = None
                    scores["siv_f1"] = None
            else:
                scores["siv_recall"] = None
                scores["siv_f1"] = None

            # MALLS-LE + Brunello-LT (Vampire/Z3)
            if not args.skip_equivalence:
                from siv.malls_le import malls_le_equivalence, malls_le_equivalence_aligned
                scores["malls_le_raw"] = malls_le_equivalence(cand, gold, timeout=args.timeout_s)
                scores["malls_le_aligned"] = malls_le_equivalence_aligned(
                    cand, gold, timeout=args.timeout_s)

                from siv.brunello_lt import brunello_lt_equivalence, brunello_lt_equivalence_aligned
                scores["brunello_lt_raw"] = brunello_lt_equivalence(cand, gold, timeout=args.timeout_s)
                scores["brunello_lt_aligned"] = brunello_lt_equivalence_aligned(
                    cand, gold, timeout=args.timeout_s)
            else:
                scores["malls_le_raw"] = None
                scores["malls_le_aligned"] = None
                scores["brunello_lt_raw"] = None
                scores["brunello_lt_aligned"] = None

            # BERTScore: defer to batch
            if not args.skip_bertscore:
                bertscore_pairs.append((len(results), i, cand, gold))
            scores["bertscore"] = None

            per_premise.append(scores)

        result_row = {
            "example_id": row["example_id"],
            "story_id": row["story_id"],
            "translator": row["translator"],
            "n_premises": n,
            "extraction_failures": sum(1 for p in per_premise if p.get("siv_recall") is None),
            "siv_mean_recall": _safe_mean([p["siv_recall"] for p in per_premise]),
            "siv_min_recall": _safe_min([p["siv_recall"] for p in per_premise]),
            "siv_mean_f1": _safe_mean([p["siv_f1"] for p in per_premise]),
            "siv_min_f1": _safe_min([p["siv_f1"] for p in per_premise]),
            "bleu_mean": _safe_mean([p["bleu"] for p in per_premise]),
            "bleu_min": _safe_min([p["bleu"] for p in per_premise]),
            "bertscore_mean": None,
            "bertscore_min": None,
            "malls_le_raw_mean": _safe_mean([p.get("malls_le_raw") for p in per_premise]),
            "malls_le_aligned_mean": _safe_mean([p.get("malls_le_aligned") for p in per_premise]),
            "brunello_lt_raw_mean": _safe_mean([p.get("brunello_lt_raw") for p in per_premise]),
            "brunello_lt_aligned_mean": _safe_mean([p.get("brunello_lt_aligned") for p in per_premise]),
            "per_premise_scores": per_premise,
        }
        results.append(result_row)

        # Progress every row
        elapsed = time.time() - t0
        rate = (row_idx + 1) / elapsed if elapsed > 0 else 0
        eta = (len(model_rows) - row_idx - 1) / rate if rate > 0 else 0
        sys.stderr.write(
            f"\r[metrics] {row_idx + 1}/{len(model_rows)} model rows "
            f"({elapsed:.0f}s elapsed, ~{eta:.0f}s remaining, "
            f"siv_cache={len(_siv_cache)})"
        )
        sys.stderr.flush()

        # Incremental save every 200 rows
        if (row_idx + 1) % 200 == 0:
            with output_path.open("w") as f:
                for r in results:
                    f.write(json.dumps(r) + "\n")

    sys.stderr.write("\n")

    # ── Phase 3: Batch BERTScore ──────────────────────────────────────────────

    if not args.skip_bertscore and bertscore_pairs:
        sys.stderr.write(
            f"[metrics] Batch BERTScore for {len(bertscore_pairs)} premise pairs...\n"
        )
        cands = [p[2] for p in bertscore_pairs]
        golds = [p[3] for p in bertscore_pairs]

        # Process in chunks to show progress
        CHUNK = 500
        all_f1s = []
        for start in range(0, len(cands), CHUNK):
            end = min(start + CHUNK, len(cands))
            chunk_f1 = compute_bertscore_batch(cands[start:end], golds[start:end])
            all_f1s.extend(chunk_f1)
            sys.stderr.write(
                f"\r[metrics] BERTScore: {end}/{len(cands)}"
            )
            sys.stderr.flush()
        sys.stderr.write("\n")

        # Assign back
        by_row: Dict[int, List] = defaultdict(list)
        for (ridx, pidx, _, _), f1 in zip(bertscore_pairs, all_f1s):
            by_row[ridx].append((pidx, f1))

        for ridx, premise_scores in by_row.items():
            result = results[ridx]
            for pidx, f1 in premise_scores:
                result["per_premise_scores"][pidx]["bertscore"] = f1
            bs_vals = [f1 for _, f1 in premise_scores]
            result["bertscore_mean"] = sum(bs_vals) / len(bs_vals) if bs_vals else None
            result["bertscore_min"] = min(bs_vals) if bs_vals else None

    # ── Write final output ────────────────────────────────────────────────────

    with output_path.open("w") as f:
        for row in results:
            f.write(json.dumps(row) + "\n")

    sys.stderr.write(f"[metrics] Wrote {len(results)} rows to {output_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
