"""
SIV CLI Generator

Generates Neo-Davidsonian-compliant FOL translations from NL premises using
the SIV Generator pipeline (frozen extraction → JSON-only generation →
invariant validation). Output is the Clean-FOLIO dataset format.

Usage:
    python -m scripts.siv_generate INPUT_FILE [options]

See --help for the full option list.

Entry point: main()
"""
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

from siv.compiler import compile_sentence_test_suite
from siv.extractor import extract_problem
from siv.frozen_client import FrozenClient
from siv.generator import generate_problem, GenerationResult, BatchGenerationReport
from siv.schema import VerificationResult
from siv.verifier import verify

# ── Constants ─────────────────────────────────────────────────────────────────

_SCHEMA_VERSION = "siv_generate_report_v1"
_SEP_HEAVY = "═" * 67
_SEP_LIGHT = "─" * 67


# ── Argument parsing ──────────────────────────────────────────────────────────

def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.siv_generate",
        description=(
            "SIV CLI Generator: generate Neo-Davidsonian-compliant FOL "
            "translations from NL premises using the frozen SIV pipeline."
        ),
    )
    parser.add_argument(
        "input_file",
        metavar="INPUT_FILE",
        help="Path to the input JSON file (same shape as siv_score).",
    )
    parser.add_argument(
        "--format",
        choices=["human", "json"],
        default="json",
        dest="output_format",
        help="Output format (default: json — the primary artifact is the generated data).",
    )
    parser.add_argument(
        "--output",
        metavar="OUTPUT_FILE",
        default=None,
        dest="output_file",
        help="Write output to this file instead of stdout.",
    )
    parser.add_argument(
        "--problem-id",
        metavar="PROBLEM_ID",
        default=None,
        dest="problem_id",
        help="Process only the problem with this ID. Default: all.",
    )
    parser.add_argument(
        "--compare-to-gold",
        metavar="NAME",
        default=None,
        dest="compare_to_gold",
        help=(
            "Also score the generated FOL and the named gold candidate from the "
            "input file's candidates dict against the same test suite, reporting "
            "the head-to-head SIV scores. NAME must be a key in each problem's "
            "candidates dict."
        ),
    )
    return parser.parse_args(argv)


# ── Input loading and validation ──────────────────────────────────────────────

def _load_input(path: str) -> list:
    """Load and structurally validate the input JSON file. Exits 2 on error."""
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, IOError) as e:
        print(f"ERROR: Cannot read input file '{path}': {e}", file=sys.stderr)
        raise SystemExit(2)
    except json.JSONDecodeError as e:
        print(f"ERROR: Input file '{path}' is not valid JSON: {e}", file=sys.stderr)
        raise SystemExit(2)

    if not isinstance(data, list):
        print(
            "ERROR: Input file must be a JSON array of problem objects.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    for i, problem in enumerate(data):
        if not isinstance(problem, dict):
            print(
                f"ERROR: Problem at index {i} must be a JSON object.",
                file=sys.stderr,
            )
            raise SystemExit(2)
        for key in ("problem_id", "premises"):
            if key not in problem:
                print(
                    f"ERROR: Problem at index {i} missing required key '{key}'.",
                    file=sys.stderr,
                )
                raise SystemExit(2)
        if not isinstance(problem["premises"], list):
            pid = problem.get("problem_id", str(i))
            print(
                f"ERROR: Problem '{pid}': 'premises' must be a list.",
                file=sys.stderr,
            )
            raise SystemExit(2)

    return data


# ── FrozenClient construction ─────────────────────────────────────────────────

def _make_frozen_client() -> FrozenClient:
    """
    Construct a FrozenClient from the environment's OPENAI_API_KEY.
    Exits 2 with a clear message if the key is unset.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print(
            "ERROR: OPENAI_API_KEY is not set.\n"
            "Export your OpenAI API key before running the generator:\n"
            "  export OPENAI_API_KEY=sk-...",
            file=sys.stderr,
        )
        raise SystemExit(2)
    try:
        from openai import OpenAI
        return FrozenClient(OpenAI(api_key=api_key))
    except ImportError as e:
        print(f"ERROR: Failed to import openai: {e}", file=sys.stderr)
        raise SystemExit(1)


# ── Serialisation helpers ─────────────────────────────────────────────────────

def _score_to_dict(result: VerificationResult) -> dict:
    return {
        "siv_score": result.siv_score,
        "recall_rate": result.recall_rate,
        "precision_rate": result.precision_rate,
    }


def _premise_to_dict(
    gen_result: GenerationResult,
    premise_idx: int,
    nl: str,
    compare_score: Optional[VerificationResult] = None,
    gold_score: Optional[VerificationResult] = None,
    gold_name: Optional[str] = None,
) -> dict:
    d: dict = {
        "premise_index": premise_idx,
        "nl": nl,
        "fol": gen_result.fol,
        "refused": gen_result.refused,
        "refusal_reason": gen_result.refusal_reason,
        "refusal_stage": gen_result.refusal_stage,
        "invariant_failures": gen_result.invariant_failures,
    }
    if compare_score is not None:
        d["generated_siv"] = _score_to_dict(compare_score)
    if gold_score is not None and gold_name is not None:
        d[f"{gold_name}_siv"] = _score_to_dict(gold_score)
    return d


# ── Human format helpers ──────────────────────────────────────────────────────

def _format_human_premise(
    problem_id: str,
    premise_idx: int,
    nl: str,
    gen_result: GenerationResult,
    compare_score: Optional[VerificationResult] = None,
    gold_score: Optional[VerificationResult] = None,
    gold_name: Optional[str] = None,
) -> str:
    lines: List[str] = []
    lines.append(_SEP_HEAVY)
    lines.append(f"Problem: {problem_id}")
    lines.append(f"Premise {premise_idx}: {nl}")
    lines.append(_SEP_HEAVY)
    lines.append("")

    if gen_result.refused:
        lines.append(f"  STATUS: REFUSED ({gen_result.refusal_stage})")
        lines.append(f"  Reason: {gen_result.refusal_reason}")
        if gen_result.invariant_failures:
            lines.append("  Invariant failures:")
            for fail in gen_result.invariant_failures:
                lines.append(f"    - {fail}")
    else:
        lines.append(f"  Generated FOL: {gen_result.fol}")
        if compare_score is not None:
            lines.append(
                f"    SIV (generated) = {compare_score.siv_score:.3f}   "
                f"recall = {compare_score.recall_rate:.3f}   "
                f"precision = {compare_score.precision_rate:.3f}"
            )
        if gold_score is not None and gold_name is not None:
            lines.append(
                f"    SIV ({gold_name}) = {gold_score.siv_score:.3f}   "
                f"recall = {gold_score.recall_rate:.3f}   "
                f"precision = {gold_score.precision_rate:.3f}"
            )

    lines.append("")
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv=None) -> None:
    args = _parse_args(argv)

    # Load and validate input
    problems = _load_input(args.input_file)

    # Filter by problem ID if requested
    if args.problem_id is not None:
        problems = [p for p in problems if p["problem_id"] == args.problem_id]
        if not problems:
            print(
                f"ERROR: No problem with id '{args.problem_id}' found in "
                f"'{args.input_file}'.",
                file=sys.stderr,
            )
            raise SystemExit(2)

    # Check API key and build FrozenClient (exits 2 if OPENAI_API_KEY is unset)
    frozen_client = _make_frozen_client()

    human_lines: List[str] = []
    json_problems: List[dict] = []

    for prob in problems:
        problem_id: str = prob["problem_id"]
        premises: List[str] = prob["premises"]
        candidates: Dict[str, str] = prob.get("candidates", {})

        if not premises:
            print(
                f"WARNING: Problem '{problem_id}' has zero premises — skipping.",
                file=sys.stderr,
            )
            continue

        # Stage 2: extract all sentences for the problem
        try:
            problem_extraction = extract_problem(
                premises,
                client=frozen_client,
                problem_id=problem_id,
            )
        except Exception as e:
            print(
                f"ERROR: Extraction failed for problem '{problem_id}': {e}",
                file=sys.stderr,
            )
            raise SystemExit(1)

        # Generator: produce FOL for each sentence in the problem
        try:
            batch_report = generate_problem(problem_extraction, frozen_client)
        except Exception as e:
            print(
                f"ERROR: Generation failed for problem '{problem_id}': {e}",
                file=sys.stderr,
            )
            raise SystemExit(1)

        json_premises_list: List[dict] = []

        for i, (sentence_ext, gen_result) in enumerate(
            zip(problem_extraction.sentences, batch_report.results)
        ):
            premise_idx = i + 1
            nl = sentence_ext.nl

            compare_score: Optional[VerificationResult] = None
            gold_score: Optional[VerificationResult] = None

            if args.compare_to_gold:
                # Compile the test suite once; score both generated and gold FOL against it.
                suite = compile_sentence_test_suite(
                    sentence_ext,
                    problem_id=f"{problem_id}_p{premise_idx}",
                )
                gold_fol = candidates.get(args.compare_to_gold, "")

                # Score generated FOL (only if generation succeeded)
                if not gen_result.refused and gen_result.fol:
                    try:
                        compare_score = verify(
                            gen_result.fol, suite, unresolved_policy="exclude"
                        )
                    except Exception as e:
                        print(
                            f"WARNING: Could not score generated FOL for "
                            f"'{problem_id}' premise {premise_idx}: {e}",
                            file=sys.stderr,
                        )

                # Score gold FOL
                if gold_fol:
                    try:
                        gold_score = verify(
                            gold_fol, suite, unresolved_policy="exclude"
                        )
                    except Exception as e:
                        print(
                            f"WARNING: Could not score gold FOL for "
                            f"'{problem_id}' premise {premise_idx}: {e}",
                            file=sys.stderr,
                        )

            if args.output_format == "human":
                human_lines.append(
                    _format_human_premise(
                        problem_id, premise_idx, nl, gen_result,
                        compare_score=compare_score,
                        gold_score=gold_score,
                        gold_name=args.compare_to_gold,
                    )
                )

            json_premises_list.append(
                _premise_to_dict(
                    gen_result, premise_idx, nl,
                    compare_score=compare_score,
                    gold_score=gold_score,
                    gold_name=args.compare_to_gold,
                )
            )

        json_problems.append({
            "problem_id": problem_id,
            "num_premises": len(premises),
            "num_generated": batch_report.num_generated,
            "num_refused_pre_call": batch_report.num_refused_pre_call,
            "num_refused_post_call": batch_report.num_refused_post_call,
            "premises": json_premises_list,
        })

    if args.output_format == "human":
        output_text = "\n".join(human_lines)
    else:
        report = {
            "schema_version": _SCHEMA_VERSION,
            "input_file": args.input_file,
            "problems": json_problems,
        }
        output_text = json.dumps(report, indent=2)

    # Write output
    if args.output_file:
        try:
            Path(args.output_file).write_text(output_text)
        except OSError as e:
            print(
                f"ERROR: Cannot write to output file '{args.output_file}': {e}",
                file=sys.stderr,
            )
            raise SystemExit(1)
    else:
        print(output_text)


if __name__ == "__main__":
    main()
