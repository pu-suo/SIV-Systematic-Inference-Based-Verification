"""Score the locked Exp B candidate set against the v3 test suites and
compute the Spearman ρ regression.

Mirrors the soft-mode scoring used in ``stage4_regenerate.py`` and
``score_candidates.py``: rewrites the v3 suite into the candidate's
vocabulary via embedding-based symbol alignment, then runs Vampire on
each rewritten probe.

Methodology for ρ matches ``stage4_regenerate.compute_rho``:
  - per-premise Spearman correlation between SIV recall and the
    ground-truth ranking ``gold=1, overstrong/partial=2, overweak=3,
    gibberish=4``
  - mean and 95% bootstrap CI over the per-premise correlations

Locked v2 baseline: ρ = 0.8543 (README) / 0.8563 (stage4b_regeneration).
Hard gate per the implementation plan: v3 ρ ∈ [v2 - 0.05, v2 + 0.05] —
i.e. roughly [0.804, 0.904].

Usage:
    python scripts/exp_b_v3_regression.py
    python scripts/exp_b_v3_regression.py \
      --v3-suites reports/test_suites/test_suites_v3_sample100.jsonl
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats as scipy_stats

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from siv.aligner import (
    align_symbols,
    extract_symbols_from_fol,
    rewrite_fol_strings,
    rewrite_test_suite,
)
from siv.contrastive_generator import derive_witness_axioms
from siv.fol_utils import is_valid_fol, normalize_fol_string
from siv.schema import SentenceExtraction, TestSuite, UnitTest
from siv.scorer import score
from siv.vampire_interface import is_vampire_available


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


_LOCKED_V2_RHO = 0.8543  # README headline
_GATE_BAND = 0.05


def _load_v3_suites(path: Path) -> dict:
    suites = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        suites[e["premise_id"]] = e
    return suites


def _reconstruct_test_suite(entry: dict) -> TestSuite:
    extraction = SentenceExtraction(**entry["extraction_json"])
    positives = [
        UnitTest(fol=t["fol"], kind=t["kind"]) for t in entry["positives"]
    ]
    contrastives = [
        UnitTest(
            fol=t["fol"],
            kind=t["kind"],
            mutation_kind=t.get("mutation_kind"),
            probe_relation=t.get("probe_relation"),
        )
        for t in entry["contrastives"]
    ]
    return TestSuite(
        extraction=extraction,
        positives=positives,
        contrastives=contrastives,
    )


def _score_v3_soft(suite: TestSuite, canonical_fol: str, candidate_fol: str, timeout_s: int = 10):
    siv_symbols = extract_symbols_from_fol(canonical_fol)
    cand_symbols = extract_symbols_from_fol(candidate_fol)
    alignment = align_symbols(siv_symbols, cand_symbols, threshold=0.6)
    rewritten_suite = rewrite_test_suite(suite, alignment)
    raw_witnesses = derive_witness_axioms(suite.extraction)
    rewritten_witnesses = rewrite_fol_strings(raw_witnesses, alignment)
    return score(
        rewritten_suite, candidate_fol,
        timeout_s=timeout_s,
        witness_axioms_override=rewritten_witnesses,
    )


def compute_rho(scored_rows: list) -> dict:
    """Per-premise Spearman ρ + mean + 95% bootstrap CI. Identical to
    ``stage4_regenerate.compute_rho`` so the v2-vs-v3 comparison is apples
    to apples."""
    gt_ranks = {"gold": 1, "overstrong": 2, "partial": 2, "overweak": 3, "gibberish": 4}

    by_premise = defaultdict(dict)
    for row in scored_rows:
        recall = row.get("v3_recall")
        if recall is not None:
            by_premise[row["premise_id"]][row["candidate_type"]] = recall

    rho_per_premise = []
    premise_ids_used = []
    for pid, type_scores in by_premise.items():
        non_gold_types = [
            t for t in ("overstrong", "partial", "overweak", "gibberish")
            if t in type_scores
        ]
        if len(non_gold_types) < 3:
            continue
        premise_ids_used.append(pid)
        gt = [gt_ranks[t] for t in non_gold_types]
        m = [type_scores[t] for t in non_gold_types]
        if len(set(m)) > 1:
            rho, _ = scipy_stats.spearmanr(m, [-r for r in gt])
            rho_per_premise.append(rho)
        else:
            rho_per_premise.append(0.0)

    rhos = np.array(rho_per_premise)
    if len(rhos) == 0:
        return {"mean_rho": None, "ci_lo": None, "ci_hi": None, "n": 0}
    mean_rho = float(rhos.mean())
    rng = np.random.RandomState(42)
    boot = [rng.choice(rhos, size=len(rhos), replace=True).mean() for _ in range(1000)]
    return {
        "mean_rho": round(mean_rho, 4),
        "ci_lo": round(float(np.percentile(boot, 2.5)), 4),
        "ci_hi": round(float(np.percentile(boot, 97.5)), 4),
        "n": len(rhos),
        "per_premise": {pid: float(r) for pid, r in zip(premise_ids_used, rho_per_premise)},
    }


def main() -> int:
    if not is_vampire_available():
        print("ERROR: Vampire required.", file=sys.stderr)
        return 1

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--v3-suites",
        type=str,
        default=str(_REPO_ROOT / "reports" / "test_suites" / "test_suites_v3.jsonl"),
    )
    ap.add_argument(
        "--candidates",
        type=str,
        default=str(_REPO_ROOT / "reports" / "experiments" / "exp2" / "scored_candidates.jsonl"),
    )
    ap.add_argument(
        "--output",
        type=str,
        default=str(_REPO_ROOT / "reports" / "v3_exp_b_regression.json"),
    )
    ap.add_argument("--timeout-s", type=int, default=10)
    args = ap.parse_args()

    suites = _load_v3_suites(Path(args.v3_suites))
    sys.stderr.write(f"[regress] loaded {len(suites)} v3 suites\n")

    candidates = []
    for line in Path(args.candidates).read_text().splitlines():
        if line.strip():
            candidates.append(json.loads(line))
    sys.stderr.write(f"[regress] loaded {len(candidates)} candidates\n")

    scored_rows = []
    skipped_no_suite = 0
    skipped_invalid = 0
    skipped_error = 0
    t0 = time.time()

    for i, cand in enumerate(candidates):
        pid = cand["premise_id"]
        ctype = cand["candidate_type"]
        candidate_fol = cand["candidate_fol"]

        suite_entry = suites.get(pid)
        if suite_entry is None:
            skipped_no_suite += 1
            continue

        canonical_fol = suite_entry["canonical_fol"]
        # gold is its own canonical
        if ctype == "gold":
            cand_norm = canonical_fol
        else:
            cand_norm = normalize_fol_string(candidate_fol)
            if not cand_norm or not is_valid_fol(cand_norm):
                skipped_invalid += 1
                continue

        try:
            suite = _reconstruct_test_suite(suite_entry)
            report = _score_v3_soft(
                suite, canonical_fol, cand_norm, timeout_s=args.timeout_s,
            )
            scored_rows.append({
                "premise_id": pid,
                "candidate_type": ctype,
                "v3_recall": report.recall,
                "v3_precision": report.precision,
                "v3_f1": report.f1,
            })
        except Exception as e:
            skipped_error += 1
            logger.warning("scoring %s/%s failed: %s", pid, ctype, e)

        if (i + 1) % 50 == 0 or (i + 1) == len(candidates):
            sys.stderr.write(
                f"[regress] {i+1}/{len(candidates)} "
                f"scored={len(scored_rows)} no_suite={skipped_no_suite} "
                f"invalid={skipped_invalid} error={skipped_error} "
                f"elapsed={time.time()-t0:.0f}s\n"
            )

    rho = compute_rho(scored_rows)

    # Mean recall by candidate type (sanity).
    by_type = defaultdict(list)
    for row in scored_rows:
        if row["v3_recall"] is not None:
            by_type[row["candidate_type"]].append(row["v3_recall"])
    mean_by_type = {
        t: float(np.mean(by_type[t])) if by_type[t] else None
        for t in ("gold", "overstrong", "partial", "overweak", "gibberish")
    }

    gate_lo = _LOCKED_V2_RHO - _GATE_BAND
    gate_hi = _LOCKED_V2_RHO + _GATE_BAND
    if rho["mean_rho"] is None:
        gate = "INSUFFICIENT_DATA"
    elif gate_lo <= rho["mean_rho"] <= gate_hi:
        gate = "PASS"
    else:
        gate = "FAIL"

    summary = {
        "v3_rho": rho,
        "locked_v2_rho": _LOCKED_V2_RHO,
        "gate_band": [gate_lo, gate_hi],
        "gate": gate,
        "mean_recall_by_type": mean_by_type,
        "candidates_scored": len(scored_rows),
        "candidates_skipped_no_suite": skipped_no_suite,
        "candidates_skipped_invalid": skipped_invalid,
        "candidates_skipped_error": skipped_error,
        "elapsed_s": round(time.time() - t0, 1),
    }

    Path(args.output).write_text(json.dumps(summary, indent=2))

    print()
    print("=" * 70)
    print("v3 Exp B regression")
    print("=" * 70)
    print(f"  Locked v2 ρ:           {_LOCKED_V2_RHO}")
    print(f"  Gate band:             [{gate_lo:.4f}, {gate_hi:.4f}]")
    if rho["mean_rho"] is not None:
        print(f"  v3 ρ:                  {rho['mean_rho']:.4f} "
              f"[{rho['ci_lo']:.4f}, {rho['ci_hi']:.4f}] (n={rho['n']})")
    print(f"  Gate:                  {gate}")
    print()
    print(f"  Mean v3 recall by candidate type:")
    for t in ("gold", "overstrong", "partial", "overweak", "gibberish"):
        v = mean_by_type[t]
        if v is not None:
            print(f"    {t:12s}: {v:.4f} (n={len(by_type[t])})")
    print()
    print(f"  Report saved to: {args.output}")
    return 0 if gate == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
