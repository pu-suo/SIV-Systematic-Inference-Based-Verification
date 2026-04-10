"""
SIV CLI Evaluator

Scores FOL candidate translations against NL premises using the full SIV
pipeline (Stage 1 pre-analysis → frozen LLM extraction → compilation →
tiered verification).

Usage:
    python -m scripts.siv_score INPUT_FILE [options]

See --help for the full option list.

Entry point: main()
"""
import siv._bootstrap  # noqa: F401 — loads .env, ensures NLTK data
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

from siv.compiler import compile_sentence_test_suite
from siv.extractor import extract_problem
from siv.frozen_client import FrozenClient
from siv.schema import SchemaViolation, VerificationResult
from siv.scorer import aggregate_per_candidate
from siv.verifier import verify

# ── Constants ─────────────────────────────────────────────────────────────────

_SCHEMA_VERSION = "siv_score_report_v1"
_SEP_HEAVY = "═" * 67
_SEP_LIGHT = "─" * 67


# ── Argument parsing ──────────────────────────────────────────────────────────

def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.siv_score",
        description=(
            "SIV CLI Evaluator: score FOL candidate translations against "
            "NL premises using the frozen SIV pipeline."
        ),
    )
    parser.add_argument(
        "input_file",
        metavar="INPUT_FILE",
        help="Path to the input JSON file.",
    )
    parser.add_argument(
        "--format",
        choices=["human", "json"],
        default="human",
        dest="output_format",
        help="Output format (default: human).",
    )
    parser.add_argument(
        "--unresolved-policy",
        choices=["raise", "exclude"],
        default="raise",
        dest="unresolved_policy",
        help=(
            "Policy for prover-unresolved tests. "
            "'raise' (default) aborts if any test cannot be resolved — "
            "required for published SIV scores. "
            "'exclude' omits unresolved tests from the denominator."
        ),
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
        help="Score only the problem with this ID. Default: score all problems.",
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
        for key in ("problem_id", "premises", "candidates"):
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
        if not isinstance(problem["candidates"], dict):
            pid = problem.get("problem_id", str(i))
            print(
                f"ERROR: Problem '{pid}': 'candidates' must be a JSON object.",
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
            "Export your OpenAI API key before running the evaluator:\n"
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

def _violation_to_dict(v: SchemaViolation) -> dict:
    return {
        "violation_type": v.violation_type,
        "fact_pred": v.fact_pred,
        "fact_args": list(v.fact_args),
        "message": v.message,
    }


def _result_to_dict(result: VerificationResult) -> dict:
    return {
        "siv_score": result.siv_score,
        "recall_rate": result.recall_rate,
        "precision_rate": result.precision_rate,
        "recall_total": result.recall_total,
        "precision_total": result.precision_total,
        "unresolved_recall": result.unresolved_recall,
        "unresolved_precision": result.unresolved_precision,
        "extraction_invalid": result.extraction_invalid,
        "candidate_inconsistent": result.candidate_inconsistent,
        "schema_violations": [_violation_to_dict(v) for v in result.schema_violations],
    }


# ── Status label ──────────────────────────────────────────────────────────────

def _result_status(result: VerificationResult) -> str:
    if result.extraction_invalid:
        return "EXTRACTION_INVALID"
    if result.candidate_inconsistent:
        return "CANDIDATE_INCONSISTENT"
    if not result.syntax_valid:
        return "SYNTAX_ERROR"
    return "OK"


# ── Human format helpers ──────────────────────────────────────────────────────

def _wrap_nl(nl: str, prefix: str, width: int = 67) -> str:
    """Word-wrap NL text; continuation lines are indented to align with prefix."""
    indent = " " * len(prefix)
    words = nl.split()
    lines: List[str] = []
    current = prefix
    for word in words:
        candidate_line = current + (" " if current != prefix else "") + word
        if len(candidate_line) > width and current != prefix:
            lines.append(current)
            current = indent + word
        else:
            current = candidate_line
    lines.append(current)
    return "\n".join(lines)


def _format_human_premise(
    problem_id: str,
    premise_idx: int,
    nl: str,
    candidate_results: Dict[str, VerificationResult],
    candidate_names: List[str],
) -> str:
    lines: List[str] = []
    lines.append(_SEP_HEAVY)
    lines.append(f"Problem: {problem_id}")
    prefix = f"Premise {premise_idx}: "
    lines.append(_wrap_nl(nl, prefix))
    lines.append(_SEP_HEAVY)
    lines.append("")

    for name in candidate_names:
        result = candidate_results[name]
        lines.append(f"  Candidate: {name}")
        lines.append(
            f"    SIV = {result.siv_score:.3f}   "
            f"recall = {result.recall_rate:.3f}   "
            f"precision = {result.precision_rate:.3f}"
        )
        lines.append(
            f"    tests: {result.recall_total} pos / {result.precision_total} neg   "
            f"unresolved: {result.unresolved_recall} / {result.unresolved_precision}"
        )
        lines.append(f"    status: {_result_status(result)}")
        if result.schema_violations:
            lines.append("    violations:")
            for v in result.schema_violations:
                args_str = ", ".join(v.fact_args)
                lines.append(
                    f"      - {v.violation_type}: pred='{v.fact_pred}' ({args_str})"
                )
        lines.append("")

    return "\n".join(lines)


def _format_human_problem_summary(
    problem_id: str,
    num_premises: int,
    per_candidate_agg: Dict[str, Dict],
    candidate_names: List[str],
) -> str:
    name_width = max((len(n) for n in candidate_names), default=0) + 2
    lines: List[str] = []
    lines.append(_SEP_HEAVY)
    lines.append(
        f"Problem {problem_id} — candidate summary "
        f"(macro-averaged over {num_premises} premise{'s' if num_premises != 1 else ''})"
    )
    lines.append(_SEP_LIGHT)
    for name in candidate_names:
        agg = per_candidate_agg[name]
        num_invalid = agg.get("num_invalid", 0)
        lines.append(
            f"  {name:<{name_width}} "
            f"SIV={agg['siv']:.3f}  "
            f"recall={agg['recall']:.3f}  "
            f"precision={agg['precision']:.3f}  "
            f"invalid={num_invalid}/{num_premises}"
        )
    lines.append(_SEP_HEAVY)
    return "\n".join(lines)


def _format_human_grand_total(
    num_problems: int,
    grand_total: Dict[str, Dict],
    candidate_names: List[str],
    total_premises: int,
    total_invalid: Dict[str, int],
) -> str:
    name_width = max((len(n) for n in candidate_names), default=0) + 2
    lines: List[str] = []
    lines.append(_SEP_HEAVY)
    lines.append(
        f"GRAND TOTAL — candidate summary "
        f"({num_problems} problem{'s' if num_problems != 1 else ''})"
    )
    lines.append(_SEP_LIGHT)
    for name in candidate_names:
        agg = grand_total[name]
        inv = total_invalid.get(name, 0)
        lines.append(
            f"  {name:<{name_width}} "
            f"SIV={agg['siv']:.3f}  "
            f"recall={agg['recall']:.3f}  "
            f"precision={agg['precision']:.3f}  "
            f"invalid={inv}/{total_premises}"
        )
    lines.append(_SEP_HEAVY)
    return "\n".join(lines)


# ── Grand-total macro-average ─────────────────────────────────────────────────

def _macro_average_per_candidate(
    per_problem: List[Dict[str, Dict]],
    candidate_names: List[str],
) -> Dict[str, Dict]:
    """Macro-average siv/recall/precision per candidate across problems."""
    result: Dict[str, Dict] = {}
    for name in candidate_names:
        entries = [p[name] for p in per_problem if name in p]
        if not entries:
            result[name] = {"siv": 0.0, "recall": 0.0, "precision": 0.0}
        else:
            n = len(entries)
            result[name] = {
                "siv": sum(e["siv"] for e in entries) / n,
                "recall": sum(e["recall"] for e in entries) / n,
                "precision": sum(e["precision"] for e in entries) / n,
            }
    return result


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

    # Collect all candidate names in input-file order (deduplication preserves first-seen)
    all_candidate_names: List[str] = []
    seen_names: set = set()
    for prob in problems:
        for name in prob["candidates"]:
            if name not in seen_names:
                all_candidate_names.append(name)
                seen_names.add(name)

    # Output accumulators
    human_lines: List[str] = []
    json_problems: List[dict] = []
    per_problem_agg: List[Dict[str, Dict]] = []
    total_invalid_per_candidate: Dict[str, int] = {n: 0 for n in all_candidate_names}
    total_premises = 0

    for prob in problems:
        problem_id: str = prob["problem_id"]
        premises: List[str] = prob["premises"]
        candidates: Dict[str, str] = prob["candidates"]
        candidate_names: List[str] = list(candidates.keys())

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

        total_premises += len(premises)

        # Per-candidate accumulator: {candidate_name: [VerificationResult, ...]}
        per_candidate_results: Dict[str, List[VerificationResult]] = {
            name: [] for name in candidate_names
        }

        json_premises_list: List[dict] = []

        for i, sentence_ext in enumerate(problem_extraction.sentences):
            premise_idx = i + 1
            nl = sentence_ext.nl

            # Stage 3: compile test suite for this single sentence
            suite = compile_sentence_test_suite(
                sentence_ext,
                problem_id=f"{problem_id}_p{premise_idx}",
            )

            premise_candidate_results: Dict[str, VerificationResult] = {}

            for cand_name in candidate_names:
                cand_fol = candidates[cand_name]
                try:
                    result = verify(
                        cand_fol,
                        suite,
                        unresolved_policy=args.unresolved_policy,
                    )
                except Exception as e:
                    print(
                        f"ERROR: Verification failed for problem '{problem_id}', "
                        f"premise {premise_idx}, candidate '{cand_name}': {e}",
                        file=sys.stderr,
                    )
                    raise SystemExit(1)

                premise_candidate_results[cand_name] = result
                per_candidate_results[cand_name].append(result)

            # Human output for this premise
            if args.output_format == "human":
                human_lines.append(
                    _format_human_premise(
                        problem_id, premise_idx, nl,
                        premise_candidate_results, candidate_names,
                    )
                )

            # JSON entry for this premise
            json_premises_list.append({
                "premise_index": premise_idx,
                "nl": nl,
                "candidates": {
                    cand_name: _result_to_dict(premise_candidate_results[cand_name])
                    for cand_name in candidate_names
                },
            })

        # Aggregate per-candidate across all premises in this problem
        problem_per_candidate_agg = aggregate_per_candidate(per_candidate_results)

        # Accumulate invalid counts for grand total
        for name in candidate_names:
            total_invalid_per_candidate[name] = (
                total_invalid_per_candidate.get(name, 0)
                + problem_per_candidate_agg[name].get("num_invalid", 0)
            )

        # Human: problem summary block
        if args.output_format == "human":
            human_lines.append("")
            human_lines.append(
                _format_human_problem_summary(
                    problem_id, len(premises),
                    problem_per_candidate_agg, candidate_names,
                )
            )
            human_lines.append("")

        # JSON: problem entry
        json_problems.append({
            "problem_id": problem_id,
            "premises": json_premises_list,
            "summary": {
                name: {
                    "siv_score": problem_per_candidate_agg[name]["siv"],
                    "recall_rate": problem_per_candidate_agg[name]["recall"],
                    "precision_rate": problem_per_candidate_agg[name]["precision"],
                    "num_invalid": problem_per_candidate_agg[name].get("num_invalid", 0),
                    "num_premises": len(premises),
                }
                for name in candidate_names
            },
        })

        per_problem_agg.append(problem_per_candidate_agg)

    # Grand total: macro-average per candidate across all problems
    grand_total = _macro_average_per_candidate(per_problem_agg, all_candidate_names)

    if args.output_format == "human":
        human_lines.append(
            _format_human_grand_total(
                len(json_problems),
                grand_total,
                all_candidate_names,
                total_premises,
                total_invalid_per_candidate,
            )
        )
        output_text = "\n".join(human_lines)
    else:
        report = {
            "schema_version": _SCHEMA_VERSION,
            "input_file": args.input_file,
            "unresolved_policy": args.unresolved_policy,
            "problems": json_problems,
            "grand_total": {
                name: {
                    "siv_score": grand_total[name]["siv"],
                    "recall_rate": grand_total[name]["recall"],
                    "precision_rate": grand_total[name]["precision"],
                }
                for name in all_candidate_names
            },
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
