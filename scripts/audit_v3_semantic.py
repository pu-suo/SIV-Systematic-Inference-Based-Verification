"""Semantic audit of v3 test suites.

For every premise in ``reports/test_suites/test_suites_v3.jsonl`` verify
that the positive and contrastive probes hold the soundness property the
metric requires:

  - **Positive (C9a)**: ``gold ∧ witnesses ⊨ positive``
    Vampire verdict on ``vampire_check(gold, positive, "entails", axioms=witnesses)``
    must be ``"unsat"`` (entailment proven). ``"sat"`` is a hard failure --
    the metric would penalise a faithful translation that happens to fail
    a positive it should pass. ``"timeout"``/``"unknown"`` is reported as a
    soft warning (the prover ran out of time, but the probe is not
    necessarily wrong).

  - **Contrastive labelled ``incompatible`` (C9b)**:
    ``vampire_check(gold, contrastive, "unsat", axioms=witnesses) == "unsat"``.
    ``"sat"`` is a hard failure -- gold does not actually contradict the
    mutant, so the metric would reward a faithful translation that
    coincidentally agrees with the mutant.

  - **Contrastive labelled ``strictly_stronger``**:
      Check B: ``vampire_check(contrastive, gold, "entails", axioms=witnesses) == "unsat"``
        (mutant entails gold).
      Check C: ``vampire_check(gold, contrastive, "entails", axioms=witnesses) == "sat"``
        (gold does NOT entail mutant).
    Both must hold. ``B="sat"`` is a hard failure (mutant is logically
    independent of gold or weaker than gold). ``C="unsat"`` is a hard
    failure (mutant is equivalent to gold).

Outputs:
  - ``reports/v3_semantic_audit.json``: per-premise verdicts and a summary.
  - stdout: counts of pass/fail/unknown per category, plus the first few
    failing examples for each failure mode.

Parallelism: uses a process pool. Each premise's probes are checked
serially within a worker (so witnesses get parsed once); workers run
across premises in parallel.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO))

from siv.vampire_interface import vampire_check


def audit_one(entry: Dict[str, Any], timeout_s: int) -> Dict[str, Any]:
    pid = entry.get("premise_id") or entry.get("nl", "")[:40]
    gold = entry["canonical_fol"]
    witnesses = entry.get("witness_axioms", []) or []

    out: Dict[str, Any] = {
        "premise_id": pid,
        "positives": [],
        "contrastives": [],
    }

    for p in entry["positives"]:
        v = vampire_check(gold, p["fol"], check="entails", axioms=witnesses, timeout=timeout_s)
        verdict = "pass" if v == "unsat" else ("fail" if v == "sat" else "unknown")
        out["positives"].append({"fol": p["fol"], "vampire": v, "verdict": verdict})

    for c in entry["contrastives"]:
        rel = c.get("probe_relation") or "incompatible"
        cfol = c["fol"]
        kind = c.get("mutation_kind", "?")
        if rel == "incompatible":
            v = vampire_check(gold, cfol, check="unsat", axioms=witnesses, timeout=timeout_s)
            verdict = "pass" if v == "unsat" else ("fail" if v == "sat" else "unknown")
            out["contrastives"].append({
                "fol": cfol, "relation": rel, "mutation_kind": kind,
                "check_a": v, "verdict": verdict,
            })
        else:  # strictly_stronger
            vb = vampire_check(cfol, gold, check="entails", axioms=witnesses, timeout=timeout_s)
            vc = vampire_check(gold, cfol, check="entails", axioms=witnesses, timeout=timeout_s)
            # B must be "unsat" (mutant entails gold);
            # C must be "sat"   (gold does NOT entail mutant).
            if vb == "unsat" and vc == "sat":
                verdict = "pass"
            elif vb == "sat" or vc == "unsat":
                verdict = "fail"
            else:
                verdict = "unknown"
            out["contrastives"].append({
                "fol": cfol, "relation": rel, "mutation_kind": kind,
                "check_b": vb, "check_c": vc, "verdict": verdict,
            })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--suites",
        default=str(_REPO / "reports" / "test_suites" / "test_suites_v3.jsonl"),
    )
    ap.add_argument("--out", default=str(_REPO / "reports" / "v3_semantic_audit.json"))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--timeout-s", type=int, default=5)
    ap.add_argument("--limit", type=int, default=None,
                    help="Audit only the first N premises (smoke-test).")
    args = ap.parse_args()

    suites = []
    for line in Path(args.suites).read_text().splitlines():
        if line.strip():
            suites.append(json.loads(line))
    if args.limit:
        suites = suites[: args.limit]
    n = len(suites)

    print(f"Auditing {n} premises with {args.workers} workers, timeout={args.timeout_s}s")
    t0 = time.time()

    results: List[Dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(audit_one, s, args.timeout_s): i for i, s in enumerate(suites)}
        done = 0
        for fut in as_completed(futs):
            results.append(fut.result())
            done += 1
            if done % 50 == 0 or done == n:
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed else 0
                eta = (n - done) / rate if rate else 0
                print(f"  [{done}/{n}] elapsed={elapsed:.0f}s rate={rate:.1f}/s eta={eta:.0f}s",
                      flush=True)

    # Aggregate
    n_pos = n_pos_fail = n_pos_unknown = 0
    n_inc = n_inc_fail = n_inc_unknown = 0
    n_str = n_str_fail = n_str_unknown = 0
    pos_failures: List[Dict[str, Any]] = []
    inc_failures: List[Dict[str, Any]] = []
    str_failures: List[Dict[str, Any]] = []
    pos_unknown_examples: List[Dict[str, Any]] = []
    str_unknown_examples: List[Dict[str, Any]] = []

    for r in results:
        for p in r["positives"]:
            n_pos += 1
            if p["verdict"] == "fail":
                n_pos_fail += 1
                pos_failures.append({"premise_id": r["premise_id"], **p})
            elif p["verdict"] == "unknown":
                n_pos_unknown += 1
                if len(pos_unknown_examples) < 5:
                    pos_unknown_examples.append({"premise_id": r["premise_id"], **p})
        for c in r["contrastives"]:
            if c["relation"] == "incompatible":
                n_inc += 1
                if c["verdict"] == "fail":
                    n_inc_fail += 1
                    inc_failures.append({"premise_id": r["premise_id"], **c})
                elif c["verdict"] == "unknown":
                    n_inc_unknown += 1
            else:
                n_str += 1
                if c["verdict"] == "fail":
                    n_str_fail += 1
                    str_failures.append({"premise_id": r["premise_id"], **c})
                elif c["verdict"] == "unknown":
                    n_str_unknown += 1
                    if len(str_unknown_examples) < 5:
                        str_unknown_examples.append({"premise_id": r["premise_id"], **c})

    summary = {
        "n_premises": n,
        "positives": {
            "total": n_pos,
            "fail": n_pos_fail,
            "unknown": n_pos_unknown,
            "pass": n_pos - n_pos_fail - n_pos_unknown,
        },
        "contrastives_incompatible": {
            "total": n_inc,
            "fail": n_inc_fail,
            "unknown": n_inc_unknown,
            "pass": n_inc - n_inc_fail - n_inc_unknown,
        },
        "contrastives_strictly_stronger": {
            "total": n_str,
            "fail": n_str_fail,
            "unknown": n_str_unknown,
            "pass": n_str - n_str_fail - n_str_unknown,
        },
        "elapsed_s": round(time.time() - t0, 1),
    }

    Path(args.out).write_text(json.dumps({
        "summary": summary,
        "pos_failures": pos_failures,
        "inc_failures": inc_failures,
        "str_failures": str_failures,
        "pos_unknown_examples": pos_unknown_examples,
        "str_unknown_examples": str_unknown_examples,
        "results": results,
    }, indent=2))

    print()
    print("=" * 70)
    print("SEMANTIC AUDIT SUMMARY")
    print("=" * 70)
    print(json.dumps(summary, indent=2))
    print()

    if pos_failures:
        print(f"\nPositive failures (gold does NOT entail positive) [{len(pos_failures)}]:")
        for f in pos_failures[:10]:
            print(f"  [{f['premise_id']}] vampire={f['vampire']}")
            print(f"    fol: {f['fol']}")
    if inc_failures:
        print(f"\nIncompatible-contrastive failures (gold ∧ mutant SAT) [{len(inc_failures)}]:")
        for f in inc_failures[:10]:
            print(f"  [{f['premise_id']}] mutation={f['mutation_kind']}  check_a={f['check_a']}")
            print(f"    fol: {f['fol']}")
    if str_failures:
        print(f"\nStrictly-stronger contrastive failures [{len(str_failures)}]:")
        for f in str_failures[:10]:
            print(f"  [{f['premise_id']}] mutation={f['mutation_kind']}  B={f['check_b']}  C={f['check_c']}")
            print(f"    fol: {f['fol']}")

    hard_fail = n_pos_fail + n_inc_fail + n_str_fail
    if hard_fail == 0:
        print("\nGate: PASS  (zero hard failures)")
        return 0
    print(f"\nGate: FAIL  ({hard_fail} hard failures)")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
