"""Generate and freeze SIV test suites for all FOLIO premises.

For each premise in the specified FOLIO split, runs the full SIV pipeline
(LLM extraction → compilation → contrastive generation) and saves the
resulting test suite as a JSONL artifact.  This artifact is the frozen
ground truth for downstream scoring.

The extraction cache in ``.siv_cache/`` is used automatically, so premises
that were previously extracted will not trigger new LLM calls.

Usage:
    # Full train split:
    python scripts/generate_folio_test_suites.py --split train

    # Dry run (5 premises):
    python scripts/generate_folio_test_suites.py --split train --limit 5

    # Custom output path:
    python scripts/generate_folio_test_suites.py --split train --output my_suites.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).parent.parent
load_dotenv(_REPO_ROOT / ".env")

sys.path.insert(0, str(_REPO_ROOT))

import os
if not os.environ.get("OPENAI_API_KEY"):
    sys.stderr.write(
        f"OPENAI_API_KEY not set. Configure it in {_REPO_ROOT / '.env'}.\n"
    )
    sys.exit(2)

from datasets import load_dataset
from openai import OpenAI

from siv.frozen_client import FrozenClient
from siv.schema import SchemaViolation
from siv.test_suite_generator import generate_test_suite, serialize_test_suite


# ── Data Loading ─────────────────────────────────────────────────────────────


def _load_fewshot_exclusions() -> Set[str]:
    path = _REPO_ROOT / "prompts" / "extraction_examples.json"
    if path.exists():
        data = json.loads(path.read_text())
        return {e["sentence"] for e in data}
    return set()


def load_premises(split: str) -> List[Dict[str, Any]]:
    """Load deduplicated FOLIO premises, excluding few-shot examples."""
    ds = load_dataset("tasksource/folio", split=split)
    exclusions = _load_fewshot_exclusions()
    seen: set = set()
    pairs: List[Dict[str, Any]] = []

    for row in ds:
        nl_parts = [p.strip() for p in row["premises"].split("\n") if p.strip()]
        fol_parts = [p.strip() for p in row["premises-FOL"].split("\n") if p.strip()]
        if len(nl_parts) != len(fol_parts):
            continue
        for n, f in zip(nl_parts, fol_parts):
            if n in seen or n in exclusions:
                continue
            seen.add(n)
            pairs.append({
                "story_id": row.get("story_id"),
                "nl": n,
                "gold_fol": f,
            })

    return pairs


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", type=str, default="train",
                    help="FOLIO split to process (default: train).")
    ap.add_argument("--limit", type=int, default=None,
                    help="Process only the first N premises.")
    ap.add_argument("--timeout-s", type=int, default=10,
                    help="Vampire timeout per check.")
    ap.add_argument("--output", type=str,
                    default=str(_REPO_ROOT / "reports" / "human_study" / "test_suites.jsonl"),
                    help="Output JSONL path.")
    args = ap.parse_args()

    # ── Split check ──
    sys.stderr.write(f"[test-suites] Loading tasksource/folio split={args.split}\n")
    pairs = load_premises(args.split)
    stories = {p["story_id"] for p in pairs}
    sys.stderr.write(
        f"[test-suites] Split={args.split}  Stories={len(stories)}  "
        f"Premises={len(pairs)}\n"
    )

    if args.limit:
        pairs = pairs[:args.limit]
        sys.stderr.write(f"[test-suites] --limit active: {len(pairs)} premises\n")

    # ── Generate ──
    client = FrozenClient(OpenAI())
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    successes = 0
    failures = []
    t0 = time.time()

    with out_path.open("w") as f:
        for i, pair in enumerate(pairs):
            premise_id = f"P{i:04d}"
            nl = pair["nl"]
            story_id = pair["story_id"]

            try:
                suite = generate_test_suite(nl, client, timeout_s=args.timeout_s)
                suite["premise_id"] = premise_id
                suite["story_id"] = story_id
                suite["gold_fol"] = pair["gold_fol"]
                f.write(serialize_test_suite(suite) + "\n")
                successes += 1

            except SchemaViolation as e:
                failures.append({
                    "premise_id": premise_id, "story_id": story_id,
                    "nl": nl, "error_kind": "schema_violation", "error": str(e),
                })
            except Exception as e:
                failures.append({
                    "premise_id": premise_id, "story_id": story_id,
                    "nl": nl, "error_kind": "exception",
                    "error": f"{type(e).__name__}: {e}",
                    "trace": traceback.format_exc(limit=3),
                })

            if (i + 1) % 25 == 0 or (i + 1) == len(pairs):
                dt = time.time() - t0
                sys.stderr.write(
                    f"[test-suites] {i+1}/{len(pairs)} processed  "
                    f"ok={successes} fail={len(failures)} "
                    f"elapsed={dt:.0f}s\n"
                )

    sys.stderr.write(f"[test-suites] Wrote {out_path} ({successes} test suites)\n")

    # Write failures log
    if failures:
        fail_path = out_path.with_suffix(".failures.json")
        fail_path.write_text(json.dumps(failures, indent=2, default=str))
        sys.stderr.write(f"[test-suites] Wrote {fail_path} ({len(failures)} failures)\n")

    sys.stderr.write(
        f"[test-suites] Done: {successes} succeeded, {len(failures)} failed "
        f"({100*successes/(successes+len(failures)):.1f}% success rate)\n"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
