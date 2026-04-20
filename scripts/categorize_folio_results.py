"""Categorize FOLIO evaluation divergence cases for human study design.

Reads a folio_agreement.json report and classifies each scored premise into
one of several divergence categories. Produces CANDIDATE labels for manual
review — not final labels.

Categories:
  perfect_agreement      — recall = 1.0
  vocab_divergence_total — zero/near-zero predicate overlap (stemmed)
  vocab_divergence_partial — some overlap but divergent predicates cause loss
  restrictor_collapse    — predicates overlap, one side drops a restrictor
  entity_flattening      — predicates overlap, arity/decomposition differs
  quantifier_mismatch    — predicates overlap, quantifier type/scope differs
  constant_divergence    — predicates overlap fully, constants differ
  alternative_decomposition — different but arguably valid approach
  parse_error            — FOLIO gold didn't parse

Usage:
    python scripts/categorize_folio_results.py
    python scripts/categorize_folio_results.py \
        --input reports/folio_agreement_train.json \
        --output reports/folio_categorization_train.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from siv.fol_utils import normalize_fol_string, parse_fol, NLTK_AVAILABLE

if NLTK_AVAILABLE:
    from nltk.sem.logic import (
        AllExpression, ExistsExpression, AndExpression, ImpExpression,
        ApplicationExpression, NegatedExpression, BinaryExpression,
    )


# ── Predicate & constant extraction ──────────────────────────────────────────

def _extract_preds_regex(fol: str) -> Set[str]:
    """Regex-based predicate extraction for both NLTK and Unicode FOL."""
    # Normalize first to handle Unicode
    norm = normalize_fol_string(fol)
    matches = re.findall(r"([A-Z][A-Za-z0-9_]*)\s*\(", norm)
    # Also check the raw string for Unicode-only predicates
    matches += re.findall(r"([A-Z][A-Za-z0-9_]*)\s*\(", fol)
    return set(matches)


def _extract_constants_regex(fol: str) -> Set[str]:
    """Extract constant names (identifiers used as predicate arguments).

    Handles constants starting with digits (e.g., 2008SummerOlympics) and
    underscored names (e.g., family_History).
    """
    norm = normalize_fol_string(fol)
    constants = set()
    for match in re.finditer(r"[A-Z][A-Za-z0-9_]*\(([^)]*)\)", norm):
        args = match.group(1).split(",")
        for arg in args:
            arg = arg.strip()
            # Constants: lowercase or digit-starting identifiers, not variables
            if re.match(r"^[a-z0-9][a-zA-Z0-9_]*$", arg) and not re.match(r"^[uvwxyz]\d*$", arg):
                constants.add(arg)
    # Also check raw string for Unicode-context constants
    for match in re.finditer(r"[A-Z][A-Za-z0-9_]*\(([^)]*)\)", fol):
        args = match.group(1).split(",")
        for arg in args:
            arg = arg.strip()
            if re.match(r"^[a-z0-9][a-zA-Z0-9_]*$", arg) and not re.match(r"^[uvwxyz]\d*$", arg):
                constants.add(arg)
    return constants


# ── Stemming-aware predicate comparison ──────────────────────────────────────

def _camel_to_words(name: str) -> List[str]:
    """Split CamelCase into lowercase words: 'WorkRemotelyFrom' → ['work', 'remotely', 'from']."""
    words = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    words = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", words)
    return [w.lower() for w in words.split()]


def _stem_match_score(pred_a: str, pred_b: str) -> float:
    """Score how similar two predicate names are (0.0 = no match, 1.0 = identical).

    Tightened from original: suffix-variant matching only triggers on
    very short differences (1-2 chars, e.g., Attend vs Attends), not on
    cases like HasLunch vs HasLunchAt (which is an arity/decomposition
    difference that should be classified as entity_flattening, not as
    matching predicates).
    """
    if pred_a == pred_b:
        return 1.0
    if pred_a.lower() == pred_b.lower():
        return 0.95

    a_low, b_low = pred_a.lower(), pred_b.lower()

    # Only match suffix variants with <= 2 char difference (e.g., "s", "ed")
    # Do NOT match HasLunch vs HasLunchAt (3+ chars) — those represent
    # decomposition differences that matter for classification.
    if a_low.startswith(b_low) or b_low.startswith(a_low):
        longer = max(len(a_low), len(b_low))
        shorter = min(len(a_low), len(b_low))
        if longer - shorter <= 2:
            return 0.85

    # CamelCase word overlap
    words_a = set(_camel_to_words(pred_a))
    words_b = set(_camel_to_words(pred_b))
    if not words_a or not words_b:
        return 0.0
    overlap = len(words_a & words_b)
    union = len(words_a | words_b)
    return overlap / union if union else 0.0


def compute_pred_overlap(siv_preds: Set[str], gold_preds: Set[str]) -> Tuple[float, Set[str], Set[str], Set[str]]:
    """Compute stemming-aware predicate overlap.

    Returns (overlap_ratio, exact_matches, stem_matches_siv, stem_matches_gold).
    """
    exact = siv_preds & gold_preds
    only_siv = siv_preds - exact
    only_gold = gold_preds - exact

    stem_matched_siv = set()
    stem_matched_gold = set()
    for s in only_siv:
        for g in only_gold:
            if g in stem_matched_gold:
                continue
            if _stem_match_score(s, g) >= 0.7:
                stem_matched_siv.add(s)
                stem_matched_gold.add(g)
                break

    total_unique = len(siv_preds | gold_preds)
    matched = len(exact) + len(stem_matched_siv)
    ratio = matched / total_unique if total_unique else 0.0

    return ratio, exact, stem_matched_siv, stem_matched_gold


# ── Structural analysis — NLTK tree-based ────────────────────────────────────

def _count_antecedent_conjuncts_tree(fol_str: str) -> int:
    """Count top-level antecedent conjuncts using NLTK parse tree.

    For a formula like `all x.((A(x) & B(x) & C(x)) -> D(x))`, this
    counts 3 conjuncts (A, B, C). Handles nested quantifiers and parens
    correctly — unlike the regex approach which fails on nested structures.

    Returns 0 if the formula doesn't parse or isn't an implication.
    """
    norm = normalize_fol_string(fol_str)
    expr = parse_fol(norm)
    if expr is None:
        return 0

    # Unwrap top-level quantifiers to reach the core formula
    inner = expr
    while hasattr(inner, "term") and isinstance(inner, (AllExpression, ExistsExpression)):
        inner = inner.term

    # Check for implication
    if not isinstance(inner, ImpExpression):
        return 0

    antecedent = inner.first

    # Count conjunction depth
    return _count_conjuncts(antecedent)


def _count_conjuncts(expr) -> int:
    """Count the number of top-level conjuncts in an expression."""
    if isinstance(expr, AndExpression):
        return _count_conjuncts(expr.first) + _count_conjuncts(expr.second)
    return 1


def _has_quantifier_type(fol_str: str, quant_type: str) -> bool:
    """Check if normalized FOL has a quantifier of the given type."""
    norm = normalize_fol_string(fol_str)
    if quant_type == "universal":
        return bool(re.search(r"\ball\b", norm))
    return bool(re.search(r"\bexists\b", norm))


def _count_args(fol: str, pred: str) -> Optional[int]:
    """Count the arity of a predicate in a FOL string."""
    norm = normalize_fol_string(fol)
    pattern = re.escape(pred) + r"\(([^)]*)\)"
    match = re.search(pattern, norm)
    if not match:
        # Also try raw string
        match = re.search(pattern, fol)
    if not match:
        return None
    args = [a.strip() for a in match.group(1).split(",") if a.strip()]
    return len(args)


def _detect_arity_diff(siv_fol: str, gold_fol: str, shared_preds: Set[str]) -> Tuple[List[str], str]:
    """Find predicates in both FOLs with different arities.

    Returns (diff_descriptions, error_direction) where error_direction is:
      - "gold_flattens" if FOLIO gold has lower arity (gold collapsed args)
      - "siv_flattens"  if SIV has lower arity (SIV collapsed args)
      - "mixed"         if both directions occur
    """
    diffs = []
    directions = set()
    for pred in shared_preds:
        siv_arity = _count_args(siv_fol, pred)
        gold_arity = _count_args(gold_fol, pred)
        if siv_arity is not None and gold_arity is not None and siv_arity != gold_arity:
            diffs.append(f"{pred}: SIV arity={siv_arity}, GOLD arity={gold_arity}")
            if siv_arity < gold_arity:
                directions.add("siv_flattens")
            else:
                directions.add("gold_flattens")

    if len(directions) > 1:
        direction = "mixed"
    elif directions:
        direction = directions.pop()
    else:
        direction = ""

    return diffs, direction


def _detect_quantifier_diff(siv_fol: str, gold_fol: str) -> Optional[str]:
    """Detect if quantifier types differ between SIV and FOLIO gold."""
    siv_univ = _has_quantifier_type(siv_fol, "universal")
    siv_exist = _has_quantifier_type(siv_fol, "existential")
    gold_univ = _has_quantifier_type(gold_fol, "universal")
    gold_exist = _has_quantifier_type(gold_fol, "existential")

    if siv_univ and not gold_univ and gold_exist and not siv_exist:
        return "SIV=universal, GOLD=existential"
    if siv_exist and not gold_exist and gold_univ and not siv_univ:
        return "SIV=existential, GOLD=universal"
    if siv_univ and gold_exist and not gold_univ:
        return "SIV has universal, GOLD only existential"
    if gold_univ and siv_exist and not siv_univ:
        return "GOLD has universal, SIV only existential"
    return None


# ── Per-test failure analysis ────────────────────────────────────────────────

def _analyze_test_failures(
    per_test_results: List[Dict[str, str]],
    gold_preds: Set[str],
) -> Dict[str, Any]:
    """Analyze which positive tests failed and why."""
    failed_positives = []
    passed_positives = []

    for t in per_test_results:
        if t["kind"] != "positive":
            continue
        test_preds = _extract_preds_regex(t["fol"])
        if t["verdict"] == "entailed":
            passed_positives.append({"fol": t["fol"], "preds": test_preds})
        else:
            missing_preds = test_preds - gold_preds
            failed_positives.append({
                "fol": t["fol"],
                "preds": test_preds,
                "missing_from_gold": missing_preds,
                "all_preds_in_gold": len(missing_preds) == 0,
            })

    structural_failures = [f for f in failed_positives if f["all_preds_in_gold"]]
    vocab_failures = [f for f in failed_positives if not f["all_preds_in_gold"]]

    return {
        "total_positives": len(failed_positives) + len(passed_positives),
        "passed": len(passed_positives),
        "failed": len(failed_positives),
        "structural_failures": len(structural_failures),
        "vocab_failures": len(vocab_failures),
        "structural_failure_details": [f["fol"][:100] for f in structural_failures],
    }


# ── Main categorization logic ────────────────────────────────────────────────

COLUMNS = [
    "story_id",
    "nl",
    "folio_gold_fol",
    "siv_canonical_fol",
    "top_formula_case",
    "structural_class",
    "recall",
    "category",
    "subcategory",
    "error_direction",
    "overlap_ratio",
    "failed_tests",
    "notes",
]


def categorize_premise(p: Dict[str, Any]) -> Dict[str, Any]:
    """Categorize a single premise's divergence pattern."""
    ff = p["folio_faithfulness"]

    base = {
        "story_id": p["story_id"],
        "nl": p["nl"],
        "siv_canonical_fol": p["canonical_fol"],
        "top_formula_case": p["top_formula_case"],
        "structural_class": p["structural_class"],
    }

    if ff.get("parse_error"):
        return {
            **base,
            "folio_gold_fol": ff.get("gold_fol_raw", ""),
            "recall": None,
            "category": "parse_error",
            "subcategory": "",
            "error_direction": "",
            "overlap_ratio": None,
            "failed_tests": "",
            "notes": f"normalized: {ff.get('gold_fol_normalized', '')}",
        }

    score = ff.get("score")
    if score is None:
        return {
            **base,
            "folio_gold_fol": ff.get("gold_fol_raw", ""),
            "recall": None,
            "category": "parse_error",
            "subcategory": "no_score",
            "error_direction": "",
            "overlap_ratio": None,
            "failed_tests": "",
            "notes": "score is None",
        }

    recall = score["recall"]
    gold_fol_raw = ff["gold_fol_raw"]
    gold_fol_norm = ff.get("gold_fol_normalized", normalize_fol_string(gold_fol_raw))
    siv_fol = p["canonical_fol"]

    base["folio_gold_fol"] = gold_fol_raw
    base["recall"] = recall

    if recall == 1.0:
        return {
            **base,
            "category": "perfect_agreement",
            "subcategory": "",
            "error_direction": "",
            "overlap_ratio": 1.0,
            "failed_tests": "",
            "notes": "",
        }

    # Extract predicates from both sides
    siv_preds = _extract_preds_regex(siv_fol)
    gold_preds = _extract_preds_regex(gold_fol_raw) | _extract_preds_regex(gold_fol_norm)

    # Compute overlap
    overlap_ratio, exact_matches, stem_siv, stem_gold = compute_pred_overlap(siv_preds, gold_preds)

    # Analyze test failures
    test_analysis = _analyze_test_failures(score["per_test_results"], gold_preds)

    # Extract constants
    siv_consts = _extract_constants_regex(siv_fol)
    gold_consts = _extract_constants_regex(gold_fol_raw) | _extract_constants_regex(gold_fol_norm)

    only_siv_preds = siv_preds - exact_matches - stem_siv
    only_gold_preds = gold_preds - exact_matches - stem_gold

    notes_parts = []
    if only_siv_preds:
        notes_parts.append(f"only_siv_preds={sorted(only_siv_preds)}")
    if only_gold_preds:
        notes_parts.append(f"only_gold_preds={sorted(only_gold_preds)}")
    if stem_siv:
        notes_parts.append(f"stem_matches={sorted(zip(sorted(stem_siv), sorted(stem_gold)))}")

    failed_test_str = "; ".join(test_analysis.get("structural_failure_details", []))

    def _result(category, subcategory="", error_direction=""):
        return {
            **base,
            "category": category,
            "subcategory": subcategory,
            "error_direction": error_direction,
            "overlap_ratio": round(overlap_ratio, 3),
            "failed_tests": failed_test_str,
            "notes": "; ".join(notes_parts),
        }

    # ── Classification logic ──

    # Low overlap → vocabulary divergence
    if overlap_ratio < 0.25:
        return _result("vocab_divergence_total")

    if overlap_ratio < 0.6:
        return _result("vocab_divergence_partial")

    # High overlap — look for structural patterns

    # Check for arity differences (entity flattening signal)
    shared_exact = exact_matches
    arity_diffs, arity_direction = _detect_arity_diff(siv_fol, gold_fol_norm, shared_exact)
    if arity_diffs:
        notes_parts.append(f"arity_diffs={arity_diffs}")
        return _result("entity_flattening", "; ".join(arity_diffs), arity_direction)

    # Check for quantifier mismatch
    quant_diff = _detect_quantifier_diff(siv_fol, gold_fol_norm)
    if quant_diff:
        notes_parts.append(f"quantifier_diff={quant_diff}")
        # Determine direction: who has the "wrong" quantifier?
        # This is debatable and needs manual review — just record the facts
        direction = ""
        if "SIV=existential" in quant_diff:
            direction = "siv_may_be_wrong"
        elif "SIV=universal" in quant_diff:
            direction = "gold_may_be_wrong"
        return _result("quantifier_mismatch", quant_diff, direction)

    # Check for restrictor collapse using NLTK tree traversal
    siv_conjuncts = _count_antecedent_conjuncts_tree(siv_fol)
    gold_conjuncts = _count_antecedent_conjuncts_tree(gold_fol_norm)
    if siv_conjuncts > gold_conjuncts and gold_conjuncts >= 1:
        notes_parts.append(
            f"restrictor_conjuncts: SIV={siv_conjuncts}, GOLD={gold_conjuncts}"
        )
        return _result(
            "restrictor_collapse",
            f"SIV={siv_conjuncts} vs GOLD={gold_conjuncts} conjuncts",
            "gold_drops_restrictor",
        )
    elif gold_conjuncts > siv_conjuncts and siv_conjuncts >= 1:
        notes_parts.append(
            f"restrictor_conjuncts: SIV={siv_conjuncts}, GOLD={gold_conjuncts}"
        )
        return _result(
            "restrictor_collapse",
            f"SIV={siv_conjuncts} vs GOLD={gold_conjuncts} conjuncts",
            "siv_drops_restrictor",
        )

    # Check for constant-name divergence
    if overlap_ratio >= 0.8:
        const_only_siv = siv_consts - gold_consts
        const_only_gold = gold_consts - siv_consts
        if const_only_siv or const_only_gold:
            notes_parts.append(
                f"const_only_siv={sorted(const_only_siv)}; const_only_gold={sorted(const_only_gold)}"
            )
            return _result("constant_divergence")

    # Check test failure analysis for structural signals
    if test_analysis["structural_failures"] > 0:
        notes_parts.append(
            f"structural_test_failures={test_analysis['structural_failures']}/{test_analysis['failed']}"
        )
        return _result("alternative_decomposition", "structural_test_failure")

    # Default
    return _result("vocab_divergence_partial", "moderate_overlap")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--input", type=str,
        default=str(_REPO_ROOT / "reports" / "folio_agreement.json"),
        help="Path to folio_agreement JSON report.",
    )
    ap.add_argument(
        "--output", type=str,
        default=str(_REPO_ROOT / "reports" / "folio_categorization.csv"),
        help="Path to output CSV.",
    )
    args = ap.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    per_pair = data["per_pair"]
    failures = data.get("failures", [])

    rows: List[Dict[str, Any]] = []
    for p in per_pair:
        rows.append(categorize_premise(p))

    # Write CSV
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)

    # Summary
    from collections import Counter
    cats = Counter(r["category"] for r in rows)
    print(f"Wrote {out_path}")
    print(f"Total premises categorized: {len(rows)}")
    print(f"Extraction failures (not in report): {len(failures)}")
    print()
    print("Category distribution:")
    for cat, count in cats.most_common():
        subcats = Counter(
            r["subcategory"] for r in rows if r["category"] == cat and r["subcategory"]
        )
        print(f"  {cat}: {count}")
        for subcat, sc in subcats.most_common():
            print(f"    └─ {subcat}: {sc}")

    # Highlight structural catch candidates with error direction
    structural_cats = ["restrictor_collapse", "entity_flattening", "quantifier_mismatch"]
    structural_rows = [r for r in rows if r["category"] in structural_cats]
    print(f"\n*** Structural catch candidates (need manual verification): {len(structural_rows)} ***")
    for r in structural_rows:
        print(f"  {r['category']} [{r['error_direction']}] story={r['story_id']}")
        print(f"    NL: {r['nl'][:80]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
