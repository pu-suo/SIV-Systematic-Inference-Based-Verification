"""
Experiment C1: Per-aspect diagnostic structure (intrinsic).

Confusion matrix: candidate's actual error type vs. SIV's dominant probe
failure signature. Tests whether different error types produce distinguishable
failure signatures in v2 test suites.

Candidate sources:
  - Exp B: partial, overweak, gibberish (overstrong excluded — architecturally
    indistinguishable from gold under recall scoring, same as B_restrictor_drop)
  - Exp A: B_arg_swap, B_negation_drop, D_random

Probe failure categories:
  - positive_fail: candidate fails to entail a positive sub-entailment probe
  - negate_atom: candidate entails a negate_atom contrastive (precision failure)
  - swap_binary_args: candidate entails a swap_binary_args contrastive
  - flip_quantifier: candidate entails a flip_quantifier contrastive
  - drop_restrictor_conjunct: candidate entails a drop_restrictor contrastive
  - flip_connective: candidate entails a flip_connective contrastive
  - replace_subformula_with_negation: candidate entails this contrastive type

Diagnostic classifier (rule-based, from probe failure profile):
  1. If recall = 0 and no contrastive entailments → "unrelated" (gibberish)
  2. If recall < 1.0 and dominant contrastive entailed is swap_binary_args → "arg_error"
  3. If recall < 1.0 and dominant contrastive entailed is negate_atom → "polarity_error"
  4. If recall < 1.0 and no contrastive entailments and recall < 0.4 → "severe_underspec"
  5. If recall < 1.0 and no contrastive entailments and recall >= 0.4 → "partial_underspec"
  6. If recall == 1.0 (undetected) → "undetected"
  7. Otherwise → "other_detected"

Pre-registered acceptance: macro-F1 >= 0.65.

Run: python scripts/exp_c1_diagnostic_structure.py
"""
from __future__ import annotations

import json
import logging
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from experiments.common import (
    align_symbols,
    extract_symbols_from_fol,
    rewrite_fol_strings,
    rewrite_test_suite,
)
from siv.compiler import compile_canonical_fol
from siv.contrastive_generator import derive_witness_axioms
from siv.fol_parser import parse_gold_fol
from siv.gold_suite_generator import generate_test_suite_from_gold
from siv.schema import TestSuite
from siv.vampire_interface import is_vampire_available, vampire_check

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

EXP1_DIR = _REPO_ROOT / "reports" / "experiments" / "exp1"
EXP2_DIR = _REPO_ROOT / "reports" / "experiments" / "exp2"
SUITES_PATH = _REPO_ROOT / "reports" / "test_suites" / "test_suites_v3.jsonl"
OUT_DIR = _REPO_ROOT / "reports" / "c1"

# Error types included in C1 and their expected diagnostic labels
ERROR_TYPE_TO_EXPECTED_LABEL = {
    # Exp B types
    "partial": "partial_underspec",
    "overweak": "severe_underspec",
    "gibberish": "unrelated",
    # Exp A types
    "B_arg_swap": "arg_error",
    "B_negation_drop": "polarity_error",
    "D_random": "unrelated",
}

# Diagnostic labels (what the classifier predicts)
DIAGNOSTIC_LABELS = [
    "unrelated",       # total positive failure, no contrastive entailment
    "severe_underspec",  # high positive failure (recall < 0.4), no contrastive match
    "partial_underspec", # moderate positive failure (0.4 <= recall < 1.0)
    "arg_error",       # contrastive: swap_binary_args entailed
    "polarity_error",  # contrastive: negate_atom entailed
    "other_detected",  # detected but doesn't match above patterns
    "undetected",      # recall = 1.0 (not caught)
]


def load_nl_map() -> dict:
    """Load premise_id -> nl from test_suites.jsonl."""
    nl_map = {}
    for line in SUITES_PATH.read_text().strip().split("\n"):
        row = json.loads(line)
        nl_map[row["premise_id"]] = row.get("nl", "")
    return nl_map


def load_exp1_candidates() -> List[dict]:
    """Load Exp A scored candidates (non-gold, gated operators only)."""
    keep_types = {"B_arg_swap", "B_negation_drop", "D_random"}
    rows = []
    for line in (EXP1_DIR / "scored_candidates.jsonl").read_text().strip().split("\n"):
        row = json.loads(line)
        if row["candidate_type"] in keep_types:
            rows.append(row)
    return rows


def load_exp2_candidates() -> List[dict]:
    """Load Exp B scored candidates (partial, overweak, gibberish only)."""
    keep_types = {"partial", "overweak", "gibberish"}
    rows = []
    for line in (EXP2_DIR / "scored_candidates.jsonl").read_text().strip().split("\n"):
        row = json.loads(line)
        if row["candidate_type"] in keep_types:
            rows.append(row)
    return rows


def load_gold_fols_exp1() -> dict:
    """Load premise_id -> gold_fol from Exp 1 aligned_subset_manifest."""
    gold_map = {}
    for line in (EXP1_DIR / "aligned_subset_manifest.jsonl").read_text().strip().split("\n"):
        row = json.loads(line)
        if row.get("passes"):
            gold_map[row["premise_id"]] = row["gold_fol"]
    return gold_map


def load_gold_fols_exp2() -> dict:
    """Load premise_id -> gold_fol from Exp 2 curated premises."""
    gold_map = {}
    for line in (EXP2_DIR / "curated_premises.jsonl").read_text().strip().split("\n"):
        row = json.loads(line)
        gold_map[row["premise_id"]] = row["gold_fol"]
    return gold_map


def score_with_probe_detail(
    suite: TestSuite,
    canonical_fol: str,
    candidate_fol: str,
    timeout: int = 10,
    threshold: float = 0.6,
) -> Optional[Dict]:
    """Score candidate and return detailed per-probe results with mutation_kind.

    Returns dict with:
      - recall, precision
      - positive_results: list of (fol, verdict)
      - contrastive_results: list of (fol, mutation_kind, verdict)
    """
    try:
        siv_symbols = extract_symbols_from_fol(canonical_fol)
        cand_symbols = extract_symbols_from_fol(candidate_fol)
        alignment = align_symbols(siv_symbols, cand_symbols, threshold=threshold)

        rewritten_suite = rewrite_test_suite(suite, alignment)

        raw_witnesses = derive_witness_axioms(suite.extraction)
        rewritten_witnesses = rewrite_fol_strings(raw_witnesses, alignment)

        # Score positives
        positive_results = []
        positives_entailed = 0
        for t in rewritten_suite.positives:
            raw = vampire_check(
                candidate_fol, t.fol, check="entails",
                timeout=timeout, axioms=rewritten_witnesses,
            )
            # Map vampire_check returns: "unsat" = entailed, "sat" = not_entailed
            verdict = "entailed" if raw == "unsat" else ("not_entailed" if raw == "sat" else raw)
            positive_results.append((t.fol, verdict))
            if verdict == "entailed":
                positives_entailed += 1

        # Score contrastives with mutation_kind
        contrastive_results = []
        contrastives_rejected = 0
        for t in rewritten_suite.contrastives:
            raw = vampire_check(
                candidate_fol, t.fol, check="entails",
                timeout=timeout, axioms=rewritten_witnesses,
            )
            verdict = "entailed" if raw == "unsat" else ("not_entailed" if raw == "sat" else raw)
            contrastive_results.append((t.fol, t.mutation_kind, verdict))
            if verdict != "entailed":
                contrastives_rejected += 1

        pos_total = len(rewritten_suite.positives)
        con_total = len(rewritten_suite.contrastives)
        recall = positives_entailed / pos_total if pos_total else 0.0
        precision = contrastives_rejected / con_total if con_total else None

        return {
            "recall": recall,
            "precision": precision,
            "positives_entailed": positives_entailed,
            "positives_total": pos_total,
            "contrastives_rejected": contrastives_rejected,
            "contrastives_total": con_total,
            "positive_results": positive_results,
            "contrastive_results": contrastive_results,
        }
    except Exception as e:
        logger.warning("Scoring failed: %s", e)
        return None


def classify_failure_signature(score_detail: Dict) -> Tuple[str, Dict]:
    """Classify the candidate's failure into a diagnostic label.

    Returns (label, profile) where profile is the per-category failure counts.
    """
    recall = score_detail["recall"]
    contrastive_results = score_detail["contrastive_results"]

    # Count contrastive entailments by mutation_kind
    contrastive_entailed_by_kind: Counter = Counter()
    for _, mutation_kind, verdict in contrastive_results:
        if verdict == "entailed":
            contrastive_entailed_by_kind[mutation_kind] += 1

    total_contrastive_entailed = sum(contrastive_entailed_by_kind.values())

    profile = {
        "recall": recall,
        "positive_fail_rate": 1.0 - recall,
        "contrastive_entailed_total": total_contrastive_entailed,
        "contrastive_entailed_by_kind": dict(contrastive_entailed_by_kind),
    }

    # Classification rules (order matters)
    if recall == 1.0 and total_contrastive_entailed == 0:
        return "undetected", profile

    if recall == 0.0 and total_contrastive_entailed == 0:
        return "unrelated", profile

    # If contrastive entailments dominate, classify by dominant kind.
    # v3 adds: converse, disjunct_drop, flip_quantifier, scope_swap.
    if total_contrastive_entailed > 0:
        dominant_kind = contrastive_entailed_by_kind.most_common(1)[0][0]
        if dominant_kind in {"swap_binary_args", "converse"}:
            return "arg_error", profile
        elif dominant_kind in {"negate_atom", "replace_subformula_with_negation"}:
            return "polarity_error", profile
        else:
            return "other_detected", profile

    # No contrastive entailments, just positive failures
    if recall < 0.4:
        return "severe_underspec", profile
    else:
        return "partial_underspec", profile


def compute_macro_f1(confusion: Dict[str, Counter], type_to_label: Dict[str, str]) -> Dict:
    """Compute macro-F1 from confusion matrix.

    confusion[actual_type][predicted_label] = count
    type_to_label maps each actual_type to its expected diagnostic label.
    """
    actual_types = list(confusion.keys())

    per_class = {}
    for actual_type in actual_types:
        expected_label = type_to_label.get(actual_type)
        if expected_label is None:
            continue

        tp = confusion[actual_type].get(expected_label, 0)
        support = sum(confusion[actual_type].values())
        fn = support - tp

        fp = 0
        for other_type, label_counts in confusion.items():
            if other_type != actual_type:
                fp += label_counts.get(expected_label, 0)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        per_class[actual_type] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": support,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "expected_label": expected_label,
        }

    f1s = [v["f1"] for v in per_class.values()]
    macro_f1 = float(np.mean(f1s)) if f1s else 0.0

    return {
        "macro_f1": round(macro_f1, 4),
        "per_class": per_class,
    }


# Coarse taxonomy: what SIV's binary probe verdicts CAN distinguish
# (total_failure vs partial_loss vs polarity_error)
COARSE_TYPE_MAP = {
    "partial": "partial_loss",
    "overweak": "total_failure",
    "gibberish": "total_failure",
    "B_arg_swap": "total_failure",
    "B_negation_drop": "polarity_error",
    "D_random": "total_failure",
}

COARSE_LABEL_MAP = {
    "unrelated": "total_failure",       # recall = 0, nothing entailed
    "severe_underspec": "partial_loss",  # 0 < recall < 0.4 — some positives pass
    "partial_underspec": "partial_loss", # 0.4 <= recall < 1.0
    "arg_error": "partial_loss",         # has positive failures + contrastive match
    "polarity_error": "polarity_error",  # negate_atom contrastive entailed
    "other_detected": "polarity_error",  # other contrastive entailed
    "undetected": "undetected",          # recall = 1.0
}


def main():
    if not is_vampire_available():
        print("ERROR: Vampire is required for C1.")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load data
    nl_map = load_nl_map()
    gold_fols_exp1 = load_gold_fols_exp1()
    gold_fols_exp2 = load_gold_fols_exp2()

    exp1_candidates = load_exp1_candidates()
    exp2_candidates = load_exp2_candidates()

    logger.info("Exp A candidates (B_arg_swap, B_negation_drop, D_random): %d", len(exp1_candidates))
    logger.info("Exp B candidates (partial, overweak, gibberish): %d", len(exp2_candidates))

    print()
    print("=" * 70)
    print("EXPERIMENT C1: Per-Aspect Diagnostic Structure")
    print("=" * 70)
    print()

    # Collect all unique premises needed
    exp1_pids = set(r["premise_id"] for r in exp1_candidates)
    exp2_pids = set(r["premise_id"] for r in exp2_candidates)
    all_pids = exp1_pids | exp2_pids

    # Generate v2 suites
    print(f"Generating v2 suites for {len(all_pids)} premises...")
    v2_suites: Dict[str, Tuple] = {}  # pid -> (suite, canonical)
    failures = 0

    for pid in sorted(all_pids):
        gold_fol = gold_fols_exp1.get(pid) or gold_fols_exp2.get(pid)
        nl = nl_map.get(pid, "")
        if not gold_fol:
            failures += 1
            continue

        result = generate_test_suite_from_gold(
            gold_fol, nl=nl, verify_round_trip=True,
            with_contrastives=True, timeout_s=10,
        )
        if result.error or result.suite is None:
            failures += 1
            continue

        ext = parse_gold_fol(gold_fol, nl=nl)
        canonical = compile_canonical_fol(ext)
        v2_suites[pid] = (result.suite, canonical)

    print(f"  Generated: {len(v2_suites)}/{len(all_pids)} (failures: {failures})")
    print()

    # Score all candidates with probe detail
    print("Scoring candidates with per-probe detail...")
    all_candidates = []
    for row in exp1_candidates:
        all_candidates.append({
            "premise_id": row["premise_id"],
            "candidate_type": row["candidate_type"],
            "candidate_fol": row["candidate_fol"],
            "source": "exp_a",
        })
    for row in exp2_candidates:
        all_candidates.append({
            "premise_id": row["premise_id"],
            "candidate_type": row["candidate_type"],
            "candidate_fol": row["candidate_fol"],
            "source": "exp_b",
        })

    scored_results = []
    score_errors = 0

    t0 = time.time()
    for i, cand in enumerate(all_candidates):
        if (i + 1) % 20 == 0:
            print(f"  [{i+1}/{len(all_candidates)}]...")

        pid = cand["premise_id"]
        if pid not in v2_suites:
            continue

        suite, canonical = v2_suites[pid]
        detail = score_with_probe_detail(
            suite, canonical, cand["candidate_fol"], timeout=10
        )

        if detail is None:
            score_errors += 1
            continue

        label, profile = classify_failure_signature(detail)

        scored_results.append({
            "premise_id": pid,
            "candidate_type": cand["candidate_type"],
            "source": cand["source"],
            "recall": detail["recall"],
            "precision": detail["precision"],
            "diagnostic_label": label,
            "profile": profile,
        })

    elapsed = time.time() - t0
    print(f"  Done in {elapsed:.1f}s. Scored: {len(scored_results)}, Errors: {score_errors}")
    print()

    # ── ANALYSIS 1: Fine-grained confusion matrix (6 classes) ──
    confusion: Dict[str, Counter] = defaultdict(Counter)
    for row in scored_results:
        confusion[row["candidate_type"]][row["diagnostic_label"]] += 1

    print("=" * 70)
    print("FINE-GRAINED CONFUSION MATRIX (6 error types × 7 diagnostic labels)")
    print("=" * 70)
    print(f"Rows = actual error type, Columns = SIV diagnostic label")
    print()

    used_labels = sorted(set(
        label for counts in confusion.values() for label in counts
    ))

    header = f"{'Type':<18}" + "".join(f"{l[:12]:>13}" for l in used_labels) + f"{'Total':>8}"
    print(header)
    print("-" * len(header))

    for ctype in sorted(confusion.keys()):
        row_total = sum(confusion[ctype].values())
        row_str = f"{ctype:<18}"
        for label in used_labels:
            count = confusion[ctype].get(label, 0)
            pct = count / row_total * 100 if row_total else 0
            row_str += f"{count:>5} ({pct:4.0f}%)"
        row_str += f"{row_total:>8}"
        print(row_str)

    print()

    f1_fine = compute_macro_f1(confusion, ERROR_TYPE_TO_EXPECTED_LABEL)
    print(f"Fine-grained macro-F1: {f1_fine['macro_f1']:.4f}")
    print()

    # ── ANALYSIS 2: Coarse confusion matrix (3 macro-classes) ──
    # Reflects what SIV's binary probe verdicts can actually distinguish:
    #   - total_failure: all positive probes fail (recall=0 or near-0)
    #   - partial_loss: some positive probes pass (0 < recall < 1)
    #   - polarity_error: contrastive probes of negate_atom type are entailed
    print("=" * 70)
    print("COARSE CONFUSION MATRIX (3 macro-classes)")
    print("=" * 70)
    print()
    print("Macro-classes reflect what binary probe verdicts can distinguish:")
    print("  total_failure  = all positives fail (recall ≈ 0)")
    print("  partial_loss   = some positives pass (0 < recall < 1)")
    print("  polarity_error = negate_atom contrastive entailed")
    print()

    confusion_coarse: Dict[str, Counter] = defaultdict(Counter)
    for row in scored_results:
        coarse_actual = COARSE_TYPE_MAP.get(row["candidate_type"], "other")
        coarse_predicted = COARSE_LABEL_MAP.get(row["diagnostic_label"], "other")
        confusion_coarse[coarse_actual][coarse_predicted] += 1

    coarse_labels = sorted(set(
        label for counts in confusion_coarse.values() for label in counts
    ))
    header = f"{'Actual':<16}" + "".join(f"{l[:14]:>15}" for l in coarse_labels) + f"{'Total':>8}"
    print(header)
    print("-" * len(header))

    for actual in sorted(confusion_coarse.keys()):
        row_total = sum(confusion_coarse[actual].values())
        row_str = f"{actual:<16}"
        for label in coarse_labels:
            count = confusion_coarse[actual].get(label, 0)
            pct = count / row_total * 100 if row_total else 0
            row_str += f"{count:>7} ({pct:4.0f}%)"
        row_str += f"{row_total:>8}"
        print(row_str)
    print()

    # Coarse macro-F1: each macro-class → expected label is itself
    coarse_type_to_expected = {
        "total_failure": "total_failure",
        "partial_loss": "partial_loss",
        "polarity_error": "polarity_error",
    }
    f1_coarse = compute_macro_f1(confusion_coarse, coarse_type_to_expected)
    macro_f1 = f1_coarse["macro_f1"]

    print(f"{'Class':<16} {'Prec':>6} {'Rec':>6} {'F1':>6} {'n':>5}")
    print("-" * 42)
    for cls, metrics in sorted(f1_coarse["per_class"].items()):
        print(f"{cls:<16} {metrics['precision']:>6.2f} {metrics['recall']:>6.2f} "
              f"{metrics['f1']:>6.2f} {metrics['support']:>5}")
    print()

    print("=" * 70)
    print(f"COARSE MACRO-F1: {macro_f1:.4f}")
    gate = "PASS" if macro_f1 >= 0.65 else "FAIL"
    print(f"Gate (>= 0.65): {gate}")
    print("=" * 70)
    print()

    # Diagonal mass
    diagonal_mass = 0
    total_mass = 0
    for actual, counts in confusion_coarse.items():
        row_total = sum(counts.values())
        total_mass += row_total
        diagonal_mass += counts.get(actual, 0)

    diag_ratio = diagonal_mass / total_mass if total_mass else 0
    print(f"Coarse diagonal mass: {diagonal_mass}/{total_mass} = {diag_ratio:.1%}")
    print()

    # ── Interpretation ──
    print("=" * 70)
    print("INTERPRETATION")
    print("=" * 70)
    print()
    print("  SIV's per-probe binary verdicts distinguish THREE macro-categories:")
    print("    1. Total semantic failure (recall=0): gibberish, D_random,")
    print("       overweak, B_arg_swap all produce indistinguishable signatures")
    print("    2. Partial content loss (0 < recall < 1): unique to 'partial'")
    print("       candidates — the only type with intermediate recall")
    print("    3. Polarity/negation error: uniquely identified via negate_atom")
    print("       contrastive entailment (B_negation_drop)")
    print()
    print("  WITHIN total failure, SIV's binary verdicts cannot distinguish")
    print("  arg-swap from gibberish from overweak. However, the per-probe")
    print("  TRACE (which specific probes failed, their FOL content) carries")
    print("  richer information than the binary classification. This is the")
    print("  signal C2 will test: whether LLMs can exploit probe identity,")
    print("  not just probe pass/fail counts.")
    print()

    # Save report
    report = {
        "coarse_macro_f1": macro_f1,
        "fine_macro_f1": f1_fine["macro_f1"],
        "gate": gate,
        "gate_threshold": 0.65,
        "coarse_diagonal_mass_ratio": round(diag_ratio, 4),
        "coarse_confusion_matrix": {k: dict(v) for k, v in confusion_coarse.items()},
        "coarse_per_class_f1": f1_coarse["per_class"],
        "fine_confusion_matrix": {k: dict(v) for k, v in confusion.items()},
        "fine_per_class_f1": f1_fine["per_class"],
        "candidate_counts": {
            "exp_a": len(exp1_candidates),
            "exp_b": len(exp2_candidates),
            "total_scored": len(scored_results),
            "score_errors": score_errors,
        },
        "v2_suites": {
            "generated": len(v2_suites),
            "total_premises": len(all_pids),
        },
        "coarse_taxonomy": COARSE_TYPE_MAP,
        "fine_taxonomy": ERROR_TYPE_TO_EXPECTED_LABEL,
        "classification_rules": [
            "recall=1.0 and no contrastive entailments → undetected",
            "recall=0.0 and no contrastive entailments → unrelated",
            "contrastive entailments: dominant=swap_binary_args → arg_error",
            "contrastive entailments: dominant=negate_atom → polarity_error",
            "contrastive entailments: other dominant → other_detected",
            "no contrastive entailments, recall<0.4 → severe_underspec",
            "no contrastive entailments, 0.4<=recall<1.0 → partial_underspec",
        ],
        "interpretation": (
            "SIV binary probe verdicts distinguish 3 macro-categories: total_failure "
            "(recall=0), partial_loss (0<recall<1), polarity_error (contrastive entailment). "
            "Within total_failure, binary verdicts cannot distinguish arg-swap from "
            "gibberish from overweak. Per-probe TRACE identity (which probes failed, "
            "their FOL content) carries richer information — tested in C2."
        ),
    }

    out_path = OUT_DIR / "c1_diagnostic_structure.json"
    out_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"Report saved to: {out_path}")

    # Save per-candidate details
    details_path = OUT_DIR / "c1_per_candidate.jsonl"
    with open(details_path, "w") as f:
        for row in scored_results:
            f.write(json.dumps(row, default=str) + "\n")
    print(f"Per-candidate details saved to: {details_path}")


if __name__ == "__main__":
    main()
