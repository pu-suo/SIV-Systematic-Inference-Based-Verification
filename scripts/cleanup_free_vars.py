"""One-shot cache cleanup: remove premises with free variables in canonical FOL.

Pre-work A (EXPERIMENT_SPEC.md): validates each cached canonical against the
post-fix free-variable check. Rows that fail are written to a separate failures
file and removed from the active cache.

Also handles Pre-work B (probe cleanup): validates each positive probe FOL and
removes probes with free variables. Logs contrastive eligibility changes.

Usage:
    python scripts/cleanup_free_vars.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from siv.fol_utils import free_individual_variables

CACHE_PATH = _REPO_ROOT / "reports" / "test_suites" / "test_suites.jsonl"
CLEANED_PATH = _REPO_ROOT / "reports" / "test_suites" / "test_suites.cleaned.jsonl"
FAILURES_PATH = _REPO_ROOT / "reports" / "test_suites" / "test_suites.failures.post_fix.json"


def _extract_declared_constants(row: dict) -> frozenset:
    ej = row.get("extraction_json", {})
    return frozenset(c["id"] for c in ej.get("constants", []))


def main() -> None:
    # ── Phase 1: Read all rows ──────────────────────────────────────────────
    rows = []
    with open(CACHE_PATH) as f:
        for line in f:
            rows.append(json.loads(line))
    total = len(rows)
    print(f"Loaded {total} rows from {CACHE_PATH.name}")

    # ── Phase 2: Validate canonical FOL ─────────────────────────────────────
    clean_rows = []
    failures = []
    for row in rows:
        constants = _extract_declared_constants(row)
        fv = free_individual_variables(row["canonical_fol"], constants)
        if fv:
            failures.append({
                "premise_id": row["premise_id"],
                "story_id": row.get("story_id"),
                "nl": row.get("nl", ""),
                "error_kind": "free_variable_in_canonical_post_fix",
                "error": f"Free individual variables in canonical FOL: {sorted(fv)}",
                "canonical_fol": row["canonical_fol"],
            })
        else:
            clean_rows.append(row)

    dropped_canonical = len(failures)
    print(f"Canonical FOL free-variable check: {dropped_canonical} rows dropped, "
          f"{len(clean_rows)} rows retained")

    # ── Phase 3: Validate positive probes (Pre-work B cleanup) ──────────────
    total_probes_removed = 0
    contrastive_eligible_before = 0
    contrastive_eligible_after = 0
    probes_removed_log = []

    for row in clean_rows:
        had_contrastives = len(row.get("contrastives", [])) > 0
        if had_contrastives:
            contrastive_eligible_before += 1

        positives = row.get("positives", [])
        clean_positives = []
        removed_count = 0
        for p in positives:
            fv = free_individual_variables(p["fol"])
            if fv:
                removed_count += 1
                total_probes_removed += 1
            else:
                clean_positives.append(p)
        if removed_count > 0:
            probes_removed_log.append(
                f"  {row['premise_id']}: removed {removed_count} probe(s)"
            )
        row["positives"] = clean_positives

        # Also check contrastives for free variables
        contrastives = row.get("contrastives", [])
        clean_contrastives = []
        for c in contrastives:
            fv = free_individual_variables(c["fol"])
            if fv:
                total_probes_removed += 1
            else:
                clean_contrastives.append(c)
        row["contrastives"] = clean_contrastives

        has_contrastives_now = len(row["contrastives"]) > 0
        if has_contrastives_now:
            contrastive_eligible_after += 1

    print(f"Probe cleanup: {total_probes_removed} probes removed across {len(probes_removed_log)} rows")
    if probes_removed_log:
        for line in probes_removed_log:
            print(line)
    print(f"Contrastive-eligible: {contrastive_eligible_before} -> {contrastive_eligible_after} "
          f"({contrastive_eligible_after / len(clean_rows) * 100:.1f}%)")

    # ── Phase 4: Write cleaned cache ────────────────────────────────────────
    with open(CLEANED_PATH, "w") as f:
        for row in clean_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote {len(clean_rows)} rows to {CLEANED_PATH.name}")

    # Verify by re-reading
    verify_count = 0
    with open(CLEANED_PATH) as f:
        for line in f:
            verify_count += 1
    assert verify_count == len(clean_rows), (
        f"Verification failed: wrote {len(clean_rows)} but read back {verify_count}"
    )
    print(f"Verified: {verify_count} rows read back correctly")

    # Atomic rename
    os.replace(CLEANED_PATH, CACHE_PATH)
    print(f"Atomic rename: {CLEANED_PATH.name} -> {CACHE_PATH.name}")

    # ── Phase 5: Write failures ─────────────────────────────────────────────
    if failures:
        with open(FAILURES_PATH, "w") as f:
            json.dump(failures, f, indent=2, ensure_ascii=False)
        print(f"Wrote {len(failures)} failures to {FAILURES_PATH.name}")

    # ── Summary ─────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"  Original rows:       {total}")
    print(f"  Dropped (canonical): {dropped_canonical}")
    print(f"  Probes removed:      {total_probes_removed}")
    print(f"  Final rows:          {len(clean_rows)}")
    print(f"  Contrastive-eligible: {contrastive_eligible_after}/{len(clean_rows)} "
          f"({contrastive_eligible_after / len(clean_rows) * 100:.1f}%)")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
