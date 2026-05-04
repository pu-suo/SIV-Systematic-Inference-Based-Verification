"""
C2 Design Investigation 4: Effect-size estimate at locked design.

Given:
- Investigation 2: SIV-equivalence is primary outcome (label collapses to binary)
- Investigation 3: Single perturbations too easy (87% correction); use compound

Method: Run 3 conditions on GPT-4o (temperature 0) with compound perturbations:
1. Score-only: NL + perturbed + "this scored X against gold"
2. Structured probe-formula: NL + perturbed + score + failed probes with formulas
3. Shuffled-trace: same probes but pairings randomly permuted

Primary outcome: SIV score (recall against gold-derived suite)
Secondary: entailment-label match

Decision rule (Δ = structured - shuffled):
- Δ ≥ 0.15: strong effect, n=80 sufficient
- 0.05-0.15: moderate, consider n=100
- <0.05: leakage explanation supported, rethink
- structured < shuffled: debug

Run: python scripts/c2_investigation_4.py
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(_REPO_ROOT / ".env")

from datasets import load_dataset
from siv.vampire_interface import prove_strict, check_entailment, is_vampire_available
from siv.fol_utils import parse_fol
from siv.gold_suite_generator import generate_test_suite_from_gold
from siv.fol_parser import parse_gold_fol
from siv.compiler import compile_canonical_fol
from siv.scorer import score
from siv.contrastive_generator import derive_witness_axioms

OUT_DIR = _REPO_ROOT / "reports" / "c2_investigations"
FOLIO_TO_NLI = {"True": "entailment", "False": "contradiction", "Uncertain": "neutral"}


# ── Perturbation helpers ──────────────────────────────────────────────────────

def perturb_arg_swap(fol: str) -> Optional[str]:
    pattern = r'(\w+)\(([^,()]+),\s*([^,()]+)\)'
    matches = list(re.finditer(pattern, fol))
    if not matches:
        return None
    m = random.choice(matches)
    result = fol[:m.start()] + f"{m.group(1)}({m.group(3)}, {m.group(2)})" + fol[m.end():]
    return result if parse_fol(result) else None


def perturb_negation_flip(fol: str) -> Optional[str]:
    pattern = r'(?<!¬)(\w+\([^)]+\))'
    matches = list(re.finditer(pattern, fol))
    if matches:
        m = random.choice(matches)
        result = fol[:m.start()] + f"¬{m.group(1)}" + fol[m.end():]
        if parse_fol(result):
            return result
    if "¬" in fol:
        pat2 = r'¬(\w+\([^)]+\))'
        match = re.search(pat2, fol)
        if match:
            result = fol[:match.start()] + match.group(1) + fol[match.end():]
            if parse_fol(result):
                return result
    return None


def perturb_quantifier_swap(fol: str) -> Optional[str]:
    if "∀" in fol:
        return fol.replace("∀", "∃", 1) if parse_fol(fol.replace("∀", "∃", 1)) else None
    if "∃" in fol:
        return fol.replace("∃", "∀", 1) if parse_fol(fol.replace("∃", "∀", 1)) else None
    return None


def perturb_disjunction_for_conjunction(fol: str) -> Optional[str]:
    if "∧" in fol:
        result = fol.replace("∧", "∨", 1)
        return result if parse_fol(result) else None
    return None


def perturb_constant_swap(fol: str) -> Optional[str]:
    keywords = {"all", "exists", "and", "or", "not", "implies"}
    consts = re.findall(r'\b([a-z][a-zA-Z0-9]+)\b', fol)
    consts = [c for c in consts if c not in keywords and len(c) > 1]
    unique = list(set(consts))
    if len(unique) < 2:
        return None
    c1, c2 = random.sample(unique, 2)
    result = fol.replace(c1, "__TMP__").replace(c2, c1).replace("__TMP__", c2)
    return result if result != fol and parse_fol(result) else None


SINGLE_PERTURBATIONS = [
    perturb_arg_swap, perturb_negation_flip, perturb_quantifier_swap,
    perturb_disjunction_for_conjunction, perturb_constant_swap,
]


def make_compound_perturbation(fol: str) -> Optional[str]:
    """Apply 2 different perturbations to make it harder."""
    random.shuffle(SINGLE_PERTURBATIONS)
    first_result = None
    first_func = None
    for func in SINGLE_PERTURBATIONS:
        result = func(fol)
        if result:
            first_result = result
            first_func = func
            break
    if not first_result:
        return None

    # Apply a second perturbation
    remaining = [f for f in SINGLE_PERTURBATIONS if f != first_func]
    random.shuffle(remaining)
    for func in remaining:
        result = func(first_result)
        if result and result != first_result:
            return result

    # If second fails, just return single
    return first_result


# ── SIV scoring ───────────────────────────────────────────────────────────────

def get_siv_suite_and_score(gold_fol: str, candidate_fol: str, nl: str):
    """Generate v2 suite from gold and score candidate against it.
    Returns (score_value, suite_info_for_feedback) or (None, None).
    """
    try:
        result = generate_test_suite_from_gold(
            gold_fol, nl=nl, verify_round_trip=True,
            with_contrastives=True, timeout_s=10,
        )
        if result.error or result.suite is None:
            return None, None

        report = score(result.suite, candidate_fol, timeout_s=10)
        if report is None:
            return None, None

        # Build probe detail for feedback conditions
        suite = result.suite
        probe_detail = []

        # Positive probes
        for p in suite.positives:
            # Check entailment: candidate should entail positive
            ent = check_entailment(candidate_fol, p.fol, timeout=5)
            probe_detail.append({
                "type": "positive",
                "fol": p.fol,
                "expected": "entailed",
                "result": "entailed" if ent is True else ("not_entailed" if ent is False else "timeout"),
                "passed": ent is True,
            })

        # Contrastive probes
        for c in suite.contrastives:
            # Check: candidate & contrastive should be inconsistent (unsat)
            from siv.vampire_interface import vampire_check
            v = vampire_check(candidate_fol, c.fol, check="unsat", timeout=5)
            is_unsat = (v == "unsat")
            probe_detail.append({
                "type": "contrastive",
                "fol": c.fol,
                "mutation_kind": getattr(c, "mutation_kind", "unknown"),
                "expected": "inconsistent",
                "result": "inconsistent" if is_unsat else "consistent",
                "passed": is_unsat,
            })

        return report.recall, probe_detail

    except Exception as e:
        return None, None


# ── LLM correction with different feedback conditions ─────────────────────────

def build_score_only_prompt(nl: str, perturbed_fol: str, siv_score: float) -> str:
    return f"""You are given a natural language sentence and a first-order logic (FOL) translation that may contain errors. A scoring system rated this translation {siv_score:.2f}/1.00 against the gold standard.

Natural language: {nl}

Candidate FOL: {perturbed_fol}

Score: {siv_score:.2f}/1.00 (1.00 = perfect match to gold)

Provide ONLY the corrected FOL formula. Do not explain."""


def build_structured_prompt(nl: str, perturbed_fol: str, siv_score: float, probe_detail: list) -> str:
    failed_probes = [p for p in probe_detail if not p["passed"]]
    probe_lines = []
    for p in failed_probes[:8]:  # Limit to 8 most informative
        if p["type"] == "positive":
            probe_lines.append(f"  FAILED positive: {p['fol']} (should be entailed but is not)")
        else:
            probe_lines.append(f"  FAILED contrastive: {p['fol']} (should be inconsistent but is consistent)")

    probes_text = "\n".join(probe_lines) if probe_lines else "  (no probe failures)"

    return f"""You are given a natural language sentence and a first-order logic (FOL) translation that contains errors. A scoring system rated this translation {siv_score:.2f}/1.00 against the gold standard.

The following diagnostic probes FAILED, indicating specific errors:
{probes_text}

Natural language: {nl}

Candidate FOL: {perturbed_fol}

Score: {siv_score:.2f}/1.00

Use the probe failures to identify and fix the errors. Provide ONLY the corrected FOL formula. Do not explain."""


def build_shuffled_prompt(nl: str, perturbed_fol: str, siv_score: float, probe_detail: list) -> str:
    """Same probes as structured but with results randomly shuffled."""
    failed_probes = [p for p in probe_detail if not p["passed"]]
    passed_probes = [p for p in probe_detail if p["passed"]]

    # Shuffle: take formulas from failed probes, pair with "passed" results and vice versa
    # This preserves the information content (same formulas shown) but breaks the signal
    all_probes = failed_probes[:4] + passed_probes[:4]
    random.shuffle(all_probes)

    # Randomly assign pass/fail labels
    probe_lines = []
    for i, p in enumerate(all_probes):
        # Flip the result for half of them
        fake_passed = (i % 2 == 0)  # Alternating true/false
        if p["type"] == "positive":
            if fake_passed:
                probe_lines.append(f"  PASSED positive: {p['fol']} (correctly entailed)")
            else:
                probe_lines.append(f"  FAILED positive: {p['fol']} (should be entailed but is not)")
        else:
            if fake_passed:
                probe_lines.append(f"  PASSED contrastive: {p['fol']} (correctly inconsistent)")
            else:
                probe_lines.append(f"  FAILED contrastive: {p['fol']} (should be inconsistent but is consistent)")

    probes_text = "\n".join(probe_lines) if probe_lines else "  (no probes)"

    return f"""You are given a natural language sentence and a first-order logic (FOL) translation that contains errors. A scoring system rated this translation {siv_score:.2f}/1.00 against the gold standard.

The following diagnostic probe results were observed:
{probes_text}

Natural language: {nl}

Candidate FOL: {perturbed_fol}

Score: {siv_score:.2f}/1.00

Use the probe results to identify and fix the errors. Provide ONLY the corrected FOL formula. Do not explain."""


def call_gpt4o(prompt: str) -> Optional[str]:
    from openai import OpenAI
    client = OpenAI()
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=500,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"    API error: {e}")
        return None


# ── Main ──────────────────────────────────────────────────────────────────────

def load_folio_examples():
    ds = load_dataset("tasksource/folio", split="train")
    examples = []
    for row in ds:
        nl_parts = [p.strip() for p in row["premises"].split("\n") if p.strip()]
        fol_parts = [p.strip() for p in row["premises-FOL"].split("\n") if p.strip()]
        if len(nl_parts) != len(fol_parts) or len(nl_parts) < 2:
            continue
        examples.append({
            "story_id": row["story_id"],
            "nl_sentences": nl_parts,
            "fol_sentences": fol_parts,
            "conclusion": row["conclusion"],
            "conclusion_fol": row["conclusion-FOL"],
            "gold_label": FOLIO_TO_NLI[row["label"]],
        })
    return examples


def main():
    if not is_vampire_available():
        print("ERROR: Vampire required.")
        sys.exit(1)
    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY required.")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    random.seed(42)

    print("=" * 70)
    print("INVESTIGATION 4: Effect-size Estimate at Locked Design")
    print("=" * 70)
    print()
    print("Design choices from prior investigations:")
    print("  - Primary outcome: SIV score (Investigation 2: label collapses to binary)")
    print("  - Perturbation: compound (Investigation 3: single too easy at 87%)")
    print("  - Bridge: natural FOLIO sampling (Investigation 1: 70% load-bearing)")
    print()

    # Step 1: Build candidate pool with compound perturbations
    print("Building candidate pool with compound perturbations...")
    examples = load_folio_examples()
    random.shuffle(examples)

    candidates = []
    for ex in examples:
        if len(candidates) >= 25:
            break
        if ex["gold_label"] == "neutral":
            continue
        # Need parseable FOLs
        if not all(parse_fol(f) is not None for f in ex["fol_sentences"]):
            continue
        if parse_fol(ex["conclusion_fol"]) is None:
            continue

        # Try to compound-perturb each sentence
        for j in range(len(ex["fol_sentences"])):
            if len(candidates) >= 25:
                break
            fol = ex["fol_sentences"][j]
            perturbed = make_compound_perturbation(fol)
            if not perturbed or perturbed == fol:
                continue
            # Verify non-equivalence
            equiv = check_entailment(fol, perturbed, timeout=5)
            if equiv is True:
                rev = check_entailment(perturbed, fol, timeout=5)
                if rev is True:
                    continue  # Equivalent, skip

            candidates.append({
                "story_id": ex["story_id"],
                "sentence_idx": j,
                "nl": ex["nl_sentences"][j],
                "gold_fol": fol,
                "perturbed_fol": perturbed,
                "all_fols": ex["fol_sentences"],
                "conclusion_fol": ex["conclusion_fol"],
                "gold_label": ex["gold_label"],
            })

    print(f"  Candidates built: {len(candidates)}")
    if len(candidates) < 15:
        print("WARNING: fewer than target 25 candidates. Proceeding with available.")
    print()

    # Step 2: Score each candidate with SIV and get probe detail
    print("Scoring candidates with SIV (for feedback generation)...")
    scored_candidates = []
    for i, cand in enumerate(candidates):
        siv_score, probe_detail = get_siv_suite_and_score(
            cand["gold_fol"], cand["perturbed_fol"], cand["nl"]
        )
        if siv_score is None:
            continue
        cand["siv_score"] = siv_score
        cand["probe_detail"] = probe_detail
        scored_candidates.append(cand)

        if (i + 1) % 10 == 0:
            print(f"  Scored {i+1}/{len(candidates)}...")

    print(f"  Successfully scored: {len(scored_candidates)}")
    # Filter to those with non-perfect score (actually broken)
    broken = [c for c in scored_candidates if c["siv_score"] < 0.95]
    print(f"  Actually broken (SIV < 0.95): {len(broken)}")
    print()

    if len(broken) < 10:
        print("WARNING: Too few broken candidates for reliable effect-size estimate.")
        # Use all scored candidates anyway
        broken = scored_candidates

    # Step 3: Run 3 conditions
    print("Running 3 conditions on GPT-4o...")
    print()

    condition_results = {"score_only": [], "structured": [], "shuffled": []}

    for i, cand in enumerate(broken[:25]):
        nl = cand["nl"]
        perturbed = cand["perturbed_fol"]
        gold = cand["gold_fol"]
        siv_sc = cand["siv_score"]
        probes = cand["probe_detail"]

        # Condition 1: Score-only
        prompt1 = build_score_only_prompt(nl, perturbed, siv_sc)
        corr1 = call_gpt4o(prompt1)

        # Condition 2: Structured
        prompt2 = build_structured_prompt(nl, perturbed, siv_sc, probes)
        corr2 = call_gpt4o(prompt2)

        # Condition 3: Shuffled
        prompt3 = build_shuffled_prompt(nl, perturbed, siv_sc, probes)
        corr3 = call_gpt4o(prompt3)

        # Score each correction
        for cond_name, correction in [("score_only", corr1), ("structured", corr2), ("shuffled", corr3)]:
            if correction is None:
                condition_results[cond_name].append({
                    "candidate_idx": i,
                    "correction": None,
                    "siv_score": None,
                    "equiv_to_gold": None,
                })
                continue

            # Score correction with SIV
            corr_score, _ = get_siv_suite_and_score(gold, correction, nl)

            # Check equivalence
            equiv = check_entailment(gold, correction, timeout=5)
            rev_equiv = check_entailment(correction, gold, timeout=5) if equiv is True else False
            is_equiv = (equiv is True and rev_equiv is True)

            condition_results[cond_name].append({
                "candidate_idx": i,
                "correction": correction[:150],
                "siv_score": corr_score,
                "equiv_to_gold": is_equiv,
            })

        if (i + 1) % 5 == 0:
            print(f"  Processed {i+1}/{min(len(broken), 25)} candidates...")

    print()

    # Step 4: Compute effect sizes
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    print()

    for cond_name in ["score_only", "structured", "shuffled"]:
        results = condition_results[cond_name]
        scores = [r["siv_score"] for r in results if r["siv_score"] is not None]
        equiv_count = sum(1 for r in results if r["equiv_to_gold"])
        n = len(results)
        n_scored = len(scores)
        mean_siv = sum(scores) / n_scored if n_scored > 0 else 0
        equiv_rate = equiv_count / n if n > 0 else 0
        print(f"  {cond_name:15s}: mean SIV={mean_siv:.4f} (n={n_scored}), equiv_rate={equiv_rate:.1%} ({equiv_count}/{n})")

    # Compute deltas
    structured_scores = [r["siv_score"] for r in condition_results["structured"] if r["siv_score"] is not None]
    shuffled_scores = [r["siv_score"] for r in condition_results["shuffled"] if r["siv_score"] is not None]
    score_only_scores = [r["siv_score"] for r in condition_results["score_only"] if r["siv_score"] is not None]

    mean_structured = sum(structured_scores) / len(structured_scores) if structured_scores else 0
    mean_shuffled = sum(shuffled_scores) / len(shuffled_scores) if shuffled_scores else 0
    mean_score_only = sum(score_only_scores) / len(score_only_scores) if score_only_scores else 0

    delta_struct_shuf = mean_structured - mean_shuffled
    delta_struct_score = mean_structured - mean_score_only

    print()
    print(f"  Δ (structured - shuffled): {delta_struct_shuf:+.4f}")
    print(f"  Δ (structured - score_only): {delta_struct_score:+.4f}")
    print()

    # Bootstrap CI for structured vs shuffled
    import numpy as np
    n_boot = 1000
    # Paired bootstrap
    paired = [(s, h) for s, h in zip(
        [r["siv_score"] for r in condition_results["structured"]],
        [r["siv_score"] for r in condition_results["shuffled"]]
    ) if s is not None and h is not None]

    if len(paired) >= 5:
        boot_deltas = []
        for _ in range(n_boot):
            sample = random.choices(paired, k=len(paired))
            s_mean = sum(s for s, _ in sample) / len(sample)
            h_mean = sum(h for _, h in sample) / len(sample)
            boot_deltas.append(s_mean - h_mean)
        boot_deltas.sort()
        ci_lo = boot_deltas[int(0.025 * n_boot)]
        ci_hi = boot_deltas[int(0.975 * n_boot)]
        print(f"  Bootstrap 95% CI for Δ(structured-shuffled): [{ci_lo:+.4f}, {ci_hi:+.4f}]")
    else:
        ci_lo, ci_hi = None, None
        print("  (Insufficient paired data for bootstrap CI)")
    print()

    # Decision
    if delta_struct_shuf >= 0.15:
        decision = "STRONG_EFFECT"
        decision_text = (
            f"Strong effect: Δ={delta_struct_shuf:+.4f} ≥ 0.15. "
            f"Structured trace provides genuine signal beyond leakage. n=80 sufficient."
        )
    elif delta_struct_shuf >= 0.05:
        decision = "MODERATE_EFFECT"
        decision_text = (
            f"Moderate effect: Δ={delta_struct_shuf:+.4f} in [0.05, 0.15). "
            f"Near power threshold; consider n=100 for main run."
        )
    elif delta_struct_shuf >= -0.05:
        decision = "LEAKAGE_SUPPORTED"
        decision_text = (
            f"No effect: Δ={delta_struct_shuf:+.4f} < 0.05. "
            f"Probe-formula gain was likely answer-leakage. Per-aspect-actionability "
            f"claim collapses. STOP and rethink before main run."
        )
    else:
        decision = "UNEXPECTED"
        decision_text = (
            f"Unexpected: structured < shuffled (Δ={delta_struct_shuf:+.4f}). "
            f"Debug implementation."
        )

    print(f"  DECISION: {decision}")
    print(f"  {decision_text}")
    print()

    # Save report
    report = {
        "n_candidates": len(broken[:25]),
        "condition_means": {
            "score_only": round(mean_score_only, 4),
            "structured": round(mean_structured, 4),
            "shuffled": round(mean_shuffled, 4),
        },
        "deltas": {
            "structured_minus_shuffled": round(delta_struct_shuf, 4),
            "structured_minus_score_only": round(delta_struct_score, 4),
        },
        "bootstrap_ci": {"lo": round(ci_lo, 4) if ci_lo else None, "hi": round(ci_hi, 4) if ci_hi else None},
        "decision": decision,
        "decision_text": decision_text,
        "per_condition": {
            cond: [
                {"idx": r["candidate_idx"], "siv": r["siv_score"], "equiv": r["equiv_to_gold"]}
                for r in results
            ]
            for cond, results in condition_results.items()
        },
    }

    out_path = OUT_DIR / "investigation_4_effect_size.json"
    out_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"Report saved to: {out_path}")

    # Markdown
    md_path = OUT_DIR / "investigation_4_effect_size.md"
    md_lines = [
        "# Investigation 4: Effect-size Estimate at Locked Design",
        "",
        "## Design",
        "",
        "- Primary outcome: SIV score (per Investigation 2)",
        "- Perturbation: compound 2-error (per Investigation 3)",
        "- Model: GPT-4o, temperature 0",
        "- 3 conditions: score-only, structured-probe, shuffled-trace",
        "",
        "## Results",
        "",
        f"| Condition | Mean SIV | Equiv Rate |",
        f"|-----------|----------|-----------|",
        f"| Score-only | {mean_score_only:.4f} | {sum(1 for r in condition_results['score_only'] if r['equiv_to_gold'])}/{len(condition_results['score_only'])} |",
        f"| Structured | {mean_structured:.4f} | {sum(1 for r in condition_results['structured'] if r['equiv_to_gold'])}/{len(condition_results['structured'])} |",
        f"| Shuffled | {mean_shuffled:.4f} | {sum(1 for r in condition_results['shuffled'] if r['equiv_to_gold'])}/{len(condition_results['shuffled'])} |",
        "",
        f"**Δ (structured - shuffled): {delta_struct_shuf:+.4f}**",
        f"**Δ (structured - score_only): {delta_struct_score:+.4f}**",
        "",
        f"Bootstrap 95% CI: [{ci_lo:+.4f}, {ci_hi:+.4f}]" if ci_lo else "Bootstrap CI: insufficient data",
        "",
        "## Decision",
        "",
        f"**{decision}**: {decision_text}",
        "",
        "## Decision Rule (pre-registered)",
        "",
        "- Δ ≥ 0.15: strong effect, n=80 sufficient",
        "- 0.05 ≤ Δ < 0.15: moderate, n=100",
        "- Δ < 0.05: leakage, rethink",
    ]
    md_path.write_text("\n".join(md_lines))
    print(f"Markdown saved to: {md_path}")


if __name__ == "__main__":
    main()
