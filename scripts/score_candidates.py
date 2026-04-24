"""Score candidate FOL translations against frozen SIV test suites.

Takes saved test suites (from generate_folio_test_suites.py) and saved
candidates (from generate_candidates.py), matches them by premise_id,
and runs Vampire scoring for each (test_suite, candidate) pair.

Supports both strict mode (SIV vocabulary) and soft mode (aligned
vocabulary via embedding-based symbol matching).

Usage:
    python scripts/score_candidates.py \
      --test-suites reports/human_study/test_suites.jsonl \
      --candidates reports/human_study/candidates.jsonl \
      --output reports/human_study/scored_candidates.jsonl

    # Limit for dry run:
    python scripts/score_candidates.py \
      --test-suites reports/human_study/test_suites.jsonl \
      --candidates reports/human_study/candidates.jsonl \
      --limit 20
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from siv.contrastive_generator import derive_witness_axioms
from siv.fol_utils import is_valid_fol, normalize_fol_string
from siv.schema import SentenceExtraction, TestSuite, UnitTest
from siv.scorer import ScoreReport, score


# ── Load artifacts ──────────────────────────────────────────────���────────────


def load_test_suites(path: Path) -> Dict[str, Dict[str, Any]]:
    """Load test suites keyed by premise_id."""
    suites = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        suites[entry["premise_id"]] = entry
    return suites


def load_candidates(path: Path) -> List[Dict[str, Any]]:
    """Load candidate list."""
    candidates = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        candidates.append(json.loads(line))
    return candidates


# ── Reconstruct TestSuite from saved dict ────────────────────────────────────


def _reconstruct_test_suite(suite_dict: Dict[str, Any]) -> TestSuite:
    """Rebuild a TestSuite Pydantic model from the saved JSON dict."""
    extraction = SentenceExtraction(**suite_dict["extraction_json"])

    positives = [
        UnitTest(fol=t["fol"], kind=t["kind"])
        for t in suite_dict["positives"]
    ]
    contrastives = [
        UnitTest(fol=t["fol"], kind=t["kind"], mutation_kind=t.get("mutation_kind"))
        for t in suite_dict["contrastives"]
    ]

    return TestSuite(
        extraction=extraction,
        positives=positives,
        contrastives=contrastives,
    )


# ── Scoring ──────────────────────────────────────────────────────────────────


def _score_record(report: ScoreReport) -> Dict[str, Any]:
    return {
        "recall": report.recall,
        "precision": report.precision,
        "f1": report.f1,
        "positives_entailed": report.positives_entailed,
        "positives_total": report.positives_total,
        "contrastives_rejected": report.contrastives_rejected,
        "contrastives_total": report.contrastives_total,
    }


def score_strict(
    suite: TestSuite,
    candidate_fol: str,
    timeout_s: int,
) -> Dict[str, Any]:
    """Score candidate against test suite in strict mode (SIV vocabulary)."""
    report = score(suite, candidate_fol, timeout_s=timeout_s)
    return _score_record(report)


def score_soft(
    suite: TestSuite,
    candidate_fol: str,
    canonical_fol: str,
    timeout_s: int,
) -> Dict[str, Any]:
    """Score candidate against test suite in soft mode (aligned vocabulary)."""
    from siv.aligner import (
        align_symbols,
        alignment_to_dict,
        extract_symbols_from_fol,
        rewrite_fol_strings,
        rewrite_test_suite,
    )

    siv_symbols = extract_symbols_from_fol(canonical_fol)
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
        **_score_record(report),
        "alignment": alignment_to_dict(alignment),
    }


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--test-suites", type=str, required=True,
                    help="Path to test_suites.jsonl")
    ap.add_argument("--candidates", type=str, required=True,
                    help="Path to candidates.jsonl")
    ap.add_argument("--output", type=str,
                    default=str(_REPO_ROOT / "reports" / "human_study" / "scored_candidates.jsonl"))
    ap.add_argument("--timeout-s", type=int, default=10)
    ap.add_argument("--limit", type=int, default=None,
                    help="Score only the first N candidates.")
    ap.add_argument("--mode", type=str, choices=["strict", "soft", "both"],
                    default="both",
                    help="Scoring mode (default: both).")
    args = ap.parse_args()

    # Load artifacts
    sys.stderr.write(f"[score] Loading test suites from {args.test_suites}\n")
    suites = load_test_suites(Path(args.test_suites))
    sys.stderr.write(f"[score] Loaded {len(suites)} test suites\n")

    sys.stderr.write(f"[score] Loading candidates from {args.candidates}\n")
    candidates = load_candidates(Path(args.candidates))
    sys.stderr.write(f"[score] Loaded {len(candidates)} candidates\n")

    if args.limit:
        candidates = candidates[:args.limit]
        sys.stderr.write(f"[score] --limit active: scoring {len(candidates)} candidates\n")

    # Score
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    scored = 0
    skipped = 0
    t0 = time.time()

    with out_path.open("w") as f:
        for i, cand in enumerate(candidates):
            premise_id = cand["premise_id"]
            candidate_fol = cand["candidate_fol"]

            # Find matching test suite
            suite_dict = suites.get(premise_id)
            if suite_dict is None:
                cand["score_strict"] = None
                cand["score_soft"] = None
                cand["score_error"] = "no_test_suite"
                f.write(json.dumps(cand, default=str) + "\n")
                skipped += 1
                continue

            # Check candidate validity
            cand_norm = normalize_fol_string(candidate_fol)
            if not candidate_fol or not is_valid_fol(cand_norm):
                cand["score_strict"] = None
                cand["score_soft"] = None
                cand["score_error"] = "candidate_parse_error"
                f.write(json.dumps(cand, default=str) + "\n")
                skipped += 1
                continue

            # Reconstruct TestSuite
            suite = _reconstruct_test_suite(suite_dict)
            canonical_fol = suite_dict["canonical_fol"]

            # Score strict
            if args.mode in ("strict", "both"):
                try:
                    cand["score_strict"] = score_strict(
                        suite, cand_norm, args.timeout_s,
                    )
                except Exception as e:
                    cand["score_strict"] = {"error": str(e)}
            else:
                cand["score_strict"] = None

            # Score soft
            if args.mode in ("soft", "both"):
                try:
                    cand["score_soft"] = score_soft(
                        suite, cand_norm, canonical_fol, args.timeout_s,
                    )
                except Exception as e:
                    cand["score_soft"] = {"error": str(e)}
            else:
                cand["score_soft"] = None

            cand["score_error"] = None
            f.write(json.dumps(cand, default=str) + "\n")
            scored += 1

            if (i + 1) % 50 == 0 or (i + 1) == len(candidates):
                dt = time.time() - t0
                sys.stderr.write(
                    f"[score] {i+1}/{len(candidates)} scored={scored} "
                    f"skipped={skipped} elapsed={dt:.0f}s\n"
                )

    sys.stderr.write(f"[score] Wrote {out_path} ({scored} scored, {skipped} skipped)\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
