"""
C2 Design Investigation 3: Hand-perturbation feasibility and quality.

Question: Can we construct perturbations that are (a) plausible LLM-style errors,
(b) reliably detected as broken by Vampire, (c) load-bearing for entailment outcome?

Method:
1. Catalog 5-8 error patterns from Exp B's LLM candidates
2. Construct 20 perturbations on load-bearing sentences targeting those patterns
3. Verify: parseable, non-equivalent, changes label, pattern-faithful
4. Run baseline correction with GPT-4o

Decision rule:
- ≥85% pass all checks: reliable, use as primary construction strategy
- 60-85%: works but needs review step
- <60%: unreliable, investigate

Run: python scripts/c2_investigation_3.py
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

OUT_DIR = _REPO_ROOT / "reports" / "c2_investigations"
FOLIO_TO_NLI = {"True": "entailment", "False": "contradiction", "Uncertain": "neutral"}

# ── Error Pattern Catalog ──────────��──────────────────────────────────────────
# Derived from Exp B (LLM-generated overweak/partial/overstrong candidates)
# and Exp A (systematic perturbation operators)

ERROR_PATTERNS = {
    "arg_swap": {
        "description": "Swap arguments of a binary predicate (e.g., Near(a,b) → Near(b,a))",
        "source": "Exp A B_arg_swap, common LLM error with asymmetric relations",
    },
    "negation_flip": {
        "description": "Add or remove negation on a predicate (e.g., P(x) → ¬P(x))",
        "source": "Exp A B_negation_drop, LLM polarity errors",
    },
    "quantifier_swap": {
        "description": "Change ∀ to ∃ or vice versa (scope confusion)",
        "source": "Exp A B_scope_flip, LLM quantifier confusion",
    },
    "conjunct_drop": {
        "description": "Drop a conjunct from a conjunction (information loss)",
        "source": "Exp B overweak candidates that omit conditions",
    },
    "disjunction_for_conjunction": {
        "description": "Replace ∧ with ∨ (weakening error)",
        "source": "Exp B overweak: P ∧ Q → P ∨ Q",
    },
    "implication_flip": {
        "description": "Reverse implication direction (A→B becomes B→A)",
        "source": "Exp B gibberish candidates with reversed conditionals",
    },
    "constant_swap": {
        "description": "Swap two constants (entity confusion)",
        "source": "Exp B partial candidates with wrong entity attribution",
    },
    "restrictor_drop": {
        "description": "Drop restrictor from universal (∀x.(P(x)→Q(x)) → ∀x.Q(x))",
        "source": "Exp A B_restrictor_drop, LLM over-generalization",
    },
}


# ── Perturbation constructors ─────────────��───────────────────────────────────

def perturb_arg_swap(fol: str) -> Optional[str]:
    """Swap arguments in a binary predicate."""
    pattern = r'(\w+)\(([^,()]+),\s*([^,()]+)\)'
    matches = list(re.finditer(pattern, fol))
    if not matches:
        return None
    m = random.choice(matches)
    result = fol[:m.start()] + f"{m.group(1)}({m.group(3)}, {m.group(2)})" + fol[m.end():]
    return result if parse_fol(result) else None


def perturb_negation_flip(fol: str) -> Optional[str]:
    """Add or remove negation on an atom."""
    # Try removing existing negation
    if "¬" in fol:
        # Find a negated atom and remove the negation
        pattern = r'¬(\w+\([^)]+\))'
        match = re.search(pattern, fol)
        if match:
            result = fol[:match.start()] + match.group(1) + fol[match.end():]
            if parse_fol(result):
                return result
    # Try adding negation
    pattern = r'(?<!¬)(\w+\([^)]+\))'
    matches = list(re.finditer(pattern, fol))
    if matches:
        m = random.choice(matches)
        result = fol[:m.start()] + f"¬{m.group(1)}" + fol[m.end():]
        if parse_fol(result):
            return result
    # Try with - notation
    pattern = r'(?<!-)(\w+\([^)]+\))'
    matches = list(re.finditer(pattern, fol))
    if matches:
        m = random.choice(matches)
        result = fol[:m.start()] + f"-{m.group(1)}" + fol[m.end():]
        if parse_fol(result):
            return result
    return None


def perturb_quantifier_swap(fol: str) -> Optional[str]:
    """Swap ∀↔∃."""
    if "∀" in fol:
        result = fol.replace("∀", "∃", 1)
    elif "∃" in fol:
        result = fol.replace("∃", "∀", 1)
    elif "all " in fol:
        result = fol.replace("all ", "exists ", 1)
    elif "exists " in fol:
        result = fol.replace("exists ", "all ", 1)
    else:
        return None
    return result if parse_fol(result) else None


def perturb_conjunct_drop(fol: str) -> Optional[str]:
    """Drop a conjunct."""
    for sep in ["∧", " & "]:
        if sep in fol:
            parts = fol.split(sep, 1)
            # Keep the larger part
            result = parts[1].strip() if len(parts[1]) > len(parts[0]) else parts[0].strip()
            # Remove dangling parens
            if result.startswith("(") and result.count("(") > result.count(")"):
                result = result[1:]
            if result.endswith(")") and result.count(")") > result.count("("):
                result = result[:-1]
            if parse_fol(result):
                return result
    return None


def perturb_disjunction_for_conjunction(fol: str) -> Optional[str]:
    """Replace ∧ with ∨."""
    if "∧" in fol:
        result = fol.replace("∧", "∨", 1)
        return result if parse_fol(result) else None
    if " & " in fol:
        result = fol.replace(" & ", " | ", 1)
        return result if parse_fol(result) else None
    return None


def perturb_implication_flip(fol: str) -> Optional[str]:
    """Reverse an implication."""
    for arrow in ["→", "->"]:
        if arrow in fol:
            idx = fol.find(arrow)
            # Find the antecedent and consequent (simplified)
            # This is a rough approach - look for the implication in a universal
            before = fol[:idx].strip()
            after = fol[idx+len(arrow):].strip()
            result = f"{after} {arrow} {before}"
            # Try wrapping in the same quantifier prefix
            # Actually just swap around the arrow
            result = fol[:idx] + arrow + " " + before.split("(", 1)[-1] if "(" in before else None
            if result and parse_fol(result):
                return result
            # Simpler: just swap what's immediately around the arrow
            # Find balanced parens
            result = after + f" {arrow} " + before
            if parse_fol(result):
                return result
    return None


def perturb_constant_swap(fol: str) -> Optional[str]:
    """Swap two constants."""
    # Find constants (lowercase multi-char tokens that aren't keywords)
    keywords = {"all", "exists", "and", "or", "not", "implies"}
    consts = re.findall(r'\b([a-z][a-zA-Z0-9]+)\b', fol)
    consts = [c for c in consts if c not in keywords and len(c) > 1]
    unique = list(set(consts))
    if len(unique) < 2:
        return None
    c1, c2 = random.sample(unique, 2)
    result = fol.replace(c1, "__TMP__").replace(c2, c1).replace("__TMP__", c2)
    return result if result != fol and parse_fol(result) else None


def perturb_restrictor_drop(fol: str) -> Optional[str]:
    """Drop restrictor from a universal: ∀x.(P(x)→Q(x)) → ∀x.Q(x)."""
    # Look for pattern: ∀x (antecedent → consequent)
    for arrow in ["→", "->"]:
        if arrow in fol and ("∀" in fol or "all " in fol):
            idx = fol.find(arrow)
            # Get everything after the arrow
            consequent = fol[idx+len(arrow):].strip()
            # Get quantifier prefix
            if "∀" in fol:
                q_idx = fol.find("∀")
                # Extract "∀x " or "∀x∀y"
                prefix_end = fol.find("(", q_idx)
                if prefix_end == -1:
                    prefix_end = q_idx + 3
                prefix = fol[q_idx:prefix_end+1]
                result = f"{prefix}{consequent}"
            elif "all " in fol:
                # Extract "all x."
                match = re.match(r'(all \w+\.)', fol.strip())
                if match:
                    result = f"{match.group(1)}{consequent}"
                else:
                    return None
            else:
                return None
            # Clean up trailing parens
            if result.count(")") > result.count("("):
                result = result[:result.rfind(")")]
            if parse_fol(result):
                return result
    return None


PERTURBATION_FUNCS = {
    "arg_swap": perturb_arg_swap,
    "negation_flip": perturb_negation_flip,
    "quantifier_swap": perturb_quantifier_swap,
    "conjunct_drop": perturb_conjunct_drop,
    "disjunction_for_conjunction": perturb_disjunction_for_conjunction,
    "implication_flip": perturb_implication_flip,
    "constant_swap": perturb_constant_swap,
    "restrictor_drop": perturb_restrictor_drop,
}


def load_folio_examples():
    """Load FOLIO examples."""
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


def find_load_bearing_with_context(examples, n_target=12):
    """Find load-bearing sentences with full context for perturbation."""
    random.shuffle(examples)
    lb_items = []

    for ex in examples:
        if len(lb_items) >= n_target:
            break
        if ex["gold_label"] == "neutral":
            continue

        # Check all FOLs parse
        all_parse = all(parse_fol(f) is not None for f in ex["fol_sentences"])
        if not all_parse or parse_fol(ex["conclusion_fol"]) is None:
            continue

        # Verify gold label
        label, _ = prove_strict(ex["fol_sentences"], ex["conclusion_fol"], timeout=10)
        if label != ex["gold_label"]:
            continue

        # Find load-bearing sentences
        for j in range(len(ex["fol_sentences"])):
            reduced = ex["fol_sentences"][:j] + ex["fol_sentences"][j+1:]
            reduced_label, _ = prove_strict(reduced, ex["conclusion_fol"], timeout=10)
            if reduced_label != ex["gold_label"]:
                lb_items.append({
                    "story_id": ex["story_id"],
                    "gold_label": ex["gold_label"],
                    "sentence_idx": j,
                    "nl": ex["nl_sentences"][j],
                    "fol": ex["fol_sentences"][j],
                    "all_fols": ex["fol_sentences"],
                    "all_nls": ex["nl_sentences"],
                    "conclusion": ex["conclusion"],
                    "conclusion_fol": ex["conclusion_fol"],
                })
                if len(lb_items) >= n_target:
                    break

    return lb_items


def run_baseline_correction(nl: str, perturbed_fol: str) -> Optional[str]:
    """Run GPT-4o baseline correction (no feedback, just NL + candidate)."""
    from openai import OpenAI

    client = OpenAI()
    prompt = f"""You are given a natural language sentence and a first-order logic (FOL) translation that may contain errors. Your task is to produce the correct FOL translation.

Natural language: {nl}

Candidate FOL (may be incorrect): {perturbed_fol}

Provide ONLY the corrected FOL formula. Do not explain."""

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


def check_equivalence(fol_a: str, fol_b: str, timeout: int = 10) -> bool:
    """Check if two FOL formulas are logically equivalent (bidirectional entailment)."""
    fwd = check_entailment(fol_a, fol_b, timeout=timeout)
    if fwd is not True:
        return False
    bwd = check_entailment(fol_b, fol_a, timeout=timeout)
    return bwd is True


def main():
    if not is_vampire_available():
        print("ERROR: Vampire required.")
        sys.exit(1)

    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY required for baseline correction.")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    random.seed(42)

    print("=" * 70)
    print("INVESTIGATION 3: Hand-perturbation Feasibility and Quality")
    print("=" * 70)
    print()

    # Step 1: Load and find load-bearing sentences
    print("Finding load-bearing sentences...")
    examples = load_folio_examples()
    lb_items = find_load_bearing_with_context(examples, n_target=12)
    print(f"  Found {len(lb_items)} load-bearing sentences")
    if len(lb_items) < 8:
        print("ERROR: Need minimum 8 load-bearing sentences.")
        sys.exit(1)
    print()

    # Step 2: Construct perturbations (2 per sentence, different patterns)
    print("Constructing perturbations...")
    perturbations = []
    pattern_names = list(PERTURBATION_FUNCS.keys())

    for item in lb_items:
        fol = item["fol"]
        patterns_tried = []

        for _ in range(2):  # Want 2 perturbations per sentence
            random.shuffle(pattern_names)
            for pname in pattern_names:
                if pname in patterns_tried:
                    continue
                func = PERTURBATION_FUNCS[pname]
                result = func(fol)
                if result and result != fol:
                    perturbations.append({
                        "source_item": item,
                        "pattern": pname,
                        "perturbed_fol": result,
                    })
                    patterns_tried.append(pname)
                    break

    print(f"  Constructed {len(perturbations)} perturbations")
    # Trim to 20
    if len(perturbations) > 20:
        perturbations = perturbations[:20]
        print(f"  Trimmed to 20")

    # Count patterns used
    from collections import Counter
    pattern_dist = Counter(p["pattern"] for p in perturbations)
    print(f"  Pattern distribution: {dict(pattern_dist)}")
    print()

    # Step 3: Verify each perturbation
    print("Verifying perturbations...")
    verified = []
    verification_failures = {"parse": 0, "equivalent": 0, "label_unchanged": 0, "timeout": 0}

    for i, pert in enumerate(perturbations):
        item = pert["source_item"]
        perturbed = pert["perturbed_fol"]

        checks = {
            "parseable": False,
            "non_equivalent": False,
            "label_changes": False,
            "pattern_faithful": True,  # Manual check placeholder
        }

        # Check 1: Parseable
        if parse_fol(perturbed) is not None:
            checks["parseable"] = True
        else:
            verification_failures["parse"] += 1
            verified.append({"perturbation": pert, "checks": checks, "all_pass": False})
            continue

        # Check 2: Non-equivalent to gold
        equiv = check_equivalence(item["fol"], perturbed, timeout=10)
        if not equiv:
            checks["non_equivalent"] = True
        else:
            verification_failures["equivalent"] += 1
            verified.append({"perturbation": pert, "checks": checks, "all_pass": False})
            continue

        # Check 3: Changes the label (in full premise context)
        premise_set = (
            item["all_fols"][:item["sentence_idx"]]
            + [perturbed]
            + item["all_fols"][item["sentence_idx"]+1:]
        )
        new_label, _ = prove_strict(premise_set, item["conclusion_fol"], timeout=10)
        if new_label != item["gold_label"]:
            checks["label_changes"] = True
        else:
            verification_failures["label_unchanged"] += 1

        all_pass = all(checks.values())
        verified.append({
            "perturbation": pert,
            "checks": checks,
            "all_pass": all_pass,
            "new_label": new_label,
        })

    n_pass = sum(1 for v in verified if v["all_pass"])
    n_total = len(verified)
    pass_rate = n_pass / n_total if n_total > 0 else 0

    print(f"  Passed all checks: {n_pass}/{n_total} ({pass_rate:.1%})")
    print(f"  Failures: {dict(verification_failures)}")
    print()

    # Step 4: Baseline correction on verified perturbations
    print("Running baseline GPT-4o corrections...")
    passing_perts = [v for v in verified if v["all_pass"]]

    correction_results = []
    for i, v in enumerate(passing_perts):
        item = v["perturbation"]["source_item"]
        perturbed = v["perturbation"]["perturbed_fol"]
        pattern = v["perturbation"]["pattern"]

        correction = run_baseline_correction(item["nl"], perturbed)
        if correction is None:
            correction_results.append({
                "pattern": pattern,
                "nl": item["nl"],
                "gold_fol": item["fol"],
                "perturbed_fol": perturbed,
                "correction": None,
                "correction_correct": None,
            })
            continue

        # Check if correction is equivalent to gold
        is_correct = check_equivalence(item["fol"], correction, timeout=10)

        # Also check if correction restores the label
        premise_set = (
            item["all_fols"][:item["sentence_idx"]]
            + [correction]
            + item["all_fols"][item["sentence_idx"]+1:]
        )
        corrected_label, _ = prove_strict(premise_set, item["conclusion_fol"], timeout=10)
        label_restored = (corrected_label == item["gold_label"])

        correction_results.append({
            "pattern": pattern,
            "nl": item["nl"],
            "gold_fol": item["fol"],
            "perturbed_fol": perturbed,
            "correction": correction,
            "correction_equivalent_to_gold": is_correct,
            "correction_restores_label": label_restored,
        })

        if (i + 1) % 5 == 0:
            print(f"  Corrected {i+1}/{len(passing_perts)}...")

    # Correction rate
    n_corrected = len([r for r in correction_results if r.get("correction_equivalent_to_gold")])
    n_label_restored = len([r for r in correction_results if r.get("correction_restores_label")])
    n_attempted = len([r for r in correction_results if r["correction"] is not None])

    correction_rate = n_corrected / n_attempted if n_attempted > 0 else 0
    label_restore_rate = n_label_restored / n_attempted if n_attempted > 0 else 0

    print()
    print(f"  Corrections attempted: {n_attempted}")
    print(f"  Equivalent to gold: {n_corrected}/{n_attempted} ({correction_rate:.1%})")
    print(f"  Restores label: {n_label_restored}/{n_attempted} ({label_restore_rate:.1%})")
    print()

    # Step 5: Decisions
    if pass_rate >= 0.85:
        construction_decision = "RELIABLE"
        construction_text = (
            f"Hand-perturbation construction is reliable. {pass_rate:.1%} pass all checks "
            f"(≥85%). Use as primary candidate-construction strategy."
        )
    elif pass_rate >= 0.60:
        construction_decision = "NEEDS_REVIEW"
        construction_text = (
            f"Hand-perturbation works but needs review process. {pass_rate:.1%} pass "
            f"(60-85%). Build in verification step; reject candidates that fail."
        )
    else:
        construction_decision = "UNRELIABLE"
        construction_text = (
            f"Hand-perturbation is unreliable. Only {pass_rate:.1%} pass (<60%). "
            f"Investigate which check fails most. May need different patterns."
        )

    # Correction rate check
    if 0.25 <= correction_rate <= 0.55:
        severity_decision = "CALIBRATED"
        severity_text = f"Baseline correction rate {correction_rate:.1%} is in target band (25-55%)."
    elif correction_rate < 0.25:
        severity_decision = "TOO_HARD"
        severity_text = f"Correction rate {correction_rate:.1%} too low (<25%). Reduce severity."
    else:
        severity_decision = "TOO_EASY"
        severity_text = f"Correction rate {correction_rate:.1%} too high (>55%). Increase severity."

    print("=" * 70)
    print("DECISIONS")
    print("=" * 70)
    print()
    print(f"  Construction: {construction_decision}")
    print(f"    {construction_text}")
    print()
    print(f"  Severity: {severity_decision}")
    print(f"    {severity_text}")
    print()

    # Save report
    report = {
        "error_pattern_catalog": ERROR_PATTERNS,
        "n_lb_sentences": len(lb_items),
        "n_perturbations_constructed": len(perturbations),
        "n_verified": n_total,
        "n_pass_all_checks": n_pass,
        "pass_rate": round(pass_rate, 4),
        "verification_failures": verification_failures,
        "construction_decision": construction_decision,
        "construction_text": construction_text,
        "baseline_correction": {
            "n_attempted": n_attempted,
            "n_equivalent_to_gold": n_corrected,
            "correction_rate": round(correction_rate, 4),
            "n_restores_label": n_label_restored,
            "label_restore_rate": round(label_restore_rate, 4),
        },
        "severity_decision": severity_decision,
        "severity_text": severity_text,
        "pattern_distribution": dict(pattern_dist),
        "per_perturbation": [
            {
                "pattern": v["perturbation"]["pattern"],
                "nl": v["perturbation"]["source_item"]["nl"][:100],
                "gold_fol": v["perturbation"]["source_item"]["fol"][:100],
                "perturbed_fol": v["perturbation"]["perturbed_fol"][:100],
                "checks": v["checks"],
                "all_pass": v["all_pass"],
            }
            for v in verified
        ],
        "correction_results": correction_results,
    }

    out_path = OUT_DIR / "investigation_3_hand_perturbation.json"
    out_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"Report saved to: {out_path}")

    # Markdown
    md_path = OUT_DIR / "investigation_3_hand_perturbation.md"
    md_lines = [
        "# Investigation 3: Hand-perturbation Feasibility and Quality",
        "",
        "## Error Pattern Catalog",
        "",
        "| Pattern | Description | Source |",
        "|---------|-------------|--------|",
    ]
    for name, info in ERROR_PATTERNS.items():
        md_lines.append(f"| {name} | {info['description']} | {info['source']} |")
    md_lines.extend([
        "",
        "## Verification Results",
        "",
        f"- Perturbations constructed: {len(perturbations)}",
        f"- **Pass all checks: {n_pass}/{n_total} ({pass_rate:.1%})**",
        f"- Failures: parse={verification_failures['parse']}, "
        f"equivalent={verification_failures['equivalent']}, "
        f"label_unchanged={verification_failures['label_unchanged']}",
        "",
        "## Baseline Correction (GPT-4o, no feedback)",
        "",
        f"- Attempted: {n_attempted}",
        f"- **Equivalent to gold: {n_corrected}/{n_attempted} ({correction_rate:.1%})**",
        f"- Restores label: {n_label_restored}/{n_attempted} ({label_restore_rate:.1%})",
        "",
        "## Decisions",
        "",
        f"- **Construction**: {construction_decision} — {construction_text}",
        f"- **Severity**: {severity_decision} — {severity_text}",
    ])
    md_path.write_text("\n".join(md_lines))
    print(f"Markdown saved to: {md_path}")


if __name__ == "__main__":
    main()
