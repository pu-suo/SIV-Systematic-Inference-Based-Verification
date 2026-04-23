"""Generate a diagnostic report of soft-mode alignment results.

For each premise, shows: alignment mappings, which tests passed/failed
as a result, and the scores. Writes a CSV for spreadsheet analysis and
prints a human-readable summary to stdout.

Usage:
    python scripts/soft_alignment_diagnostics.py
    python scripts/soft_alignment_diagnostics.py --input reports/folio_agreement_soft.json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

_REPO_ROOT = Path(__file__).parent.parent


def _fmt_pred_map(alignment: dict) -> str:
    """Format predicate alignment as compact string."""
    pm = alignment.get("predicate_map", {})
    if not pm:
        return "(none)"
    parts = []
    for siv, info in sorted(pm.items()):
        cand = info["candidate"]
        score = info["score"]
        tag = "=" if siv == cand else "~"
        parts.append(f"{siv} {tag}> {cand} ({score:.2f})")
    return " | ".join(parts)


def _fmt_const_map(alignment: dict) -> str:
    """Format constant alignment as compact string."""
    cm = alignment.get("constant_map", {})
    if not cm:
        return "(none)"
    parts = []
    for siv, info in sorted(cm.items()):
        cand = info["candidate"]
        score = info["score"]
        tag = "=" if siv == cand else "~"
        parts.append(f"{siv} {tag}> {cand} ({score:.2f})")
    return " | ".join(parts)


def _fmt_unaligned(alignment: dict) -> str:
    """Format unaligned symbols."""
    parts = []
    us = alignment.get("unaligned_siv_predicates", [])
    uc = alignment.get("unaligned_candidate_predicates", [])
    usc = alignment.get("unaligned_siv_constants", [])
    ucc = alignment.get("unaligned_candidate_constants", [])
    if us:
        parts.append(f"siv_preds: {', '.join(us)}")
    if uc:
        parts.append(f"cand_preds: {', '.join(uc)}")
    if usc:
        parts.append(f"siv_consts: {', '.join(usc)}")
    if ucc:
        parts.append(f"cand_consts: {', '.join(ucc)}")
    return " | ".join(parts) if parts else "(none)"


def _test_verdicts(per_test: List[Dict]) -> str:
    """Compact per-test verdict string."""
    parts = []
    for t in per_test:
        kind = "P" if t["kind"] == "positive" else "C"
        v = t["verdict"]
        if v == "entailed":
            flag = "PASS" if kind == "P" else "FAIL"
        elif v == "not_entailed":
            flag = "FAIL" if kind == "P" else "PASS"
        elif v == "no_contrastives":
            continue
        else:
            flag = v.upper()
        parts.append(f"{kind}:{flag}")
    return " ".join(parts)


def _failed_test_fols(per_test: List[Dict]) -> str:
    """FOL strings of failed positive tests (truncated)."""
    failed = []
    for t in per_test:
        if t["kind"] == "positive" and t["verdict"] != "entailed":
            fol = t["fol"]
            if len(fol) > 80:
                fol = fol[:77] + "..."
            failed.append(fol)
    return " || ".join(failed) if failed else "(all passed)"


def process(data: dict) -> List[Dict[str, Any]]:
    rows = []
    for p in data["per_pair"]:
        ff = p["folio_faithfulness"]
        alignment = ff.get("alignment")
        score = ff.get("score")

        if ff.get("parse_error") or score is None:
            rows.append({
                "story_id": p["story_id"],
                "nl": p["nl"][:100],
                "siv_fol": p["canonical_fol"][:80],
                "gold_fol": ff.get("gold_fol_normalized", "")[:80],
                "recall": None,
                "precision": None,
                "f1": None,
                "pred_alignments": "",
                "const_alignments": "",
                "unaligned": "",
                "test_verdicts": "PARSE_ERROR",
                "failed_tests": "",
                "n_identity_preds": "",
                "n_semantic_preds": "",
                "n_unaligned_siv_preds": "",
                "n_unaligned_cand_preds": "",
            })
            continue

        # Count alignment types
        n_identity = 0
        n_semantic = 0
        if alignment:
            for siv, info in alignment.get("predicate_map", {}).items():
                if siv == info["candidate"]:
                    n_identity += 1
                else:
                    n_semantic += 1

        rows.append({
            "story_id": p["story_id"],
            "nl": p["nl"][:100],
            "siv_fol": p["canonical_fol"][:80],
            "gold_fol": ff.get("gold_fol_normalized", "")[:80],
            "recall": score["recall"],
            "precision": score["precision"],
            "f1": score["f1"],
            "pred_alignments": _fmt_pred_map(alignment) if alignment else "",
            "const_alignments": _fmt_const_map(alignment) if alignment else "",
            "unaligned": _fmt_unaligned(alignment) if alignment else "",
            "test_verdicts": _test_verdicts(score["per_test_results"]),
            "failed_tests": _failed_test_fols(score["per_test_results"]),
            "n_identity_preds": n_identity,
            "n_semantic_preds": n_semantic,
            "n_unaligned_siv_preds": len(alignment.get("unaligned_siv_predicates", [])) if alignment else 0,
            "n_unaligned_cand_preds": len(alignment.get("unaligned_candidate_predicates", [])) if alignment else 0,
        })

    return rows


def print_summary(rows: List[Dict[str, Any]]) -> None:
    scored = [r for r in rows if r["recall"] is not None]
    if not scored:
        print("No scored premises.")
        return

    recalls = [r["recall"] for r in scored]
    f1s = [r["f1"] for r in scored if r["f1"] is not None]

    perfect = [r for r in scored if r["recall"] == 1.0]
    zero = [r for r in scored if r["recall"] == 0.0]
    partial = [r for r in scored if 0.0 < r["recall"] < 1.0]

    print(f"Total scored: {len(scored)}")
    print(f"  Perfect recall (1.0):  {len(perfect)} ({100*len(perfect)/len(scored):.1f}%)")
    print(f"  Partial recall:        {len(partial)} ({100*len(partial)/len(scored):.1f}%)")
    print(f"  Zero recall:           {len(zero)} ({100*len(zero)/len(scored):.1f}%)")
    print(f"  Mean recall: {sum(recalls)/len(recalls):.3f}")
    if f1s:
        print(f"  Mean F1:     {sum(f1s)/len(f1s):.3f}")

    # Alignment stats
    total_identity = sum(r["n_identity_preds"] for r in scored if isinstance(r["n_identity_preds"], int))
    total_semantic = sum(r["n_semantic_preds"] for r in scored if isinstance(r["n_semantic_preds"], int))
    total_unaligned_siv = sum(r["n_unaligned_siv_preds"] for r in scored if isinstance(r["n_unaligned_siv_preds"], int))
    total_unaligned_cand = sum(r["n_unaligned_cand_preds"] for r in scored if isinstance(r["n_unaligned_cand_preds"], int))

    print(f"\nPredicate alignment totals across all premises:")
    print(f"  Identity (exact match): {total_identity}")
    print(f"  Semantic (renamed):     {total_semantic}")
    print(f"  Unaligned SIV:          {total_unaligned_siv}")
    print(f"  Unaligned candidate:    {total_unaligned_cand}")

    # Breakdown: zero-recall premises — why?
    print(f"\n--- Zero-recall premises ({len(zero)}) ---")
    for r in zero[:15]:
        print(f"  [{r['story_id']}] {r['nl']}")
        print(f"    Alignments: {r['pred_alignments']}")
        print(f"    Unaligned:  {r['unaligned']}")
        print()
    if len(zero) > 15:
        print(f"  ... and {len(zero) - 15} more")

    # Partial recall — what failed?
    print(f"\n--- Partial-recall premises ({len(partial)}) ---")
    for r in sorted(partial, key=lambda x: x["recall"])[:15]:
        print(f"  [{r['story_id']}] recall={r['recall']:.2f}  {r['nl']}")
        print(f"    Alignments: {r['pred_alignments']}")
        print(f"    Failed:     {r['failed_tests']}")
        print()
    if len(partial) > 15:
        print(f"  ... and {len(partial) - 15} more")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=str,
                    default=str(_REPO_ROOT / "reports" / "folio_agreement_soft.json"))
    ap.add_argument("--output", type=str,
                    default=str(_REPO_ROOT / "reports" / "soft_alignment_diagnostics.csv"))
    args = ap.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    rows = process(data)

    # Write CSV
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {out_path} ({len(rows)} rows)\n")
    print_summary(rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
