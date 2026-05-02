#!/usr/bin/env python3
"""Experiment 2 — Graded Correctness (SIV produces meaningful continuous scores).

Orchestrator with --step {1,2,3,4,5}.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from experiments.common import (
    load_test_suites,
    is_contrastive_eligible,
    score_bleu,
    score_bertscore,
    score_malls_le_aligned,
    score_brunello_lt_aligned,
    score_siv_strict,
    score_siv_soft,
    paired_bootstrap_ci,
    paired_permutation_p,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

EXP2_DIR = _REPO_ROOT / "reports" / "experiments" / "exp2"
TEST_SUITES_PATH = _REPO_ROOT / "reports" / "test_suites" / "test_suites.jsonl"
MANIFEST_PATH = _REPO_ROOT / "reports" / "experiments" / "exp1" / "aligned_subset_manifest.jsonl"


# ═══════════════════════════════════════════════════════════════════════════
# Structural feature detection
# ═══════════════════════════════════════════════════════════════════════════

def _has_nested_existential(formula_dict: dict | None) -> bool:
    """Recursively check for nested existential quantifiers anywhere in formula."""
    if not formula_dict:
        return False

    quant = formula_dict.get("quantification")
    if quant:
        if quant.get("inner_quantifications"):
            return True
        nucleus = quant.get("nucleus") or {}
        if nucleus.get("quantification"):
            return True
        if _has_nested_existential(nucleus):
            return True

    for op in formula_dict.get("operands") or []:
        if _has_nested_existential(op):
            return True

    return False


def _count_consequent_conjuncts(formula_dict: dict) -> int:
    """Count conjuncts in consequent/body position."""
    quant = formula_dict.get("quantification")
    if quant:
        nucleus = quant.get("nucleus") or {}
        if nucleus.get("connective") == "and":
            return len(nucleus.get("operands") or [])
        # Nested existential with conjunctive body
        nq = nucleus.get("quantification")
        if nq:
            inner_restr = nq.get("restrictor") or []
            inner_nuc = nq.get("nucleus") or {}
            if inner_nuc.get("atomic"):
                return 1 + len(inner_restr)
            if inner_nuc.get("connective") == "and":
                return len(inner_nuc.get("operands") or [])

    # Top-level conjunction (ground instances)
    if formula_dict.get("connective") == "and":
        return len(formula_dict.get("operands") or [])

    return 1


def _count_antecedent_conjuncts(formula_dict: dict) -> int:
    """Count restrictor atoms (antecedent conjuncts) for top-level universal."""
    quant = formula_dict.get("quantification")
    if quant:
        return len(quant.get("restrictor") or [])
    return 0


def _extract_structural_features(extraction_json: dict) -> dict:
    """Extract structural features from an extraction_json."""
    formula = extraction_json.get("formula") or {}
    preds = extraction_json.get("predicates") or []
    binary_preds = [p for p in preds if p.get("arity", 0) >= 2]

    ant = _count_antecedent_conjuncts(formula)
    cons = _count_consequent_conjuncts(formula)
    nested = _has_nested_existential(formula)

    return {
        "antecedent_conjunct_count": ant,
        "consequent_conjunct_count": cons,
        "has_nested_existential": nested,
        "n_binary_predicates": len(binary_preds),
    }


def _passes_structural_criteria(features: dict) -> bool:
    """Check if at least one structural feature criterion is met."""
    return (
        features["antecedent_conjunct_count"] >= 2
        or features["consequent_conjunct_count"] >= 2
        or features["has_nested_existential"]
        or features["n_binary_predicates"] >= 2
    )


# ═══════════════════════════════════════════════════════════════════════════
# Step 1 — Curate premises
# ═══════════════════════════════════════════════════════════════════════════

def step1_curate():
    """Select structurally-rich premises for graded-correctness experiment."""
    logger.info("Step 1: Curating premises for Exp 2")

    # Load passing premise IDs from Exp 1 manifest
    passing_ids = set()
    manifest_gold = {}
    for line in MANIFEST_PATH.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("passes"):
            passing_ids.add(row["premise_id"])
            manifest_gold[row["premise_id"]] = row.get("gold_fol", "")

    logger.info("Aligned-subset size: %d", len(passing_ids))

    # Load test suites
    suites = load_test_suites(TEST_SUITES_PATH)

    # Apply primary criteria
    candidates = []
    for pid in sorted(passing_ids):
        if pid not in suites:
            continue
        row = suites[pid]
        n_pos = len(row.get("positives") or [])
        n_contr = len(row.get("contrastives") or [])

        # Primary: >=2 positives, >=1 contrastive
        if n_pos < 2 or n_contr < 1:
            continue

        # Primary: structural feature
        ej = row.get("extraction_json") or {}
        features = _extract_structural_features(ej)
        if not _passes_structural_criteria(features):
            continue

        candidates.append({
            "premise_id": pid,
            "nl": row.get("nl", ""),
            "gold_fol": manifest_gold.get(pid, ""),
            "siv_canonical_fol": row.get("canonical_fol", ""),
            "structural_features": features,
            "n_positives": n_pos,
            "n_contrastives": n_contr,
        })

    logger.info("Premises passing primary criteria: %d", len(candidates))

    if len(candidates) < 40:
        logger.error("ABORT: fewer than 40 premises pass criteria (%d)", len(candidates))
        sys.exit(1)

    # Secondary sort: contrastive count DESC, then structural richness DESC, then diversity
    def sort_key(c):
        f = c["structural_features"]
        richness = (f["antecedent_conjunct_count"] + f["consequent_conjunct_count"]
                    + int(f["has_nested_existential"]) + f["n_binary_predicates"])
        return (-c["n_contrastives"], -richness, c["premise_id"])

    candidates.sort(key=sort_key)

    # Take top 50 (or all if fewer)
    selected = candidates[:50]

    # Assign selection rank
    for i, c in enumerate(selected, 1):
        c["selection_rank"] = i

    # Write output
    EXP2_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EXP2_DIR / "curated_premises.jsonl"
    with open(out_path, "w") as f:
        for c in selected:
            f.write(json.dumps(c) + "\n")

    logger.info("Wrote %d curated premises to %s", len(selected), out_path)

    # Summary stats
    classes = Counter()
    for c in selected:
        f = c["structural_features"]
        if f["consequent_conjunct_count"] >= 2:
            classes["conjunctive_consequent"] += 1
        if f["antecedent_conjunct_count"] >= 2:
            classes["conjunctive_antecedent"] += 1
        if f["has_nested_existential"]:
            classes["nested_existential"] += 1
        if f["n_binary_predicates"] >= 2:
            classes["binary_predicates_ge2"] += 1

    logger.info("Structural feature distribution in selected:")
    for cls, cnt in classes.most_common():
        logger.info("  %s: %d", cls, cnt)

    # Write run metadata
    meta = {
        "step": 1,
        "aligned_subset_size": len(passing_ids),
        "premises_passing_primary": len(candidates),
        "premises_selected": len(selected),
        "target_was_50": True,
        "deviations": [],
    }
    if len(selected) < 50:
        meta["deviations"].append(
            f"Only {len(selected)} premises pass primary criteria (target 50, minimum 40). "
            f"All {len(selected)} selected without relaxing criteria."
        )

    meta_path = EXP2_DIR / "run_metadata.json"
    if meta_path.exists():
        existing = json.loads(meta_path.read_text())
        existing["step1"] = meta
        meta_path.write_text(json.dumps(existing, indent=2) + "\n")
    else:
        meta_path.write_text(json.dumps({"step1": meta}, indent=2) + "\n")

    logger.info("Done. run_metadata.json updated.")


# ═══════════════════════════════════════════════════════════════════════════
# Step 2 — Generate graded candidates via LLM + Vampire verification
# ═══════════════════════════════════════════════════════════════════════════

CANDIDATE_GEN_PROMPT = """\
You are constructing test cases for a first-order-logic translation metric.

Premise (natural language): {nl}
Gold FOL translation: {gold_fol}
Predicates available: {predicate_signatures}
Constants available: {constants}

Produce 4 candidate FOL formulas, each using ONLY the predicates and \
constants listed above. Each must be syntactically valid FOL using the \
same convention as gold (all/exists for quantifiers, ->/&/|/<-> for \
connectives, - for negation).

CANDIDATE_PARTIAL: A formula that captures part of what gold says but is \
missing a key consequent or conjunct. It should be logically weaker than \
gold (gold entails it) but not equivalent. Drop one or more conjuncts or \
consequents.

CANDIDATE_OVERWEAK: A formula that is logically WEAKER than gold — gold \
entails it, but it does not entail gold. Drop a restrictor or weaken a \
quantifier (e.g., universal to existential). It must be DIFFERENT from \
CANDIDATE_PARTIAL — use a different weakening strategy.

CANDIDATE_OVERSTRONG: A formula that is logically STRONGER than gold — \
it entails gold, but gold does not entail it. Add a restrictor, strengthen \
a quantifier, or add an extra conjunct that gold doesn't assert.

CANDIDATE_GIBBERISH: A formula that is syntactically valid but semantically \
unrelated to the premise. Use the available predicates but in a way that \
has nothing to do with what the premise says.

Output exactly 4 lines. Each line: LABEL: <fol_formula>
No explanation. No commentary. No markdown."""


_LLM_CACHE_DIR = EXP2_DIR / ".llm_cache"


def _cache_key_for_prompt(premise_id: str, attempt: int) -> str:
    return f"{premise_id}_attempt{attempt}"


def _cache_get_llm(premise_id: str, attempt: int) -> Optional[str]:
    _LLM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _LLM_CACHE_DIR / f"{_cache_key_for_prompt(premise_id, attempt)}.json"
    if path.exists():
        return json.loads(path.read_text()).get("response")
    return None


def _cache_put_llm(premise_id: str, attempt: int, response: str):
    _LLM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _LLM_CACHE_DIR / f"{_cache_key_for_prompt(premise_id, attempt)}.json"
    path.write_text(json.dumps({"premise_id": premise_id, "attempt": attempt, "response": response}))


def _call_llm(prompt: str, premise_id: str, attempt: int = 0) -> str:
    """Call GPT-4o via OpenAI API. Caches responses."""
    cached = _cache_get_llm(premise_id, attempt)
    if cached is not None:
        return cached

    from openai import OpenAI
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    temperature = 0.0 if attempt == 0 else 0.3
    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=1024,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.choices[0].message.content
    _cache_put_llm(premise_id, attempt, text)
    return text


def _parse_llm_response(response: str) -> dict[str, str]:
    """Parse 4-line LLM response into {label: fol} dict."""
    result = {}
    for line in response.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # Match CANDIDATE_PARTIAL: ..., CANDIDATE_OVERWEAK: ..., etc.
        match = re.match(r"^(CANDIDATE_\w+)\s*:\s*(.+)$", line)
        if match:
            label = match.group(1).upper()
            fol = match.group(2).strip()
            result[label] = fol
    return result


_LABEL_TO_TYPE = {
    "CANDIDATE_PARTIAL": "partial",
    "CANDIDATE_OVERWEAK": "overweak",
    "CANDIDATE_OVERSTRONG": "overstrong",
    "CANDIDATE_GIBBERISH": "gibberish",
}


def _classify_by_entailment(forward: Optional[bool], reverse: Optional[bool]) -> str:
    """Classify candidate by entailment pattern.

    forward = check_entailment(gold, candidate) — gold |= candidate?
    reverse = check_entailment(candidate, gold) — candidate |= gold?
    """
    if forward is None or reverse is None:
        return "verification_failed"
    if forward and reverse:
        return "equivalent"
    if forward and not reverse:
        return "overweak"
    if not forward and reverse:
        return "overstrong"
    return "incompatible"


def _format_predicate_signatures(extraction_json: dict) -> str:
    preds = extraction_json.get("predicates") or []
    parts = []
    for p in preds:
        args = ", ".join(p.get("arg_types", []))
        parts.append(f"{p['name']}/{p['arity']}({args})")
    return ", ".join(parts)


def _format_constants(extraction_json: dict) -> str:
    constants = extraction_json.get("constants") or []
    if not constants:
        return "(none)"
    return ", ".join(c["id"] for c in constants)


def step2_generate():
    """Generate graded candidates via LLM + Vampire verification."""
    from dotenv import load_dotenv
    load_dotenv(_REPO_ROOT / ".env")

    from siv.vampire_interface import check_entailment, setup_vampire
    from siv.fol_utils import parse_fol
    setup_vampire()

    logger.info("Step 2: Generating graded candidates")

    # Load curated premises
    curated_path = EXP2_DIR / "curated_premises.jsonl"
    if not curated_path.exists():
        logger.error("Run step 1 first: %s not found", curated_path)
        sys.exit(1)

    premises = []
    for line in curated_path.read_text().splitlines():
        if line.strip():
            premises.append(json.loads(line))
    logger.info("Loaded %d curated premises", len(premises))

    # Load test suites (for extraction_json — predicate/constant info)
    suites = load_test_suites(TEST_SUITES_PATH)

    all_candidates = []
    category_counts = Counter()
    api_cost_input = 0
    api_cost_output = 0
    total_calls = 0

    for premise in premises:
        pid = premise["premise_id"]
        canonical = premise["siv_canonical_fol"]
        nl = premise["nl"]
        suite_row = suites.get(pid, {})
        ej = suite_row.get("extraction_json", {})

        pred_sigs = _format_predicate_signatures(ej)
        constants = _format_constants(ej)

        # Try up to 2 attempts per premise (temp=0 then temp=0.3)
        for attempt in range(2):
            prompt = CANDIDATE_GEN_PROMPT.format(
                nl=nl,
                gold_fol=canonical,
                predicate_signatures=pred_sigs,
                constants=constants,
            )

            response = _call_llm(prompt, pid, attempt)
            total_calls += 1
            parsed = _parse_llm_response(response)

            if len(parsed) < 4 and attempt == 0:
                logger.warning("%s attempt %d: only parsed %d candidates, retrying",
                               pid, attempt, len(parsed))
                continue

            # Verify each candidate with Vampire
            for label, fol in parsed.items():
                ctype = _LABEL_TO_TYPE.get(label)
                if ctype is None:
                    continue

                # Check syntactic validity
                expr = parse_fol(fol)
                if expr is None:
                    all_candidates.append({
                        "premise_id": pid,
                        "candidate_type": ctype,
                        "candidate_fol": fol,
                        "llm_claimed_type": ctype,
                        "vampire_forward": None,
                        "vampire_reverse": None,
                        "vampire_category": "parse_failed",
                        "kept": False,
                        "drop_reason": "candidate parse failure",
                    })
                    continue

                # Vampire verification
                forward = check_entailment(canonical, fol, timeout=10)
                reverse = check_entailment(fol, canonical, timeout=10)
                vampire_cat = _classify_by_entailment(forward, reverse)

                # Determine if candidate is kept based on entailment pattern.
                # "partial" and "overweak" are both forward=True, reverse=False
                # (gold entails them). We distinguish by construction method:
                # - partial: drops a conjunct/consequent
                # - overweak: drops a restrictor or weakens a quantifier
                # Both verify as "overweak" in entailment terms.
                kept = False
                drop_reason = None

                if vampire_cat == "equivalent":
                    drop_reason = "equivalent to gold"
                elif vampire_cat == "verification_failed":
                    drop_reason = "vampire timeout or unavailable"
                elif ctype == "partial":
                    # Partial should be overweak (gold |= partial) or incompatible
                    kept = vampire_cat in ("overweak", "incompatible")
                    if not kept:
                        drop_reason = f"vampire says {vampire_cat}, expected overweak/incompatible for partial"
                elif ctype == "overweak":
                    kept = vampire_cat == "overweak"
                    if not kept:
                        drop_reason = f"vampire says {vampire_cat}, expected overweak"
                elif ctype == "overstrong":
                    kept = vampire_cat == "overstrong"
                    if not kept:
                        drop_reason = f"vampire says {vampire_cat}, expected overstrong"
                elif ctype == "gibberish":
                    # Gibberish should be incompatible (or possibly overweak/overstrong by accident)
                    kept = vampire_cat == "incompatible"
                    if not kept:
                        drop_reason = f"vampire says {vampire_cat}, expected incompatible for gibberish"

                if kept:
                    category_counts[ctype] += 1

                all_candidates.append({
                    "premise_id": pid,
                    "candidate_type": ctype,
                    "candidate_fol": fol,
                    "llm_claimed_type": ctype,
                    "vampire_forward": forward,
                    "vampire_reverse": reverse,
                    "vampire_category": vampire_cat,
                    "kept": kept,
                    "drop_reason": drop_reason,
                })

            # If first attempt got all 4, no need for retry
            if len(parsed) >= 4:
                break

        if (premises.index(premise) + 1) % 10 == 0:
            logger.info("  Processed %d/%d premises. Kept so far: %s",
                        premises.index(premise) + 1, len(premises),
                        dict(category_counts))

    # Write all candidates (kept and dropped)
    out_path = EXP2_DIR / "verified_candidates.jsonl"
    with open(out_path, "w") as f:
        for c in all_candidates:
            f.write(json.dumps(c) + "\n")

    kept_count = sum(1 for c in all_candidates if c["kept"])
    logger.info("Total candidates generated: %d", len(all_candidates))
    logger.info("Kept (verified match): %d", kept_count)
    logger.info("Per-category kept: %s", dict(category_counts))

    # Check yield threshold
    below_30 = [cat for cat, cnt in category_counts.items() if cnt < 30]
    if below_30:
        logger.warning("Categories below 30 verified candidates: %s", below_30)
        logger.warning("Consider running retry pass or surfacing for discussion.")

    # Update metadata
    meta_path = EXP2_DIR / "run_metadata.json"
    existing = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    existing["step2"] = {
        "total_candidates": len(all_candidates),
        "kept_candidates": kept_count,
        "per_category_kept": dict(category_counts),
        "total_api_calls": total_calls,
        "premises_processed": len(premises),
        "categories_below_30": below_30,
    }
    meta_path.write_text(json.dumps(existing, indent=2) + "\n")
    logger.info("Done. Wrote %s", out_path)


# ═══════════════════════════════════════════════════════════════════════════
# Step 3 — Smoke test
# ═══════════════════════════════════════════════════════════════════════════

def _score_candidate_all_metrics(
    suite_row: dict, candidate_fol: str, gold_fol: str
) -> dict:
    """Score a single candidate with all 7 metrics. Returns metric name -> score."""
    results = {}

    # Reference-free: SIV
    siv_strict_report = score_siv_strict(suite_row, candidate_fol, timeout=10)
    results["siv_strict_recall"] = siv_strict_report.recall if siv_strict_report else None

    siv_soft_report = score_siv_soft(suite_row, candidate_fol, timeout=10, threshold=0.6)
    if siv_soft_report:
        results["siv_soft_recall"] = siv_soft_report.recall
        results["siv_soft_precision"] = siv_soft_report.precision
        results["siv_soft_f1"] = siv_soft_report.f1
    else:
        results["siv_soft_recall"] = None
        results["siv_soft_precision"] = None
        results["siv_soft_f1"] = None

    # Reference-based: need gold_fol
    results["bleu"] = score_bleu(candidate_fol, gold_fol)
    results["bertscore"] = score_bertscore(candidate_fol, gold_fol)
    results["malls_le_aligned"] = score_malls_le_aligned(candidate_fol, gold_fol, timeout=10)
    results["brunello_lt_aligned"] = score_brunello_lt_aligned(candidate_fol, gold_fol, timeout=10)

    return results


def step3_smoke_test():
    """Score 5 premises with all 4 types, verify gradedness signal."""
    logger.info("Step 3: Smoke test")

    # Load verified candidates
    cands_path = EXP2_DIR / "verified_candidates.jsonl"
    if not cands_path.exists():
        logger.error("Run step 2 first")
        sys.exit(1)

    from collections import defaultdict
    by_premise = defaultdict(dict)
    with open(cands_path) as f:
        for line in f:
            row = json.loads(line)
            if row["kept"]:
                by_premise[row["premise_id"]][row["candidate_type"]] = row["candidate_fol"]

    # Select 5 premises with all 4 types
    full_premises = [pid for pid, types in by_premise.items() if len(types) == 4]
    smoke_premises = sorted(full_premises)[:5]
    logger.info("Smoke premises: %s", smoke_premises)

    # Load test suites and curated premises (for gold_fol)
    suites = load_test_suites(TEST_SUITES_PATH)
    gold_fols = {}
    for line in (EXP2_DIR / "curated_premises.jsonl").read_text().splitlines():
        row = json.loads(line)
        gold_fols[row["premise_id"]] = row["siv_canonical_fol"]

    # Score each premise × candidate type (including gold/canonical as baseline)
    smoke_results = []
    for pid in smoke_premises:
        suite_row = suites[pid]
        canonical = gold_fols[pid]
        gold_fol = suite_row.get("gold_fol", canonical)  # FOLIO gold for ref-based

        logger.info("  Scoring %s...", pid)

        # Score the canonical (SIV's gold) as reference point
        gold_scores = _score_candidate_all_metrics(suite_row, canonical, gold_fol)
        smoke_results.append({
            "premise_id": pid, "candidate_type": "gold",
            "candidate_fol": canonical, "scores": gold_scores,
        })

        # Score each candidate type
        for ctype in ["overstrong", "partial", "overweak", "gibberish"]:
            cfol = by_premise[pid].get(ctype)
            if cfol is None:
                continue
            scores = _score_candidate_all_metrics(suite_row, cfol, gold_fol)
            smoke_results.append({
                "premise_id": pid, "candidate_type": ctype,
                "candidate_fol": cfol, "scores": scores,
            })

    # Write raw smoke results
    smoke_path = EXP2_DIR / "smoke_test.json"
    smoke_path.write_text(json.dumps(smoke_results, indent=2) + "\n")

    # Evaluate pass criteria
    verdicts = []

    # 1. SIV-soft on gold >= 0.9
    gold_siv_scores = [r["scores"]["siv_soft_recall"] for r in smoke_results
                       if r["candidate_type"] == "gold" and r["scores"]["siv_soft_recall"] is not None]
    gold_pass = sum(1 for s in gold_siv_scores if s >= 0.9)
    verdicts.append(f"SIV-soft on gold >= 0.9: {gold_pass}/{len(gold_siv_scores)}")

    # 2. SIV-soft on partial: strictly between gold and overweak on >= 3/5
    gradedness_pass = 0
    for pid in smoke_premises:
        gold_s = next((r["scores"]["siv_soft_recall"] for r in smoke_results
                       if r["premise_id"] == pid and r["candidate_type"] == "gold"), None)
        partial_s = next((r["scores"]["siv_soft_recall"] for r in smoke_results
                          if r["premise_id"] == pid and r["candidate_type"] == "partial"), None)
        overweak_s = next((r["scores"]["siv_soft_recall"] for r in smoke_results
                           if r["premise_id"] == pid and r["candidate_type"] == "overweak"), None)
        if all(s is not None for s in [gold_s, partial_s, overweak_s]):
            # Partial should be between gold and overweak (or equal to gold if partial is very close)
            if partial_s < gold_s and partial_s > overweak_s:
                gradedness_pass += 1
            elif partial_s <= gold_s and partial_s > overweak_s:
                gradedness_pass += 1  # Allow equal to gold

    verdicts.append(f"SIV-soft partial between gold and overweak: {gradedness_pass}/5")

    # 3. MALLS-LE and Brunello-LT on non-gold: all 0.0
    ref_based_zero = 0
    ref_based_total = 0
    for r in smoke_results:
        if r["candidate_type"] == "gold":
            continue
        for metric in ["malls_le_aligned", "brunello_lt_aligned"]:
            val = r["scores"].get(metric)
            if val is not None:
                ref_based_total += 1
                if val == 0.0:
                    ref_based_zero += 1
    verdicts.append(f"MALLS/Brunello on non-gold = 0.0: {ref_based_zero}/{ref_based_total}")

    # 4. SIV-soft on gibberish: strictly below all other types
    gibberish_lowest = 0
    for pid in smoke_premises:
        gib_s = next((r["scores"]["siv_soft_recall"] for r in smoke_results
                      if r["premise_id"] == pid and r["candidate_type"] == "gibberish"), None)
        other_scores = [r["scores"]["siv_soft_recall"] for r in smoke_results
                        if r["premise_id"] == pid and r["candidate_type"] not in ("gibberish",)
                        and r["scores"]["siv_soft_recall"] is not None]
        if gib_s is not None and other_scores:
            if gib_s < min(other_scores):
                gibberish_lowest += 1
    verdicts.append(f"SIV-soft gibberish < all others: {gibberish_lowest}/5")

    # Print score table
    logger.info("\n=== SMOKE TEST SCORE TABLE ===")
    logger.info("%-8s %-12s %8s %8s %8s %8s %8s", "PID", "Type", "SIV-sft", "MALLS", "Brunello", "BLEU", "BERTSc")
    for r in smoke_results:
        s = r["scores"]
        logger.info("%-8s %-12s %8s %8s %8s %8s %8s",
                    r["premise_id"][-4:], r["candidate_type"],
                    f"{s['siv_soft_recall']:.3f}" if s["siv_soft_recall"] is not None else "None",
                    f"{s['malls_le_aligned']:.1f}" if s["malls_le_aligned"] is not None else "None",
                    f"{s['brunello_lt_aligned']:.1f}" if s["brunello_lt_aligned"] is not None else "None",
                    f"{s['bleu']:.3f}" if s["bleu"] is not None else "None",
                    f"{s['bertscore']:.3f}" if s["bertscore"] is not None else "None")

    logger.info("\n=== VERDICTS ===")
    for v in verdicts:
        logger.info("  %s", v)

    # Overall pass: gradedness >= 3 AND ref-based metrics all zero on non-gold
    overall_pass = gradedness_pass >= 3 and ref_based_zero == ref_based_total
    logger.info("\n  OVERALL: %s", "PASS" if overall_pass else "FAIL")

    if not overall_pass:
        logger.warning("SMOKE TEST FAILED. Do not proceed to step 4.")
        logger.warning("Inspect smoke_test.json for details.")

    # Update metadata
    meta_path = EXP2_DIR / "run_metadata.json"
    existing = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    existing["step3"] = {
        "smoke_premises": smoke_premises,
        "verdicts": verdicts,
        "overall_pass": overall_pass,
        "gradedness_pass_count": gradedness_pass,
    }
    meta_path.write_text(json.dumps(existing, indent=2) + "\n")


# ═══════════════════════════════════════════════════════════════════════════
# Step 4 — Full scoring
# ═══════════════════════════════════════════════════════════════════════════

def step4_full_scoring():
    """Score all kept candidates with all metrics."""
    logger.info("Step 4: Full scoring")

    # Load verified candidates (kept only)
    cands_path = EXP2_DIR / "verified_candidates.jsonl"
    kept = []
    with open(cands_path) as f:
        for line in f:
            row = json.loads(line)
            if row["kept"]:
                kept.append(row)
    logger.info("Loaded %d kept candidates", len(kept))

    # Load test suites and curated premises
    suites = load_test_suites(TEST_SUITES_PATH)
    gold_fols = {}
    canonical_fols = {}
    for line in (EXP2_DIR / "curated_premises.jsonl").read_text().splitlines():
        row = json.loads(line)
        canonical_fols[row["premise_id"]] = row["siv_canonical_fol"]
        gold_fols[row["premise_id"]] = row.get("gold_fol", row["siv_canonical_fol"])

    # Score each candidate
    scored = []
    start_time = time.time()

    for i, cand in enumerate(kept):
        pid = cand["premise_id"]
        cfol = cand["candidate_fol"]
        suite_row = suites[pid]
        gold_fol = gold_fols.get(pid, "")
        canonical = canonical_fols.get(pid, "")

        scores = _score_candidate_all_metrics(suite_row, cfol, gold_fol)

        # Also score gold/canonical for this premise (once per premise)
        scored.append({
            "premise_id": pid,
            "candidate_type": cand["candidate_type"],
            "candidate_fol": cfol,
            "scores": scores,
        })

        if (i + 1) % 25 == 0:
            elapsed = time.time() - start_time
            logger.info("  Scored %d/%d (%.1fs elapsed)", i + 1, len(kept), elapsed)

    # Also score gold (SIV canonical) for each premise
    scored_premises = set()
    for cand in kept:
        pid = cand["premise_id"]
        if pid in scored_premises:
            continue
        scored_premises.add(pid)
        suite_row = suites[pid]
        canonical = canonical_fols[pid]
        gold_fol = gold_fols.get(pid, canonical)
        scores = _score_candidate_all_metrics(suite_row, canonical, gold_fol)
        scored.append({
            "premise_id": pid,
            "candidate_type": "gold",
            "candidate_fol": canonical,
            "scores": scores,
        })

    elapsed = time.time() - start_time
    logger.info("Total scoring time: %.1fs", elapsed)

    # Write output
    out_path = EXP2_DIR / "scored_candidates.jsonl"
    with open(out_path, "w") as f:
        for row in scored:
            f.write(json.dumps(row) + "\n")
    logger.info("Wrote %d scored rows to %s", len(scored), out_path)

    # Update metadata
    meta_path = EXP2_DIR / "run_metadata.json"
    existing = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    existing["step4"] = {
        "scored_candidates": len(kept),
        "scored_gold_rows": len(scored_premises),
        "total_rows": len(scored),
        "wall_time_s": round(elapsed, 1),
    }
    meta_path.write_text(json.dumps(existing, indent=2) + "\n")


# ═══════════════════════════════════════════════════════════════════════════
# Step 5 — Primary analysis
# ═══════════════════════════════════════════════════════════════════════════

def step5_analysis():
    """Produce tables, rank correlations, and figures for Exp 2."""
    import numpy as np
    from scipy import stats as scipy_stats

    logger.info("Step 5: Primary analysis")

    # Load scored candidates
    scored_path = EXP2_DIR / "scored_candidates.jsonl"
    if not scored_path.exists():
        logger.error("Run step 4 first")
        sys.exit(1)

    scored = []
    for line in scored_path.read_text().splitlines():
        if line.strip():
            scored.append(json.loads(line))
    logger.info("Loaded %d scored rows", len(scored))

    # ── Table 2.5a — Mean score per (metric, candidate_type) ──

    from collections import defaultdict
    by_type_metric = defaultdict(list)
    metrics = ["siv_soft_recall", "malls_le_aligned", "brunello_lt_aligned", "bleu", "bertscore"]

    for row in scored:
        ctype = row["candidate_type"]
        for m in metrics:
            val = row["scores"].get(m)
            if val is not None:
                by_type_metric[(ctype, m)].append(val)

    type_order = ["gold", "overstrong", "partial", "overweak", "gibberish"]

    # Compute means and bootstrap CIs
    table_a_rows = []
    for ctype in type_order:
        row_data = {"candidate_type": ctype}
        for m in metrics:
            vals = by_type_metric.get((ctype, m), [])
            if vals:
                arr = np.array(vals)
                mean = float(arr.mean())
                # Bootstrap CI for mean
                rng = np.random.RandomState(42)
                boot_means = [rng.choice(arr, size=len(arr), replace=True).mean()
                              for _ in range(1000)]
                ci_lo = float(np.percentile(boot_means, 2.5))
                ci_hi = float(np.percentile(boot_means, 97.5))
                row_data[m] = {"mean": round(mean, 4), "ci_lo": round(ci_lo, 4), "ci_hi": round(ci_hi, 4), "n": len(vals)}
            else:
                row_data[m] = {"mean": None, "ci_lo": None, "ci_hi": None, "n": 0}
        table_a_rows.append(row_data)

    # Write Table 2.5a
    table_a_path = EXP2_DIR / "mean_by_type.json"
    table_a_path.write_text(json.dumps(table_a_rows, indent=2) + "\n")

    # Also write CSV
    csv_path = EXP2_DIR / "mean_by_type.csv"
    with open(csv_path, "w") as f:
        f.write("candidate_type," + ",".join(f"{m}_mean,{m}_ci_lo,{m}_ci_hi" for m in metrics) + "\n")
        for row_data in table_a_rows:
            parts = [row_data["candidate_type"]]
            for m in metrics:
                d = row_data[m]
                parts.extend([
                    str(d["mean"]) if d["mean"] is not None else "",
                    str(d["ci_lo"]) if d["ci_lo"] is not None else "",
                    str(d["ci_hi"]) if d["ci_hi"] is not None else "",
                ])
            f.write(",".join(parts) + "\n")

    logger.info("Table 2.5a written to %s", csv_path)

    # ── Table 2.5b — Spearman rank correlation (HEADLINE NUMBER) ──

    # Ground-truth ranks: gold=1, overstrong=2, partial=2, overweak=3, gibberish=4
    gt_ranks = {"gold": 1, "overstrong": 2, "partial": 2, "overweak": 3, "gibberish": 4}

    # Group scored rows by premise
    by_premise = defaultdict(dict)
    for row in scored:
        by_premise[row["premise_id"]][row["candidate_type"]] = row["scores"]

    # For each premise, compute Spearman rho per metric (on non-gold candidates)
    # Use all 4 non-gold types for ranking
    rho_per_metric = defaultdict(list)
    premise_ids_used = []

    for pid, type_scores in by_premise.items():
        # Need at least 3 non-gold types for meaningful correlation
        non_gold_types = [t for t in ["overstrong", "partial", "overweak", "gibberish"]
                          if t in type_scores]
        if len(non_gold_types) < 3:
            continue

        premise_ids_used.append(pid)
        gt_ranks_vec = [gt_ranks[t] for t in non_gold_types]

        for m in metrics:
            metric_scores = []
            for t in non_gold_types:
                val = type_scores[t].get(m)
                metric_scores.append(val if val is not None else 0.0)

            # Higher metric score = better = lower rank, so negate for Spearman
            # Actually Spearman: we want metric to rank same as ground truth
            # Ground truth: lower rank number = better. Metric: higher score = better.
            # So correlation between (-metric_scores, gt_ranks) or equivalently
            # correlation between (metric_scores, -gt_ranks)
            if len(set(metric_scores)) > 1:  # Avoid constant arrays
                rho, _ = scipy_stats.spearmanr(metric_scores, [-r for r in gt_ranks_vec])
                rho_per_metric[m].append(rho)
            else:
                rho_per_metric[m].append(0.0)  # No discrimination

    logger.info("Premises used for rank correlation: %d", len(premise_ids_used))

    # Compute mean rho and bootstrap CI
    rank_corr_results = {}
    siv_rhos = np.array(rho_per_metric.get("siv_soft_recall", []))

    for m in metrics:
        rhos = np.array(rho_per_metric.get(m, []))
        if len(rhos) == 0:
            rank_corr_results[m] = {"mean_rho": None, "ci_lo": None, "ci_hi": None}
            continue
        mean_rho = float(rhos.mean())
        rng = np.random.RandomState(42)
        boot = [rng.choice(rhos, size=len(rhos), replace=True).mean() for _ in range(1000)]
        ci_lo = float(np.percentile(boot, 2.5))
        ci_hi = float(np.percentile(boot, 97.5))

        # Paired permutation test vs SIV-soft
        p_val = None
        if m != "siv_soft_recall" and len(siv_rhos) == len(rhos):
            p_val = float(paired_permutation_p(siv_rhos, rhos))

        rank_corr_results[m] = {
            "mean_rho": round(mean_rho, 4),
            "ci_lo": round(ci_lo, 4),
            "ci_hi": round(ci_hi, 4),
            "n_premises": len(rhos),
            "p_vs_siv": round(p_val, 4) if p_val is not None else None,
        }

    # Write Table 2.5b
    corr_path = EXP2_DIR / "rank_correlation.json"
    corr_path.write_text(json.dumps(rank_corr_results, indent=2) + "\n")

    csv_corr_path = EXP2_DIR / "rank_correlation.csv"
    with open(csv_corr_path, "w") as f:
        f.write("metric,mean_rho,ci_lo,ci_hi,n_premises,p_vs_siv\n")
        for m in metrics:
            d = rank_corr_results[m]
            f.write(f"{m},{d['mean_rho']},{d['ci_lo']},{d['ci_hi']},{d['n_premises']},{d['p_vs_siv'] or ''}\n")

    logger.info("Table 2.5b written to %s", csv_corr_path)
    logger.info("  HEADLINE: SIV-soft mean rho = %.4f [%.4f, %.4f]",
                rank_corr_results["siv_soft_recall"]["mean_rho"],
                rank_corr_results["siv_soft_recall"]["ci_lo"],
                rank_corr_results["siv_soft_recall"]["ci_hi"])

    # ── Table 2.5c — Adjacent-pair AUC ──

    # Adjacent pairs in ground truth: (overstrong, partial), (partial, overweak), (overweak, gibberish)
    adjacent_pairs = [
        ("overstrong", "partial"),
        ("partial", "overweak"),
        ("overweak", "gibberish"),
    ]

    auc_results = {m: {} for m in metrics}
    for better, worse in adjacent_pairs:
        pair_key = f"{better}_vs_{worse}"
        for m in metrics:
            scores_better = []
            scores_worse = []
            for pid, type_scores in by_premise.items():
                if better in type_scores and worse in type_scores:
                    b_val = type_scores[better].get(m)
                    w_val = type_scores[worse].get(m)
                    if b_val is not None and w_val is not None:
                        scores_better.append(b_val)
                        scores_worse.append(w_val)

            if scores_better and scores_worse:
                all_scores = np.array(scores_better + scores_worse)
                labels = np.array([1] * len(scores_better) + [0] * len(scores_worse))
                from experiments.common import auc_roc
                auc_val = auc_roc(all_scores, labels)
                auc_results[m][pair_key] = round(float(auc_val), 4)
            else:
                auc_results[m][pair_key] = None

    auc_path = EXP2_DIR / "adjacent_pair_auc.json"
    auc_path.write_text(json.dumps(auc_results, indent=2) + "\n")

    csv_auc_path = EXP2_DIR / "adjacent_pair_auc.csv"
    with open(csv_auc_path, "w") as f:
        pair_keys = [f"{b}_vs_{w}" for b, w in adjacent_pairs]
        f.write("metric," + ",".join(pair_keys) + "\n")
        for m in metrics:
            f.write(m + "," + ",".join(str(auc_results[m].get(pk, "")) for pk in pair_keys) + "\n")

    logger.info("Table 2.5c written to %s", csv_auc_path)

    # ── Figure 2.5d — Score distributions ──
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(1, len(metrics), figsize=(4 * len(metrics), 5))
        if len(metrics) == 1:
            axes = [axes]

        for ax, m in zip(axes, metrics):
            data_by_type = []
            labels = []
            for ctype in type_order:
                vals = by_type_metric.get((ctype, m), [])
                if vals:
                    data_by_type.append(vals)
                    labels.append(ctype)

            if data_by_type:
                bp = ax.boxplot(data_by_type, labels=labels, patch_artist=True)
                colors = ["#2ecc71", "#3498db", "#f39c12", "#e74c3c", "#95a5a6"]
                for patch, color in zip(bp["boxes"], colors[:len(data_by_type)]):
                    patch.set_facecolor(color)
                    patch.set_alpha(0.7)

            ax.set_title(m.replace("_", " ").title(), fontsize=9)
            ax.set_ylabel("Score")
            ax.tick_params(axis="x", rotation=45, labelsize=8)
            ax.set_ylim(-0.05, 1.05)

        plt.suptitle("Exp 2: Score Distributions by Candidate Type", fontsize=12)
        plt.tight_layout()
        fig_path = EXP2_DIR / "score_distributions.png"
        plt.savefig(fig_path, dpi=150, bbox_inches="tight")
        plt.close()
        logger.info("Figure written to %s", fig_path)
    except ImportError:
        logger.warning("matplotlib not available, skipping figure")

    # ── Acceptance check ──
    siv_rho = rank_corr_results["siv_soft_recall"]["mean_rho"]
    siv_ci_lo = rank_corr_results["siv_soft_recall"]["ci_lo"]
    malls_p = rank_corr_results["malls_le_aligned"].get("p_vs_siv")
    brunello_p = rank_corr_results["brunello_lt_aligned"].get("p_vs_siv")

    logger.info("\n=== ACCEPTANCE CHECK ===")
    logger.info("  SIV-soft mean rho: %.4f", siv_rho)
    logger.info("  SIV-soft CI lower: %.4f", siv_ci_lo)
    logger.info("  p vs MALLS-LE-aligned: %s", malls_p)
    logger.info("  p vs Brunello-LT-aligned: %s", brunello_p)

    if siv_rho >= 0.7 and siv_ci_lo >= 0.6:
        if (malls_p is not None and malls_p < 0.01 and
            brunello_p is not None and brunello_p < 0.01):
            logger.info("  RESULT: FULL ACCEPTANCE — gradedness demonstrated")
        else:
            logger.info("  RESULT: PARTIAL — rho high but p-values not significant")
    elif siv_rho >= 0.5:
        logger.info("  RESULT: PARTIAL SUPPORT — gradedness partially demonstrated (rho 0.5-0.7)")
    else:
        logger.info("  RESULT: NOT SUPPORTED — gradedness claim unsupported (rho < 0.5)")

    # Update metadata
    meta_path = EXP2_DIR / "run_metadata.json"
    existing = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    existing["step5"] = {
        "headline_rho": siv_rho,
        "headline_ci": [siv_ci_lo, rank_corr_results["siv_soft_recall"]["ci_hi"]],
        "p_vs_malls": malls_p,
        "p_vs_brunello": brunello_p,
        "n_premises_for_correlation": rank_corr_results["siv_soft_recall"]["n_premises"],
        "rank_correlation": rank_corr_results,
        "adjacent_pair_auc": auc_results,
    }
    meta_path.write_text(json.dumps(existing, indent=2) + "\n")
    logger.info("Done. All outputs in %s", EXP2_DIR)


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Experiment 2 — Graded Correctness")
    parser.add_argument("--step", type=int, choices=[1, 2, 3, 4, 5], required=True)
    args = parser.parse_args()

    if args.step == 1:
        step1_curate()
    elif args.step == 2:
        step2_generate()
    elif args.step == 3:
        step3_smoke_test()
    elif args.step == 4:
        step4_full_scoring()
    elif args.step == 5:
        step5_analysis()


if __name__ == "__main__":
    main()
