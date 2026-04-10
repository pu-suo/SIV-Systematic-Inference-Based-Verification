"""
SIV Inspector CLI

Shows what SIV sees: the extraction, compiled test suite, and optionally
scores a candidate FOL against the compiled tests.

Usage:
    python -m siv inspect "All dogs are mammals."
    python -m siv inspect --extraction-json '{"constants":[],...}' [--candidate FOL]
    python scripts/siv_inspect.py --help

Entry point: main()
"""
import siv._bootstrap  # noqa: F401 — loads .env, ensures NLTK data
import argparse
import json
import os
import sys
from typing import List, Optional, Tuple

from siv.compiler import compile_test_suite
from siv.extractor import _dict_to_extraction
from siv.frozen_client import FrozenClient
from siv.schema import (
    ProblemExtraction, SentenceExtraction, TestSuite, UnitTest,
)
from siv.verifier import (
    _tier0_consistency, _tier0_syntax, _tier1_vocabulary, _tier2_ast,
    _tier3_prover, verify,
)
from siv.fol_utils import NLTK_AVAILABLE, parse_fol


# ── Argument parsing ──────────────────────────────────────────────────────────

def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m siv inspect",
        description=(
            "SIV Inspector: show extraction, test suite, and optionally "
            "score a candidate."
        ),
    )
    parser.add_argument(
        "sentences",
        nargs="*",
        metavar="sentences",
        help="One or more NL sentences to inspect.",
    )
    parser.add_argument(
        "--candidate",
        metavar="FOL",
        default=None,
        dest="candidate",
        help="Score this FOL candidate against the compiled test suite.",
    )
    parser.add_argument(
        "--extraction-json",
        metavar="JSON",
        action="append",
        dest="extraction_jsons",
        default=None,
        help=(
            "Use this raw SIV JSON extraction instead of calling the extractor. "
            "Can be specified multiple times for multiple premises. "
            "Useful for offline demos and testing."
        ),
    )
    parser.add_argument(
        "--unresolved-policy",
        choices=["raise", "exclude"],
        default="exclude",
        dest="unresolved_policy",
        help="How to handle prover-unresolvable tests (default: exclude).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        dest="output_json",
        help="Output structured JSON instead of human-readable text.",
    )
    return parser.parse_args(argv)


# ── FrozenClient construction ─────────────────────────────────────────────────

def _make_frozen_client() -> FrozenClient:
    """Construct a FrozenClient from OPENAI_API_KEY. Exits 2 if unset."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print(
            "ERROR: OPENAI_API_KEY is not set.\n"
            "Export your OpenAI API key or use --extraction-json for offline mode:\n"
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


# ── Parsing JSON extractions ──────────────────────────────────────────────────

def _parse_extraction_json(raw: str) -> SentenceExtraction:
    """Parse a raw JSON string into a SentenceExtraction. Exits 2 on error."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid --extraction-json: {e}", file=sys.stderr)
        raise SystemExit(2)
    if not isinstance(data, dict):
        print("ERROR: --extraction-json must be a JSON object.", file=sys.stderr)
        raise SystemExit(2)
    try:
        return _dict_to_extraction("", data, [])
    except Exception as e:
        print(f"ERROR: Could not parse extraction JSON: {e}", file=sys.stderr)
        raise SystemExit(2)


# ── Per-test tier resolution ──────────────────────────────────────────────────

def _resolve_test_with_tier(
    candidate: str,
    test: UnitTest,
    candidate_expr,
) -> Tuple[bool, str, Optional[str]]:
    """
    Determine pass/fail and which tier resolved a test.

    Returns (passed, tier_label, reason_if_failed).
    tier_label: "T0", "T1", "T2", "T3", "T3(unresolved)"
    """
    if test.is_positive:
        definitive, credit = _tier1_vocabulary(candidate, test)
        if credit == 0.0:
            return False, "T1", "predicate absent"

        test_expr = parse_fol(test.fol_string) if NLTK_AVAILABLE else None
        if candidate_expr is not None and test_expr is not None:
            t2 = _tier2_ast(candidate_expr, test_expr)
            if t2 is True:
                return True, "T2", None
            elif t2 is False:
                return False, "T2", "AST mismatch"

        result = _tier3_prover(candidate, test.fol_string)
        if result is True:
            return True, "T3", None
        elif result is False:
            return False, "T3", "prover: not entailed"
        else:
            return False, "T3(unresolved)", "prover: timeout/unavailable"

    else:  # negative test
        _, credit = _tier1_vocabulary(candidate, test)
        if credit == 0.0:
            return True, "T1", None  # predicate absent → trivially safe

        test_expr = parse_fol(test.fol_string) if NLTK_AVAILABLE else None
        if candidate_expr is not None and test_expr is not None:
            t2 = _tier2_ast(candidate_expr, test_expr)
            if t2 is not None:
                passed = not t2
                return passed, "T2", None if passed else "AST: entailed (precision fail)"

        result = _tier3_prover(candidate, test.fol_string)
        if result is True:
            return False, "T3", "prover: entailed (precision fail)"
        elif result is False:
            return True, "T3", None
        else:
            return False, "T3(unresolved)", "prover: timeout/unavailable"


# ── Human output helpers ──────────────────────────────────────────────────────

def _format_extraction(idx: int, sent_ext: SentenceExtraction) -> List[str]:
    lines = []
    nl_display = sent_ext.nl if sent_ext.nl else "(offline extraction)"
    lines.append(f"Premise {idx}: {nl_display}")
    lines.append("")
    lines.append("  Extraction:")

    # Constants
    if sent_ext.constants:
        const_strs = [f"{c.id}={c.surface}" for c in sent_ext.constants]
        lines.append(f"    constants: {', '.join(const_strs)}")
    else:
        lines.append("    constants: (none)")

    # Entities
    if sent_ext.entities:
        lines.append("    entities:")
        for e in sent_ext.entities:
            lines.append(f"      {e.id}  {e.surface}  ({e.entity_type.value})")
    else:
        lines.append("    entities: (none)")

    # Facts
    if sent_ext.facts:
        lines.append("    facts:")
        for f in sent_ext.facts:
            args_str = ", ".join(f.args)
            neg_tag = "  [negated: true]" if f.negated else ""
            lines.append(f"      {f.pred}({args_str}){neg_tag}")
    else:
        lines.append("    facts: (none)")

    lines.append(f"    macro_template: {sent_ext.macro_template.value}")

    return lines


def _format_test_suite(suite: TestSuite) -> List[str]:
    lines = []
    n_pos = len(suite.positive_tests)
    n_neg = len(suite.negative_tests)
    lines.append(f"  Compiled Test Suite: {n_pos} positive / {n_neg} negative")

    if suite.positive_tests:
        lines.append("    Positive (recall):")
        for t in suite.positive_tests:
            lines.append(f"      [{t.test_type}]  {t.fol_string}")

    if suite.negative_tests:
        lines.append("    Negative (precision):")
        for t in suite.negative_tests:
            lines.append(f"      [{t.test_type}]  {t.fol_string}")

    if suite.violations:
        lines.append("    Violations:")
        for v in suite.violations:
            lines.append(f"      - {v.violation_type}: {v.message}")

    return lines


def _format_candidate_result(
    candidate: str,
    suite: TestSuite,
    result,
    unresolved_policy: str,
) -> List[str]:
    lines = []
    lines.append(f"  Candidate: {candidate}")

    syntax_ok = "OK" if result.syntax_valid else "FAIL"
    if result.candidate_inconsistent:
        consist_str = "FAIL"
    elif result.syntax_valid:
        consist_str = "OK"
    else:
        consist_str = "UNKNOWN"
    lines.append(f"    Tier 0: syntax={syntax_ok}  consistency={consist_str}")
    lines.append("")

    if not result.syntax_valid:
        lines.append("    Candidate has syntax errors; skipping test details.")
        lines.append(f"    SIV = {result.siv_score:.3f}   "
                     f"recall = {result.recall_rate:.3f}   "
                     f"precision = {result.precision_rate:.3f}")
        return lines

    candidate_expr = parse_fol(candidate) if NLTK_AVAILABLE else None

    # Recall
    recall_passed_display = 0
    recall_total_display = len(suite.positive_tests)
    lines.append(f"    Recall ({result.recall_passed}/{result.recall_total - result.unresolved_recall} effective):")
    for test in suite.positive_tests:
        passed, tier, reason = _resolve_test_with_tier(candidate, test, candidate_expr)
        if passed:
            recall_passed_display += 1
        status = "PASS" if passed else "FAIL"
        reason_str = f"  — {reason}" if reason else ""
        lines.append(f"      [{status} {tier}]  {test.fol_string}{reason_str}")

    lines.append("")

    # Precision
    precision_passed_display = 0
    lines.append(f"    Precision ({result.precision_passed}/{result.precision_total - result.unresolved_precision} effective):")
    for test in suite.negative_tests:
        passed, tier, reason = _resolve_test_with_tier(candidate, test, candidate_expr)
        if passed:
            precision_passed_display += 1
        status = "PASS" if passed else "FAIL"
        reason_str = f"  — {reason}" if reason else ""
        lines.append(f"      [{status} {tier}]  {test.fol_string}{reason_str}")

    lines.append("")
    lines.append(f"    SIV = {result.siv_score:.3f}   "
                 f"recall = {result.recall_rate:.3f}   "
                 f"precision = {result.precision_rate:.3f}")

    return lines


# ── JSON output helpers ───────────────────────────────────────────────────────

def _extraction_to_dict(sent_ext: SentenceExtraction) -> dict:
    return {
        "constants": [{"id": c.id, "surface": c.surface} for c in sent_ext.constants],
        "entities": [
            {"id": e.id, "surface": e.surface, "entity_type": e.entity_type.value}
            for e in sent_ext.entities
        ],
        "facts": [
            {"pred": f.pred, "args": f.args, "negated": f.negated}
            for f in sent_ext.facts
        ],
        "macro_template": sent_ext.macro_template.value,
        "violations": [],
    }


def _test_suite_to_dict(suite: TestSuite) -> dict:
    return {
        "positive_tests": [
            {"fol_string": t.fol_string, "test_type": t.test_type}
            for t in suite.positive_tests
        ],
        "negative_tests": [
            {"fol_string": t.fol_string, "test_type": t.test_type}
            for t in suite.negative_tests
        ],
    }


def _candidate_result_to_dict(candidate: str, result) -> dict:
    return {
        "candidate_fol": candidate,
        "syntax_valid": result.syntax_valid,
        "candidate_inconsistent": result.candidate_inconsistent,
        "recall_passed": result.recall_passed,
        "recall_total": result.recall_total - result.unresolved_recall,
        "precision_passed": result.precision_passed,
        "precision_total": result.precision_total - result.unresolved_precision,
        "siv_score": round(result.siv_score, 3),
        "recall_rate": round(result.recall_rate, 3),
        "precision_rate": round(result.precision_rate, 3),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv=None) -> None:
    args = _parse_args(argv)

    offline_mode = args.extraction_jsons is not None

    if not offline_mode and not args.sentences:
        print(
            "ERROR: Provide at least one sentence, or use --extraction-json for "
            "offline mode.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    # ── Build sentence extractions ────────────────────────────────────────────

    if offline_mode:
        # Parse each --extraction-json value into a SentenceExtraction
        sentence_extractions: List[SentenceExtraction] = [
            _parse_extraction_json(raw) for raw in args.extraction_jsons
        ]
    else:
        # Online mode: need API key and extractor
        frozen_client = _make_frozen_client()
        from siv.extractor import extract_problem
        from siv.pre_analyzer import analyze_sentence

        try:
            problem_extraction = extract_problem(
                args.sentences,
                client=frozen_client,
                problem_id="inspect",
            )
            sentence_extractions = problem_extraction.sentences
        except Exception as e:
            print(f"ERROR: Extraction failed: {e}", file=sys.stderr)
            raise SystemExit(1)

    # ── Build unified ProblemExtraction and compile test suite ────────────────

    problem = ProblemExtraction(
        problem_id="inspect",
        sentences=sentence_extractions,
    )
    suite = compile_test_suite(problem)

    # ── Score candidate if provided ───────────────────────────────────────────

    candidate_result = None
    if args.candidate:
        try:
            candidate_result = verify(
                args.candidate,
                suite,
                unresolved_policy=args.unresolved_policy,
            )
        except Exception as e:
            print(f"ERROR: Verification failed: {e}", file=sys.stderr)
            raise SystemExit(1)

    # ── Output ────────────────────────────────────────────────────────────────

    if args.output_json:
        premises_out = []
        for i, sent_ext in enumerate(sentence_extractions):
            entry = {
                "nl": sent_ext.nl,
                "extraction": _extraction_to_dict(sent_ext),
                "test_suite": _test_suite_to_dict(suite),
                "candidate_result": (
                    _candidate_result_to_dict(args.candidate, candidate_result)
                    if candidate_result is not None
                    else None
                ),
            }
            premises_out.append(entry)
        print(json.dumps({"premises": premises_out}, indent=2))
    else:
        output_lines: List[str] = []

        for i, sent_ext in enumerate(sentence_extractions):
            output_lines.extend(_format_extraction(i + 1, sent_ext))
            output_lines.append("")
            output_lines.extend(_format_test_suite(suite))

        if candidate_result is not None:
            output_lines.append("")
            output_lines.extend(
                _format_candidate_result(
                    args.candidate, suite, candidate_result, args.unresolved_policy
                )
            )

        print("\n".join(output_lines))


if __name__ == "__main__":
    main()
