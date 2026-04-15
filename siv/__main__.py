"""
SIV: Soundness-Invariant Verification for NL-to-FOL Translation.

Usage:
    python -m siv extract "sentence"

Loads OPENAI_API_KEY from .env at the repo root and extracts a single
sentence into JSON per the SentenceExtraction schema (§6.2).
"""
import json
import os
import sys
from pathlib import Path


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__.strip())
        raise SystemExit(0)

    command = sys.argv[1]
    sys.argv = [f"python -m siv {command}"] + sys.argv[2:]

    if command == "extract":
        _run_extract()
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print("Available commands: extract", file=sys.stderr)
        raise SystemExit(2)


def _run_extract():
    if len(sys.argv) < 2:
        print('Usage: python -m siv extract "sentence"', file=sys.stderr)
        raise SystemExit(2)
    sentence = sys.argv[1]

    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
    except ImportError:
        pass

    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set.", file=sys.stderr)
        raise SystemExit(1)

    from openai import OpenAI
    from siv.extractor import extract_sentence
    from siv.frozen_client import FrozenClient

    client = FrozenClient(OpenAI())
    extraction = extract_sentence(sentence, client)
    print(json.dumps(extraction.model_dump(), indent=2))


if __name__ == "__main__":
    main()
