"""Regenerate the locked test-suite artifact under v3 settings.

The original frozen artifact at ``reports/test_suites/test_suites.jsonl``
(1,471 premises) is *not* overwritten. The v3 artifact is written
alongside as ``reports/test_suites/test_suites_v3.jsonl``.

V3 differences vs. v2 (the original artifact):
  - relaxed contrastive gate (admits ``strictly_stronger`` mutants)
  - new positive rules: contrapositive, de Morgan, XOR-split, DN-elim,
    universal instantiation
  - new contrastive operators: disjunct_drop, converse, scope_swap,
    equality_drop
  - AST-canonical dedup
  - probe_relation tag on each contrastive

Optional flags:
  - ``SIV_COMPOSE_OPERATORS=1`` enables compositional probes (capped per
    premise); off by default in CI, recommended on for the locked v3 run.
  - ``SIV_DEDUPE_PROBES=1`` enables Vampire-equivalence dedup; expensive,
    on for the locked v3 run only.

Usage:
    python scripts/regenerate_v3.py
    python scripts/regenerate_v3.py --limit 100 --output reports/test_suites/test_suites_v3_sample.jsonl
    SIV_COMPOSE_OPERATORS=1 python scripts/regenerate_v3.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from siv.compiler import compile_canonical_fol
from siv.contrastive_generator import derive_witness_axioms
from siv.fol_parser import parse_gold_fol
from siv.gold_suite_generator import generate_test_suite_from_gold
from siv.invariants import (
    check_contrastive_soundness,
    check_entailment_monotonicity,
)
from siv.vampire_interface import is_vampire_available


_LOCKED = _REPO_ROOT / "reports" / "test_suites" / "test_suites.jsonl"
_DEFAULT_OUT = _REPO_ROOT / "reports" / "test_suites" / "test_suites_v3.jsonl"


def _load_locked_index() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for line in _LOCKED.read_text().splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        out[entry["premise_id"]] = entry
    return out


def _serialize_unit_test(t):
    d = {
        "fol": t.fol,
        "kind": t.kind,
    }
    if t.mutation_kind is not None:
        d["mutation_kind"] = t.mutation_kind
    if t.probe_relation is not None:
        d["probe_relation"] = t.probe_relation
    return d


def _serialize_suite_entry(
    locked_entry: Dict[str, Any],
    suite,
    structural_class: str,
) -> Dict[str, Any]:
    return {
        "nl": locked_entry["nl"],
        "canonical_fol": compile_canonical_fol(suite.extraction),
        "structural_class": structural_class,
        "positives": [_serialize_unit_test(p) for p in suite.positives],
        "contrastives": [_serialize_unit_test(c) for c in suite.contrastives],
        "witness_axioms": derive_witness_axioms(suite.extraction),
        "extraction_json": suite.extraction.model_dump(),
        "premise_id": locked_entry["premise_id"],
        "story_id": locked_entry["story_id"],
        "gold_fol": locked_entry["gold_fol"],
    }


def main() -> int:
    if not is_vampire_available():
        print("ERROR: Vampire required.", file=sys.stderr)
        return 1

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=str, default=str(_DEFAULT_OUT))
    ap.add_argument("--limit", type=int, default=None,
                    help="Process only the first N premises (for sampling).")
    ap.add_argument("--start", type=int, default=0,
                    help="Skip the first START premises (resume support).")
    ap.add_argument("--timeout-s", type=int, default=5,
                    help="Vampire timeout per check (default 5).")
    ap.add_argument("--no-soundness-check", action="store_true",
                    help="Skip per-premise C9a/C9b checks (faster; less safe).")
    args = ap.parse_args()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    locked = _load_locked_index()
    premise_ids = sorted(locked.keys())
    if args.start:
        premise_ids = premise_ids[args.start:]
    if args.limit:
        premise_ids = premise_ids[:args.limit]

    sys.stderr.write(
        f"[v3] regenerating {len(premise_ids)} premises -> {out_path}\n"
    )

    n_ok = 0
    n_failed_parse = 0
    n_failed_round_trip = 0
    n_failed_c9a = 0
    n_failed_c9b = 0
    legacy_probe_drops = 0  # additive-guarantee violations
    sum_pos = 0
    sum_con = 0
    sum_pos_strictly_stronger = 0  # contrastives by relation
    sum_con_incompatible = 0
    sum_con_strictly_stronger = 0
    t0 = time.time()

    # Open in append mode if --start > 0 to support resume.
    mode = "a" if args.start else "w"
    with out_path.open(mode) as f:
        for i, pid in enumerate(premise_ids):
            entry = locked[pid]
            try:
                result = generate_test_suite_from_gold(
                    fol_string=entry["gold_fol"],
                    nl=entry["nl"],
                    verify_round_trip=True,
                    with_contrastives=True,
                    timeout_s=args.timeout_s,
                )
            except Exception as e:
                sys.stderr.write(f"[v3] {pid}: exception {e}\n")
                n_failed_parse += 1
                continue

            if result.suite is None:
                if "round_trip" in (result.error or ""):
                    n_failed_round_trip += 1
                else:
                    n_failed_parse += 1
                sys.stderr.write(f"[v3] {pid}: skipped — {result.error}\n")
                continue

            suite = result.suite

            if not args.no_soundness_check:
                ok_a, reason_a = check_entailment_monotonicity(
                    suite.extraction, suite, timeout_s=args.timeout_s,
                )
                if not ok_a:
                    n_failed_c9a += 1
                    sys.stderr.write(f"[v3] {pid}: C9a FAIL {reason_a}\n")
                    continue
                ok_b, reason_b = check_contrastive_soundness(
                    suite, timeout_s=args.timeout_s,
                )
                if not ok_b:
                    n_failed_c9b += 1
                    sys.stderr.write(f"[v3] {pid}: C9b FAIL {reason_b}\n")
                    continue

            # Additive-guarantee check vs the legacy artifact. Only meaningful
            # when the legacy and new canonical FOL agree as strings — many
            # legacy entries were emitted by an older parser whose predicate
            # naming/extraction differs from the current one (e.g. equality
            # canonicalization, conjunct splitting), and a probe-by-probe
            # subset comparison is undefined across that change.
            legacy_canonical = entry.get("canonical_fol", "")
            new_canonical = compile_canonical_fol(suite.extraction)
            if legacy_canonical == new_canonical:
                legacy_pos = {p["fol"] for p in entry.get("positives", [])}
                legacy_con = {c["fol"] for c in entry.get("contrastives", [])}
                new_pos = {p.fol for p in suite.positives}
                new_con = {c.fol for c in suite.contrastives}
                if not legacy_pos.issubset(new_pos):
                    legacy_probe_drops += 1
                    missing = legacy_pos - new_pos
                    sys.stderr.write(
                        f"[v3] {pid}: WARN dropped {len(missing)} legacy "
                        f"positive(s) under same canonical\n"
                    )
                if not legacy_con.issubset(new_con):
                    legacy_probe_drops += 1
                    missing = legacy_con - new_con
                    sys.stderr.write(
                        f"[v3] {pid}: WARN dropped {len(missing)} legacy "
                        f"contrastive(s) under same canonical\n"
                    )

            # Counts.
            sum_pos += len(suite.positives)
            sum_con += len(suite.contrastives)
            for c in suite.contrastives:
                relation = c.probe_relation or "incompatible"
                if relation == "incompatible":
                    sum_con_incompatible += 1
                elif relation == "strictly_stronger":
                    sum_con_strictly_stronger += 1

            structural_class = entry.get("structural_class", "other")
            f.write(json.dumps(
                _serialize_suite_entry(entry, suite, structural_class),
                default=str,
            ) + "\n")
            n_ok += 1

            if (i + 1) % 25 == 0 or (i + 1) == len(premise_ids):
                dt = time.time() - t0
                sys.stderr.write(
                    f"[v3] {i+1}/{len(premise_ids)} ok={n_ok} "
                    f"parse_fail={n_failed_parse} rt_fail={n_failed_round_trip} "
                    f"c9a_fail={n_failed_c9a} c9b_fail={n_failed_c9b} "
                    f"legacy_drops={legacy_probe_drops} "
                    f"elapsed={dt:.0f}s\n"
                )

    summary = {
        "n_processed": len(premise_ids),
        "n_ok": n_ok,
        "n_failed_parse": n_failed_parse,
        "n_failed_round_trip": n_failed_round_trip,
        "n_failed_c9a": n_failed_c9a,
        "n_failed_c9b": n_failed_c9b,
        "legacy_probe_drops": legacy_probe_drops,
        "mean_positives": sum_pos / n_ok if n_ok else 0,
        "mean_contrastives": sum_con / n_ok if n_ok else 0,
        "contrastives_by_relation": {
            "incompatible": sum_con_incompatible,
            "strictly_stronger": sum_con_strictly_stronger,
        },
        "elapsed_s": round(time.time() - t0, 1),
    }
    summary_path = out_path.parent / (out_path.stem + "_summary.json")
    summary_path.write_text(json.dumps(summary, indent=2))
    sys.stderr.write(f"[v3] summary -> {summary_path}\n")
    sys.stderr.write(json.dumps(summary, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
