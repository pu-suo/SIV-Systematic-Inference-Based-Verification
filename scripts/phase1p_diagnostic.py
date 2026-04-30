"""Phase 1P Diagnostic: Categorize SIV vs FOLIO gold extraction disagreements.

Samples 50 premises from FOLIO train, compares SIV's canonical FOL to FOLIO gold,
and produces categorized disagreement analysis for human review.

Usage:
    python scripts/phase1p_diagnostic.py
"""
from __future__ import annotations

import csv
import json
import random
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from siv.aligner import extract_symbols_from_fol
from siv.compiler import compile_canonical_fol
from siv.fol_utils import normalize_fol_string, parse_fol
from siv.stratum_classifier import classify_stratum_from_fol

OUTPUT_DIR = _REPO_ROOT / "reports" / "phase1p_diagnostic"
SEED = 42


# ── Step 1: Sample selection ──────────────────────────────────────────────────

def load_and_sample_premises(split: str, n: int = 50) -> List[Dict[str, Any]]:
    """Load FOLIO premises, classify by stratum, stratified-sample n premises."""
    from datasets import load_dataset

    ds = load_dataset("tasksource/folio", split=split)
    seen: Set[str] = set()
    all_premises: List[Dict[str, Any]] = []
    pid_counter = 0

    for row in ds:
        nl_parts = [p.strip() for p in row["premises"].split("\n") if p.strip()]
        fol_parts = [p.strip() for p in row["premises-FOL"].split("\n") if p.strip()]
        if len(nl_parts) != len(fol_parts):
            continue
        for nl, fol in zip(nl_parts, fol_parts):
            if nl in seen:
                continue
            seen.add(nl)
            norm = normalize_fol_string(fol)
            stratum = classify_stratum_from_fol(fol) or "unparseable"
            all_premises.append({
                "premise_id": f"P{pid_counter:04d}",
                "story_id": row.get("story_id"),
                "nl": nl,
                "gold_fol": fol,
                "gold_fol_normalized": norm,
                "stratum": stratum,
            })
            pid_counter += 1

    sys.stderr.write(f"[diag] {len(all_premises)} unique premises loaded\n")

    # Stratified sampling
    strata_groups = {
        "simple": ["S1_atomic", "S2_universal_simple"],
        "compound": ["S3_universal_multi_restrictor", "S4_nested_quantifier"],
        "relational": ["S5_relational"],
        "other": ["S6_negation", "S7_existential", "S8_other", "unparseable"],
    }
    targets = {"simple": 15, "compound": 20, "relational": 10, "other": 5}

    rng = random.Random(SEED)
    sampled = []

    for group_name, strata_list in strata_groups.items():
        pool = [p for p in all_premises if p["stratum"] in strata_list]
        target_n = min(targets[group_name], len(pool))
        selected = rng.sample(pool, target_n)
        sampled.extend(selected)
        sys.stderr.write(
            f"  {group_name}: {target_n} sampled from {len(pool)} available\n"
        )

    sys.stderr.write(f"[diag] Total sampled: {len(sampled)}\n")
    return sampled


# ── Step 2: Pull SIV canonical FOL ────────────────────────────────────────────

def add_siv_extraction(premises: List[Dict[str, Any]]) -> None:
    """Look up cached SIV extractions, compile canonical FOL."""
    import os
    from dotenv import load_dotenv
    load_dotenv(_REPO_ROOT / ".env")

    from openai import OpenAI
    from siv.frozen_client import FrozenClient
    from siv.extractor import extract_sentence

    client = None
    cache_hits = 0
    cache_misses = 0

    for p in premises:
        nl = p["nl"]

        # Try extraction — it checks the cache internally
        if client is None:
            api_key = os.environ.get("OPENAI_API_KEY")
            if api_key:
                client = FrozenClient(OpenAI())
            else:
                sys.stderr.write("[diag] No OPENAI_API_KEY — can only use cached extractions\n")

        try:
            extraction = extract_sentence(nl, client)
            canonical = compile_canonical_fol(extraction)
            canonical_norm = normalize_fol_string(canonical) if canonical else ""

            p["siv_extraction"] = extraction.model_dump() if hasattr(extraction, "model_dump") else str(extraction)
            p["siv_canonical_fol"] = canonical
            p["siv_canonical_fol_normalized"] = canonical_norm
            p["siv_extraction_error"] = None
            cache_hits += 1  # approximate — can't distinguish cache hit from API call here
        except Exception as e:
            p["siv_extraction"] = None
            p["siv_canonical_fol"] = None
            p["siv_canonical_fol_normalized"] = ""
            p["siv_extraction_error"] = str(e)
            cache_misses += 1
            sys.stderr.write(f"  [diag] Extraction failed: {nl[:60]}... ({e})\n")

    sys.stderr.write(f"[diag] Extractions: {cache_hits} ok, {cache_misses} failed\n")


# ── Step 3: Programmatic disagreement detection ───────────────────────────────

def _count_quantifiers(fol_str: str) -> Dict[str, int]:
    norm = normalize_fol_string(fol_str) if fol_str else ""
    return {
        "universal": len(re.findall(r"\ball\b", norm)),
        "existential": len(re.findall(r"\bexists\b", norm)),
    }


def _count_connectives(fol_str: str) -> Dict[str, int]:
    norm = normalize_fol_string(fol_str) if fol_str else ""
    return {
        "and": norm.count(" & "),
        "or": norm.count(" | "),
        "implies": norm.count(" -> "),
        "iff": norm.count(" <-> "),
        "negation": norm.count("-"),
    }


def _max_nesting(fol_str: str) -> int:
    norm = normalize_fol_string(fol_str) if fol_str else ""
    depth = 0
    max_d = 0
    for c in norm:
        if c == "(":
            depth += 1
            max_d = max(max_d, depth)
        elif c == ")":
            depth -= 1
    return max_d


def categorize_disagreement(p: Dict[str, Any]) -> Dict[str, Any]:
    """Compute disagreement features and assign tentative category."""
    gold_norm = p.get("gold_fol_normalized", "")
    siv_norm = p.get("siv_canonical_fol_normalized", "")

    if not siv_norm:
        return {
            "tentative_category": "extraction_failure",
            "secondary_categories": [],
            "features": {"error": p.get("siv_extraction_error", "unknown")},
        }

    # Extract symbols
    siv_sym = extract_symbols_from_fol(siv_norm)
    gold_sym = extract_symbols_from_fol(gold_norm)

    siv_preds = siv_sym["predicates"]  # {name: arity}
    gold_preds = gold_sym["predicates"]
    siv_consts = siv_sym["constants"]
    gold_consts = gold_sym["constants"]

    # Predicate analysis
    siv_pred_set = set(siv_preds.keys())
    gold_pred_set = set(gold_preds.keys())
    shared_preds = siv_pred_set & gold_pred_set
    siv_only = siv_pred_set - gold_pred_set
    gold_only = gold_pred_set - siv_pred_set

    # Arity mismatches (same name, different arity)
    arity_mismatches = {
        name: (siv_preds[name], gold_preds[name])
        for name in shared_preds
        if siv_preds[name] != gold_preds[name]
    }

    # Arity distribution
    siv_arities = Counter(siv_preds.values())
    gold_arities = Counter(gold_preds.values())

    # Constants
    shared_consts = siv_consts & gold_consts
    siv_only_consts = siv_consts - gold_consts
    gold_only_consts = gold_consts - siv_consts

    # Structural features
    siv_quants = _count_quantifiers(siv_norm)
    gold_quants = _count_quantifiers(gold_norm)
    siv_conns = _count_connectives(siv_norm)
    gold_conns = _count_connectives(gold_norm)

    features = {
        "siv_predicates": {k: v for k, v in sorted(siv_preds.items())},
        "gold_predicates": {k: v for k, v in sorted(gold_preds.items())},
        "siv_only_preds": sorted(f"{n}/{siv_preds[n]}" for n in siv_only),
        "gold_only_preds": sorted(f"{n}/{gold_preds[n]}" for n in gold_only),
        "shared_preds": sorted(shared_preds),
        "arity_mismatches": {k: list(v) for k, v in arity_mismatches.items()},
        "predicate_count_diff": len(siv_preds) - len(gold_preds),
        "siv_only_constants": sorted(siv_only_consts),
        "gold_only_constants": sorted(gold_only_consts),
        "shared_constants": sorted(shared_consts),
        "siv_quantifiers": siv_quants,
        "gold_quantifiers": gold_quants,
        "siv_nesting_depth": _max_nesting(siv_norm),
        "gold_nesting_depth": _max_nesting(gold_norm),
        "siv_arity_distribution": dict(siv_arities),
        "gold_arity_distribution": dict(gold_arities),
    }

    # Heuristic category assignment
    categories = []

    # Check exact match
    if siv_norm.replace(" ", "") == gold_norm.replace(" ", ""):
        categories.append("exact_match")

    # Vocabulary-only difference
    elif (len(siv_preds) == len(gold_preds)
          and all(siv_preds.get(n) == gold_preds.get(n) for n in shared_preds)
          and not arity_mismatches
          and siv_quants == gold_quants):
        categories.append("vocabulary_only")

    else:
        # Compound vs decomposed: SIV has fewer predicates, higher arity-1 count
        if (siv_arities.get(1, 0) > gold_arities.get(1, 0)
                and len(siv_preds) < len(gold_preds)):
            categories.append("compound_vs_decomposed")

        # Arity mismatch
        if arity_mismatches:
            categories.append("arity_mismatch")

        # SIV has more unary predicates absorbing constants
        if (siv_arities.get(1, 0) > gold_arities.get(1, 0)
                and len(gold_only_consts) > len(siv_only_consts)):
            categories.append("const_vs_pred_asymmetry")

        # Opposite: gold has compound predicates, SIV decomposes
        if (len(siv_preds) > len(gold_preds)
                and gold_arities.get(1, 0) > siv_arities.get(1, 0)):
            categories.append("compound_vs_decomposed")

        # Restrictor structure difference
        if (siv_quants == gold_quants
                and abs(features["predicate_count_diff"]) <= 1
                and siv_conns.get("and", 0) != gold_conns.get("and", 0)):
            categories.append("restrictor_structure_diff")

        # Quantifier scope difference
        if siv_quants != gold_quants:
            categories.append("quantifier_scope_diff")

        # Connective difference
        if (siv_conns.get("implies", 0) != gold_conns.get("implies", 0)
                or siv_conns.get("iff", 0) != gold_conns.get("iff", 0)):
            categories.append("connective_diff")

    if not categories:
        categories.append("other")

    return {
        "tentative_category": categories[0],
        "secondary_categories": categories[1:],
        "features": features,
    }


# ── Step 4: CSV template ──────────────────────────────────────────────────────

def write_csv_template(premises: List[Dict[str, Any]], path: Path) -> None:
    """Write a CSV template for manual labeling."""
    fieldnames = [
        "premise_id", "stratum", "nl",
        "siv_canonical_fol", "gold_fol_normalized",
        "tentative_category", "secondary_categories",
        "siv_only_preds", "gold_only_preds",
        "siv_only_constants", "gold_only_constants",
        "predicate_count_diff", "arity_mismatches",
        # Human-fill columns
        "final_category", "more_principled", "linguistic_argument", "notes",
    ]

    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for p in premises:
            feat = p.get("disagreement", {}).get("features", {})
            writer.writerow({
                "premise_id": p["premise_id"],
                "stratum": p["stratum"],
                "nl": p["nl"],
                "siv_canonical_fol": p.get("siv_canonical_fol", ""),
                "gold_fol_normalized": p["gold_fol_normalized"],
                "tentative_category": p.get("disagreement", {}).get("tentative_category", ""),
                "secondary_categories": "; ".join(p.get("disagreement", {}).get("secondary_categories", [])),
                "siv_only_preds": "; ".join(feat.get("siv_only_preds", [])),
                "gold_only_preds": "; ".join(feat.get("gold_only_preds", [])),
                "siv_only_constants": "; ".join(feat.get("siv_only_constants", [])),
                "gold_only_constants": "; ".join(feat.get("gold_only_constants", [])),
                "predicate_count_diff": feat.get("predicate_count_diff", ""),
                "arity_mismatches": str(feat.get("arity_mismatches", {})),
                "final_category": "",
                "more_principled": "",
                "linguistic_argument": "",
                "notes": "",
            })

    sys.stderr.write(f"[diag] Wrote CSV template: {path}\n")


# ── Step 5: Comparison markdown ───────────────────────────────────────────────

def write_comparison_md(premises: List[Dict[str, Any]], path: Path) -> None:
    """Generate a structured comparison artifact for paper review."""
    lines = ["# SIV vs FOLIO Gold Extraction Comparison\n"]

    for p in premises:
        feat = p.get("disagreement", {}).get("features", {})
        cat = p.get("disagreement", {}).get("tentative_category", "?")
        sec = p.get("disagreement", {}).get("secondary_categories", [])

        lines.append(f"## {p['premise_id']} (story {p['story_id']}, {p['stratum']})\n")
        lines.append(f"**NL**: {p['nl']}\n")
        lines.append(f"**SIV canonical**:\n```\n{p.get('siv_canonical_fol', 'EXTRACTION FAILED')}\n```\n")
        lines.append(f"**FOLIO gold**:\n```\n{p['gold_fol']}\n```\n")
        lines.append(f"**Tentative category**: `{cat}`" +
                      (f" + `{'`, `'.join(sec)}`" if sec else "") + "\n")

        # Auto-detected differences
        lines.append("**Auto-detected differences**:\n")
        lines.append(f"- Predicate counts: SIV={len(feat.get('siv_predicates', {}))}, "
                      f"gold={len(feat.get('gold_predicates', {}))}\n")
        if feat.get("siv_only_preds"):
            lines.append(f"- SIV-only predicates: {', '.join(feat['siv_only_preds'])}\n")
        if feat.get("gold_only_preds"):
            lines.append(f"- Gold-only predicates: {', '.join(feat['gold_only_preds'])}\n")
        if feat.get("arity_mismatches"):
            lines.append(f"- Arity mismatches: {feat['arity_mismatches']}\n")
        if feat.get("siv_only_constants"):
            lines.append(f"- SIV-only constants: {', '.join(feat['siv_only_constants'])}\n")
        if feat.get("gold_only_constants"):
            lines.append(f"- Gold-only constants: {', '.join(feat['gold_only_constants'])}\n")

        lines.append("\n**Linguistic argument**: _to be filled by reviewer_\n")
        lines.append("---\n")

    path.write_text("\n".join(lines))
    sys.stderr.write(f"[diag] Wrote comparison markdown: {path}\n")


# ── Step 6: Summary report ────────────────────────────────────────────────────

def write_summary(premises: List[Dict[str, Any]], path: Path) -> None:
    """Generate summary statistics."""
    lines = ["# Phase 1P Diagnostic Summary\n"]

    # Category distribution
    cats = Counter(p.get("disagreement", {}).get("tentative_category", "?") for p in premises)
    lines.append("## Tentative Category Distribution\n")
    lines.append("| Category | Count | % |")
    lines.append("|---|---|---|")
    for cat, count in cats.most_common():
        lines.append(f"| {cat} | {count} | {count/len(premises)*100:.0f}% |")
    lines.append("")

    # Stratum distribution
    strata = Counter(p["stratum"] for p in premises)
    lines.append("## Stratum Distribution\n")
    lines.append("| Stratum | Count |")
    lines.append("|---|---|")
    for s, c in strata.most_common():
        lines.append(f"| {s} | {c} |")
    lines.append("")

    # Mechanical agreement rate
    agree_cats = {"exact_match", "vocabulary_only"}
    n_agree = sum(1 for p in premises
                  if p.get("disagreement", {}).get("tentative_category", "") in agree_cats)
    lines.append(f"## Mechanical Agreement Rate\n")
    lines.append(f"Premises where SIV and gold agree (modulo vocabulary): "
                 f"**{n_agree}/{len(premises)}** ({n_agree/len(premises)*100:.0f}%)\n")
    lines.append(f"Premises needing human review: "
                 f"**{len(premises) - n_agree}/{len(premises)}**\n")

    # Disagreement category breakdown (excluding agreement cases)
    disagree = [p for p in premises
                if p.get("disagreement", {}).get("tentative_category", "") not in agree_cats]
    if disagree:
        disagree_cats = Counter(p["disagreement"]["tentative_category"] for p in disagree)
        lines.append("## Disagreement Categories (needs review)\n")
        lines.append("| Category | Count | % of disagreements |")
        lines.append("|---|---|---|")
        for cat, count in disagree_cats.most_common():
            lines.append(f"| {cat} | {count} | {count/len(disagree)*100:.0f}% |")
        lines.append("")

        # Top examples per category
        lines.append("## Representative Examples per Category\n")
        by_cat = defaultdict(list)
        for p in disagree:
            by_cat[p["disagreement"]["tentative_category"]].append(p)

        for cat, examples in sorted(by_cat.items()):
            lines.append(f"### {cat} ({len(examples)} cases)\n")
            for ex in examples[:3]:
                lines.append(f"- **{ex['premise_id']}**: {ex['nl'][:80]}...")
                lines.append(f"  - SIV: `{(ex.get('siv_canonical_fol') or 'EXTRACTION FAILED')[:70]}`")
                lines.append(f"  - Gold: `{(ex.get('gold_fol_normalized') or '')[:70]}`")
            lines.append("")

    path.write_text("\n".join(lines))
    sys.stderr.write(f"[diag] Wrote summary: {path}\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # Step 1: Sample
    sys.stderr.write("[diag] Step 1: Sampling 50 premises...\n")
    premises = load_and_sample_premises("train", n=50)

    # Step 2: Pull SIV extractions
    sys.stderr.write("[diag] Step 2: Pulling SIV extractions...\n")
    add_siv_extraction(premises)

    # Step 3: Categorize disagreements
    sys.stderr.write("[diag] Step 3: Categorizing disagreements...\n")
    for p in premises:
        p["disagreement"] = categorize_disagreement(p)

    # Write JSONL
    jsonl_path = OUTPUT_DIR / "sample_50.jsonl"
    with jsonl_path.open("w") as f:
        for p in premises:
            f.write(json.dumps(p, default=str) + "\n")
    sys.stderr.write(f"[diag] Wrote {jsonl_path}\n")

    # Step 4: CSV template
    write_csv_template(premises, OUTPUT_DIR / "review_template.csv")

    # Step 5: Comparison markdown
    write_comparison_md(premises, OUTPUT_DIR / "comparison.md")

    # Step 6: Summary
    write_summary(premises, OUTPUT_DIR / "summary.md")

    elapsed = time.time() - t0
    sys.stderr.write(f"\n[diag] Done in {elapsed:.1f}s\n")

    # Print summary to stdout
    cats = Counter(p["disagreement"]["tentative_category"] for p in premises)
    print(f"Sample size: {len(premises)}")
    print(f"Tentative category distribution:")
    for cat, count in cats.most_common():
        print(f"  {cat:35s}: {count}")

    n_agree = sum(1 for p in premises
                  if p["disagreement"]["tentative_category"] in {"exact_match", "vocabulary_only"})
    print(f"\nMechanical agreement: {n_agree}/{len(premises)} ({n_agree/len(premises)*100:.0f}%)")
    print(f"Needs human review: {len(premises) - n_agree}/{len(premises)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
