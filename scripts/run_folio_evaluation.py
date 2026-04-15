"""Run SIV's full pipeline against FOLIO premises and write an agreement report.

Phase 5 deliverable per SIV.md §17 (amended H). For each unique premise NL,
this script:

  1. Extracts the premise via the frozen LLM (extract_sentence).
  2. Compiles a test suite (positives + contrastives) from the extraction.
  3. Scores TWO candidates against that test suite:
       - SIV canonical FOL (self-consistency measurement).
       - FOLIO gold FOL (FOLIO-faithfulness measurement).

Aggregates each measurement separately and writes reports/folio_agreement.json
with top-level keys `self_consistency` and `folio_faithfulness`.

This script measures only. It does not modify the pipeline. If measurement
reveals a bug, stop and surface (§17 instruction). FOLIO-faithfulness F1 < 1.0
is the expected result and the paper's headline claim, not a failure.

Usage:
    OPENAI_API_KEY loaded from .env at repo root.
    python scripts/run_folio_evaluation.py [--limit N] [--timeout-s N]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).parent.parent
load_dotenv(_REPO_ROOT / ".env")

import os
sys.path.insert(0, str(_REPO_ROOT))

if not os.environ.get("OPENAI_API_KEY"):
    sys.stderr.write(
        f"[phase5] OPENAI_API_KEY not set. Configure it in {_REPO_ROOT / '.env'} "
        f"and re-run.\n"
    )
    sys.exit(2)


from datasets import load_dataset
from openai import OpenAI

from siv.compiler import compile_canonical_fol, compile_sentence_test_suite
from siv.contrastive_generator import classify_structure
from siv.extractor import extract_sentence
from siv.fol_utils import is_valid_fol, normalize_fol_string
from siv.frozen_client import FrozenClient
from siv.schema import Formula, SchemaViolation, SentenceExtraction, TestSuite
from siv.scorer import score


# ── Data loading ────────────────────────────────────────────────────────────

def load_folio_premise_pairs(split: str) -> List[Dict[str, Any]]:
    """Return deduplicated (NL, FOL) premise pairs from tasksource/folio."""
    ds = load_dataset("tasksource/folio", split=split)
    seen: set = set()
    pairs: List[Dict[str, Any]] = []
    for row in ds:
        nl_parts = [p.strip() for p in row["premises"].split("\n") if p.strip()]
        fol_parts = [p.strip() for p in row["premises-FOL"].split("\n") if p.strip()]
        if len(nl_parts) != len(fol_parts):
            continue
        for n, f in zip(nl_parts, fol_parts):
            if n in seen:
                continue
            seen.add(n)
            pairs.append({
                "story_id": row.get("story_id"),
                "nl": n,
                "gold_fol": f,
            })
    return pairs


# ── Per-Formula-case classification ─────────────────────────────────────────

def top_level_formula_case(f: Formula) -> str:
    """One of "atomic", "quantification", "connective", "negation"."""
    if f.atomic is not None:
        return "atomic"
    if f.quantification is not None:
        return "quantification"
    if f.negation is not None:
        return "negation"
    if f.connective is not None:
        return "connective"
    return "other"


# ── Per-premise measurement ─────────────────────────────────────────────────

def _score_record(report) -> Dict[str, Any]:
    return {
        "recall": report.recall,
        "precision": report.precision,
        "f1": report.f1,
        "positives_total": report.positives_total,
        "positives_entailed": report.positives_entailed,
        "contrastives_total": report.contrastives_total,
        "contrastives_rejected": report.contrastives_rejected,
        "per_test_results": [
            {"kind": k, "fol": f, "verdict": v} for (k, f, v) in report.per_test_results
        ],
    }


def _score_folio_gold(suite: TestSuite, gold_fol_raw: str, timeout_s: int) -> Dict[str, Any]:
    """Score the FOLIO gold FOL against the test suite.

    FOLIO gold uses Unicode (∀ ∃ ∧ ∨ → ⊕ ¬). We run normalize_fol_string once;
    no predicate renaming, no vocabulary alignment (§17 Amendment H forbidden
    move). If the result does not parse, record an error and skip scoring.
    """
    gold_normalized = normalize_fol_string(gold_fol_raw)
    if not is_valid_fol(gold_normalized):
        return {
            "gold_fol_raw": gold_fol_raw,
            "gold_fol_normalized": gold_normalized,
            "parse_error": True,
            "score": None,
        }
    report = score(suite, gold_normalized, timeout_s=timeout_s)
    return {
        "gold_fol_raw": gold_fol_raw,
        "gold_fol_normalized": gold_normalized,
        "parse_error": False,
        "score": _score_record(report),
    }


def run(
    pairs: List[Dict[str, Any]],
    client,
    timeout_s: int = 10,
) -> Dict[str, Any]:
    per_pair: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []

    t0 = time.time()
    for i, pair in enumerate(pairs):
        nl = pair["nl"]
        gold_fol_raw = pair["gold_fol"]

        try:
            extraction = extract_sentence(nl, client)
        except SchemaViolation as e:
            failures.append({
                "story_id": pair["story_id"], "nl": nl,
                "error_kind": "schema_violation", "error": str(e),
            })
            continue
        except Exception as e:  # noqa: BLE001
            failures.append({
                "story_id": pair["story_id"], "nl": nl,
                "error_kind": "exception",
                "error": f"{type(e).__name__}: {e}",
            })
            continue

        top_case = top_level_formula_case(extraction.formula)
        struct_class = classify_structure(extraction)
        canonical = compile_canonical_fol(extraction)

        try:
            suite = compile_sentence_test_suite(extraction, timeout_s=timeout_s)
            self_report = score(suite, canonical, timeout_s=timeout_s)
            folio_res = _score_folio_gold(suite, gold_fol_raw, timeout_s)
        except Exception as e:  # noqa: BLE001
            failures.append({
                "story_id": pair["story_id"], "nl": nl,
                "error_kind": "pipeline_exception",
                "error": f"{type(e).__name__}: {e}",
                "trace": traceback.format_exc(limit=3),
            })
            continue

        per_pair.append({
            "story_id": pair["story_id"],
            "nl": nl,
            "canonical_fol": canonical,
            "top_formula_case": top_case,
            "structural_class": struct_class,
            "self_consistency": _score_record(self_report),
            "folio_faithfulness": folio_res,
        })

        if (i + 1) % 25 == 0 or (i + 1) == len(pairs):
            dt = time.time() - t0
            sys.stderr.write(
                f"[phase5] {i + 1}/{len(pairs)} processed "
                f"(failures={len(failures)}, elapsed={dt:.0f}s)\n"
            )

    return {
        "per_pair": per_pair,
        "failures": failures,
        "runtime_seconds": time.time() - t0,
    }


# ── Aggregation ─────────────────────────────────────────────────────────────

def _summarize(rows: List[Dict[str, Any]], score_key: str) -> Dict[str, Any]:
    if not rows:
        return {"count": 0}
    scores = []
    for r in rows:
        s = r.get(score_key)
        if s is None:
            continue
        # self_consistency stores the score dict directly.
        # folio_faithfulness wraps it under "score" (None if parse error).
        if score_key == "folio_faithfulness":
            if s.get("parse_error"):
                continue
            s = s.get("score")
            if s is None:
                continue
        scores.append(s)

    recalls = [s["recall"] for s in scores]
    f1s = [s["f1"] for s in scores if s["f1"] is not None]
    precisions = [s["precision"] for s in scores if s["precision"] is not None]
    return {
        "count": len(rows),
        "scored_count": len(scores),
        "mean_recall": mean(recalls) if recalls else None,
        "mean_precision": mean(precisions) if precisions else None,
        "mean_f1_where_defined": mean(f1s) if f1s else None,
        "f1_defined_count": len(f1s),
        "recall_only_count": len(scores) - len(f1s),
    }


def _f1_histogram(rows: List[Dict[str, Any]], score_key: str) -> List[int]:
    bins = [0] * 11
    for r in rows:
        s = r.get(score_key)
        if s is None:
            continue
        if score_key == "folio_faithfulness":
            if s.get("parse_error"):
                continue
            s = s.get("score")
            if s is None:
                continue
        if s["f1"] is None:
            continue
        idx = min(int(s["f1"] * 10), 10)
        bins[idx] += 1
    return bins


def _low_f1_list(rows: List[Dict[str, Any]], score_key: str, threshold: float = 0.5) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        s = r.get(score_key)
        if s is None:
            continue
        if score_key == "folio_faithfulness":
            if s.get("parse_error"):
                out.append({
                    "story_id": r["story_id"], "nl": r["nl"],
                    "f1": None, "reason": "parse_error",
                    "canonical_fol": r["canonical_fol"],
                    "gold_fol_raw": s.get("gold_fol_raw"),
                    "top_formula_case": r["top_formula_case"],
                    "structural_class": r["structural_class"],
                })
                continue
            inner = s.get("score")
            if inner is None:
                continue
            f1 = inner["f1"]
        else:
            f1 = s["f1"]
        if f1 is None or f1 >= threshold:
            continue
        record: Dict[str, Any] = {
            "story_id": r["story_id"], "nl": r["nl"],
            "f1": f1,
            "recall": inner["recall"] if score_key == "folio_faithfulness" else s["recall"],
            "precision": inner["precision"] if score_key == "folio_faithfulness" else s["precision"],
            "canonical_fol": r["canonical_fol"],
            "top_formula_case": r["top_formula_case"],
            "structural_class": r["structural_class"],
        }
        if score_key == "folio_faithfulness":
            record["gold_fol_raw"] = s.get("gold_fol_raw")
            record["gold_fol_normalized"] = s.get("gold_fol_normalized")
        out.append(record)
    return sorted(out, key=lambda x: (x["f1"] is None, x.get("f1") or -1))


def aggregate(results: Dict[str, Any], total_premises: int) -> Dict[str, Any]:
    per_pair = results["per_pair"]
    failures = results["failures"]

    by_top = defaultdict(list)
    by_struct = defaultdict(list)
    for row in per_pair:
        by_top[row["top_formula_case"]].append(row)
        by_struct[row["structural_class"]].append(row)

    def build(score_key: str) -> Dict[str, Any]:
        return {
            "overall": _summarize(per_pair, score_key),
            "by_top_formula_case": {k: _summarize(v, score_key) for k, v in by_top.items()},
            "by_structural_class": {k: _summarize(v, score_key) for k, v in by_struct.items()},
            "f1_histogram_bins_0_to_1_by_0p1": _f1_histogram(per_pair, score_key),
            "low_f1_review_list": _low_f1_list(per_pair, score_key),
        }

    return {
        "n_pairs_total": total_premises,
        "n_evaluated": len(per_pair),
        "n_failures": len(failures),
        "extraction_failure_rate": len(failures) / total_premises if total_premises else 0.0,
        "runtime_seconds": results["runtime_seconds"],
        "self_consistency": build("self_consistency"),
        "folio_faithfulness": build("folio_faithfulness"),
        "per_pair": per_pair,
        "failures": failures,
    }


# ── Self-consistency gate check ─────────────────────────────────────────────

def self_consistency_gate(agg: Dict[str, Any]) -> Dict[str, Any]:
    """Only the self-consistency measurement has pass/fail thresholds
    (§17 Amendment H). FOLIO-faithfulness is descriptive."""
    sc = agg["self_consistency"]
    overall = sc["overall"]
    by_case = sc["by_top_formula_case"]

    def check(label: str, value: Optional[float], threshold: float, op: str = ">=") -> Dict[str, Any]:
        ok = value is not None and value >= threshold
        return {"label": label, "value": value, "threshold": threshold, "pass": bool(ok)}

    checks = [
        check("self_consistency.overall.mean_recall >= 0.98", overall.get("mean_recall"), 0.98),
    ]
    for case in ("atomic", "quantification", "connective", "negation"):
        bucket = by_case.get(case, {})
        if bucket.get("count", 0) == 0:
            checks.append({"label": f"{case}.mean_recall >= 0.95", "value": None,
                           "threshold": 0.95, "pass": True, "note": "no premises in class"})
            continue
        checks.append(check(f"{case}.mean_recall >= 0.95", bucket.get("mean_recall"), 0.95))

    # Extraction failure rate
    fail_rate = agg["extraction_failure_rate"]
    checks.append({
        "label": "extraction_failure_rate < 0.10",
        "value": fail_rate, "threshold": 0.10,
        "pass": fail_rate < 0.10,
    })
    return {"checks": checks, "all_pass": all(c["pass"] for c in checks)}


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="Evaluate only the first N premises (debugging).")
    ap.add_argument("--timeout-s", type=int, default=10)
    ap.add_argument("--output", type=str, default="reports/folio_agreement.json")
    ap.add_argument("--split", type=str, default="validation",
                    help="FOLIO split to evaluate.")
    args = ap.parse_args()

    sys.stderr.write(f"[phase5] loading tasksource/folio split={args.split}\n")
    pairs = load_folio_premise_pairs(args.split)
    total = len(pairs)
    sys.stderr.write(f"[phase5] {total} unique premise pairs\n")

    if args.limit:
        pairs = pairs[: args.limit]
        sys.stderr.write(f"[phase5] limit active: evaluating {len(pairs)} pairs\n")

    client = FrozenClient(OpenAI())
    results = run(pairs, client, timeout_s=args.timeout_s)
    agg = aggregate(results, total_premises=total)
    agg["self_consistency_gate"] = self_consistency_gate(agg)

    out_path = _REPO_ROOT / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(agg, indent=2, default=str))
    sys.stderr.write(f"[phase5] wrote {out_path}\n")

    # Brief summary.
    def _fmt(x):
        return f"{x:.3f}" if isinstance(x, float) else str(x)

    sc_overall = agg["self_consistency"]["overall"]
    ff_overall = agg["folio_faithfulness"]["overall"]
    sys.stderr.write(
        f"[phase5] self-consistency: mean_recall={_fmt(sc_overall.get('mean_recall'))} "
        f"mean_f1={_fmt(sc_overall.get('mean_f1_where_defined'))}\n"
    )
    sys.stderr.write(
        f"[phase5] folio-faithfulness: mean_recall={_fmt(ff_overall.get('mean_recall'))} "
        f"mean_f1_where_defined={_fmt(ff_overall.get('mean_f1_where_defined'))}\n"
    )
    sys.stderr.write("[phase5] self-consistency gate:\n")
    for c in agg["self_consistency_gate"]["checks"]:
        flag = "PASS" if c["pass"] else "FAIL"
        sys.stderr.write(f"  {flag}  {c['label']}  value={c.get('value')}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
