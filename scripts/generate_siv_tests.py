"""Generate a SIV test suite for a single natural language sentence.

Prints the test suite as JSON to stdout.  This is the atomic unit of the
SIV pipeline: NL → extraction → compilation → test probes.

Usage:
    python scripts/generate_siv_tests.py "All dogs are mammals."
    python scripts/generate_siv_tests.py --sentence "Some student read a book."
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

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

from openai import OpenAI
from siv.frozen_client import FrozenClient
from siv.test_suite_generator import generate_test_suite, serialize_test_suite


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("sentence", nargs="?", default=None,
                    help="Natural language sentence to generate tests for.")
    ap.add_argument("--sentence", dest="sentence_flag", default=None,
                    help="Alternative: pass sentence as --sentence flag.")
    ap.add_argument("--timeout-s", type=int, default=10,
                    help="Vampire timeout per check (default 10).")
    ap.add_argument("--pretty", action="store_true",
                    help="Pretty-print JSON output.")
    args = ap.parse_args()

    sentence = args.sentence or args.sentence_flag
    if not sentence:
        ap.print_help()
        return 1

    client = FrozenClient(OpenAI())

    sys.stderr.write(f"[siv-tests] Generating test suite for: {sentence[:80]}\n")
    suite = generate_test_suite(sentence, client, timeout_s=args.timeout_s)

    if args.pretty:
        print(json.dumps(suite, indent=2, default=str))
    else:
        print(serialize_test_suite(suite))

    sys.stderr.write(
        f"[siv-tests] Done: {len(suite['positives'])} positives, "
        f"{len(suite['contrastives'])} contrastives, "
        f"class={suite['structural_class']}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
