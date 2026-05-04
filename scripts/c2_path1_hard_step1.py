"""
Path 1-Hard, Step 1: Calibrate task difficulty.

Tests three difficulty levels to find candidates where GPT-4o no-feedback
correction rate is in 10-30% band.

Difficulty A: Complex FOLIO premises (multi-quantifier from the hardest subset)
              with compound-3 perturbation
Difficulty B: Hand-constructed deep-nesting FOL (3+ quantifiers) with compound-2
Difficulty C: Hand-constructed FOL with adversarial perturbations designed to
              preserve surface plausibility

Run: python scripts/c2_path1_hard_step1.py
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
from siv.vampire_interface import check_entailment, prove_strict, is_vampire_available
from siv.fol_utils import parse_fol
from siv.gold_suite_generator import generate_test_suite_from_gold
from siv.fol_parser import parse_gold_fol, ParseError
from siv.compiler import compile_canonical_fol

OUT_DIR = _REPO_ROOT / "reports" / "c2_investigations" / "path1_hard"

FOLIO_TO_NLI = {"True": "entailment", "False": "contradiction", "Uncertain": "neutral"}


# ── Hand-constructed hard FOL bank ───────────────────────────────────────────
# These are deliberately complex: 3+ nested quantifiers, compound restrictors,
# mixed scopes, multi-predicate interactions.

HARD_FOL_BANK = [
    {
        "nl": "Every professor who advises a student that studies logic teaches a course that covers logic.",
        "fol": "all x.(Professor(x) & exists y.(Student(y) & Advises(x,y) & Studies(y,logic)) -> exists z.(Course(z) & Teaches(x,z) & Covers(z,logic)))",
    },
    {
        "nl": "Every company that employs a manager who supervises at least two different teams is classified as large.",
        "fol": "all x.(Company(x) & exists y.(Manager(y) & Employs(x,y) & exists z1.exists z2.(Team(z1) & Team(z2) & Supervises(y,z1) & Supervises(y,z2) & -(z1=z2))) -> Large(x))",
    },
    {
        "nl": "Every student who is either a senior or has completed all prerequisites can register for the seminar.",
        "fol": "all x.((Student(x) & (Senior(x) | all y.(Prerequisite(y) -> Completed(x,y)))) -> CanRegister(x,seminar))",
    },
    {
        "nl": "There exists a library such that every book in it has been read by some scholar.",
        "fol": "exists x.(Library(x) & all y.((Book(y) & In(y,x)) -> exists z.(Scholar(z) & HasRead(z,y))))",
    },
    {
        "nl": "Every hospital that treats a patient who has been diagnosed with a rare disease employs a specialist who researches that disease.",
        "fol": "all x.(Hospital(x) & exists y.(Patient(y) & Treats(x,y) & exists d.(RareDisease(d) & DiagnosedWith(y,d))) -> exists s.(Specialist(s) & Employs(x,s) & exists d2.(RareDisease(d2) & Researches(s,d2))))",
    },
    {
        "nl": "No country that imports all its energy from a single supplier and has no domestic reserves is energy independent.",
        "fol": "all x.(Country(x) & exists s.(Supplier(s) & all e.(Energy(e) & Consumes(x,e) -> Imports(x,e,s))) & -(exists r.(Reserve(r) & Domestic(r) & Has(x,r))) -> -EnergyIndependent(x))",
    },
    {
        "nl": "Every researcher who publishes in a top journal and mentors a student who also publishes there is considered distinguished.",
        "fol": "all x.(Researcher(x) & exists j.(TopJournal(j) & PublishesIn(x,j)) & exists y.(Student(y) & Mentors(x,y) & exists j2.(TopJournal(j2) & PublishesIn(y,j2))) -> Distinguished(x))",
    },
    {
        "nl": "Every city that has a university offering a program accredited by an international body attracts foreign students.",
        "fol": "all x.(City(x) & exists u.(University(u) & In(u,x) & exists p.(Program(p) & Offers(u,p) & exists b.(InternationalBody(b) & Accredits(b,p)))) -> AttractsForeignStudents(x))",
    },
    {
        "nl": "If every member of a committee approves a proposal, and the committee has at least three members, then the proposal is adopted.",
        "fol": "all c.all p.((Committee(c) & Proposal(p) & all m.(Member(m,c) -> Approves(m,p)) & exists m1.exists m2.exists m3.(Member(m1,c) & Member(m2,c) & Member(m3,c) & -(m1=m2) & -(m2=m3) & -(m1=m3))) -> Adopted(p))",
    },
    {
        "nl": "Every teacher who works at a school that has won an award and who teaches a subject that is part of the core curriculum receives a bonus.",
        "fol": "all x.(Teacher(x) & exists s.(School(s) & WorksAt(x,s) & exists a.(Award(a) & Won(s,a))) & exists subj.(Subject(subj) & Teaches(x,subj) & CoreCurriculum(subj)) -> ReceivesBonus(x))",
    },
    {
        "nl": "There exists a network such that every server connected to it that handles sensitive data is protected by at least two firewalls.",
        "fol": "exists n.(Network(n) & all s.((Server(s) & Connected(s,n) & HandlesSensitiveData(s)) -> exists f1.exists f2.(Firewall(f1) & Firewall(f2) & Protects(f1,s) & Protects(f2,s) & -(f1=f2))))",
    },
    {
        "nl": "Every airline that operates a route between two cities where both cities have international airports offers connecting flights.",
        "fol": "all a.(Airline(a) & exists c1.exists c2.(City(c1) & City(c2) & -(c1=c2) & OperatesRoute(a,c1,c2) & HasInternationalAirport(c1) & HasInternationalAirport(c2)) -> OffersConnectingFlights(a))",
    },
]


# ── Perturbation functions ────────────────────────────────────────────────────

def perturb_arg_swap(fol: str) -> Optional[str]:
    pattern = r'(\w+)\(([^,()]+),\s*([^,()]+)\)'
    matches = list(re.finditer(pattern, fol))
    if not matches:
        return None
    m = random.choice(matches)
    result = fol[:m.start()] + f"{m.group(1)}({m.group(3)}, {m.group(2)})" + fol[m.end():]
    return result if parse_fol(result) else None


def perturb_negation_flip(fol: str) -> Optional[str]:
    # Add negation to a predicate
    pattern = r'(?<!-)(\w+\([^)]+\))'
    matches = list(re.finditer(pattern, fol))
    if matches:
        m = random.choice(matches)
        result = fol[:m.start()] + f"-{m.group(1)}" + fol[m.end():]
        if parse_fol(result):
            return result
    # Remove existing negation
    match = re.search(r'-(\w+\([^)]+\))', fol)
    if match:
        result = fol[:match.start()] + match.group(1) + fol[match.end():]
        if parse_fol(result):
            return result
    return None


def perturb_quantifier_swap(fol: str) -> Optional[str]:
    if "all " in fol:
        # Swap a specific 'all' to 'exists'
        occurrences = [m.start() for m in re.finditer(r'\ball\b', fol)]
        if occurrences:
            idx = random.choice(occurrences)
            result = fol[:idx] + "exists" + fol[idx+3:]
            return result if parse_fol(result) else None
    if "exists " in fol:
        occurrences = [m.start() for m in re.finditer(r'\bexists\b', fol)]
        if occurrences:
            idx = random.choice(occurrences)
            result = fol[:idx] + "all" + fol[idx+6:]
            return result if parse_fol(result) else None
    return None


def perturb_connective_flip(fol: str) -> Optional[str]:
    if " & " in fol:
        # Find a specific & and replace with |
        occurrences = [m.start() for m in re.finditer(r' & ', fol)]
        if occurrences:
            idx = random.choice(occurrences)
            result = fol[:idx] + " | " + fol[idx+3:]
            return result if parse_fol(result) else None
    if " | " in fol:
        occurrences = [m.start() for m in re.finditer(r' \| ', fol)]
        if occurrences:
            idx = random.choice(occurrences)
            result = fol[:idx] + " & " + fol[idx+3:]
            return result if parse_fol(result) else None
    if " -> " in fol:
        occurrences = [m.start() for m in re.finditer(r' -> ', fol)]
        if occurrences:
            idx = random.choice(occurrences)
            result = fol[:idx] + " & " + fol[idx+4:]
            return result if parse_fol(result) else None
    return None


def perturb_drop_conjunct(fol: str) -> Optional[str]:
    """Drop a conjunct — removes info from the formula."""
    # Find balanced & operators at different depths
    if " & " not in fol:
        return None
    # Simple approach: remove a Pred(args) conjunct
    pattern = r'\w+\([^()]+\) & '
    match = re.search(pattern, fol)
    if match:
        result = fol[:match.start()] + fol[match.end():]
        if parse_fol(result):
            return result
    # Try removing from right side
    pattern2 = r' & \w+\([^()]+\)'
    match2 = re.search(pattern2, fol)
    if match2:
        result = fol[:match2.start()] + fol[match2.end():]
        if parse_fol(result):
            return result
    return None


PERTURBATION_FUNCS = [
    ("argument-order", perturb_arg_swap),
    ("polarity", perturb_negation_flip),
    ("quantifier-scope", perturb_quantifier_swap),
    ("connective-polarity", perturb_connective_flip),
    ("restrictor-content", perturb_drop_conjunct),
]


def make_compound_perturbation(fol: str, n_layers: int = 2) -> Optional[tuple[str, list[str]]]:
    """Apply n_layers different perturbations."""
    random.shuffle(PERTURBATION_FUNCS)
    result = fol
    applied_cats = []
    used_cats = set()

    for _ in range(n_layers):
        for cat, func in PERTURBATION_FUNCS:
            if cat in used_cats:
                continue
            new_result = func(result)
            if new_result and new_result != result:
                result = new_result
                applied_cats.append(cat)
                used_cats.add(cat)
                break

    if not applied_cats or result == fol:
        return None
    return result, applied_cats


def make_adversarial_perturbation(fol: str) -> Optional[tuple[str, list[str]]]:
    """Make perturbations that are adversarially hard to detect from NL alone.
    Key: make the FOL look superficially plausible but have subtle errors
    that require careful logical reasoning to detect.
    """
    cats = []

    # Strategy: combine a subtle quantifier swap with an arg swap deep inside
    # These preserve surface structure but change deep semantics
    result = fol

    # 1. Swap a deeply nested quantifier (subtle)
    all_positions = [m.start() for m in re.finditer(r'\ball\b', fol)]
    exists_positions = [m.start() for m in re.finditer(r'\bexists\b', fol)]

    # Prefer swapping inner (non-first) quantifiers — more subtle
    if len(all_positions) > 1:
        idx = all_positions[-1]  # Innermost
        result = result[:idx] + "exists" + result[idx+3:]
        cats.append("quantifier-scope")
    elif exists_positions:
        idx = exists_positions[-1]
        result = result[:idx] + "all" + result[idx+6:]
        cats.append("quantifier-scope")

    if not parse_fol(result):
        result = fol
        cats = []

    # 2. Swap args in a deeply nested binary predicate
    pattern = r'(\w+)\(([^,()]+),\s*([^,()]+)\)'
    matches = list(re.finditer(pattern, result))
    if matches:
        # Pick the deepest (last) match
        m = matches[-1]
        new_result = result[:m.start()] + f"{m.group(1)}({m.group(3)}, {m.group(2)})" + result[m.end():]
        if parse_fol(new_result):
            result = new_result
            cats.append("argument-order")

    # 3. If we still only have 1 perturbation, add a subtle connective change
    if len(cats) < 2:
        # Change -> to & in an inner implication (keeps FOL parseable, changes meaning)
        inner_arrows = [m.start() for m in re.finditer(r' -> ', result)]
        if len(inner_arrows) > 1:
            idx = inner_arrows[-1]  # Inner implication
            new_result = result[:idx] + " & " + result[idx+4:]
            if parse_fol(new_result):
                result = new_result
                cats.append("connective-polarity")

    if not cats or result == fol or not parse_fol(result):
        return None
    return result, cats


def check_equivalence(fol_a: str, fol_b: str, timeout: int = 10) -> bool:
    fwd = check_entailment(fol_a, fol_b, timeout=timeout)
    if fwd is not True:
        return False
    bwd = check_entailment(fol_b, fol_a, timeout=timeout)
    return bwd is True


def call_gpt4o_no_feedback(nl: str, perturbed_fol: str) -> Optional[str]:
    from openai import OpenAI
    client = OpenAI()
    prompt = f"""You are given a natural language sentence and a first-order logic (FOL) translation that contains errors. Your task is to produce the correct FOL translation of the natural language sentence.

Natural language: {nl}

Candidate FOL (contains errors): {perturbed_fol}

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
    print("PATH 1-HARD, STEP 1: Calibrate Task Difficulty")
    print("=" * 70)
    print()

    # ── Difficulty A: Hard FOLIO with compound-3 ──────────────────────────────
    print("DIFFICULTY A: Complex FOLIO with compound-3 perturbation")
    print("-" * 50)

    # Load FOLIO and find the hardest premises (multi-quantifier)
    ds = load_dataset("tasksource/folio", split="train")
    hard_folio = []
    for row in ds:
        if FOLIO_TO_NLI[row["label"]] == "neutral":
            continue
        nl_parts = [p.strip() for p in row["premises"].split("\n") if p.strip()]
        fol_parts = [p.strip() for p in row["premises-FOL"].split("\n") if p.strip()]
        if len(nl_parts) != len(fol_parts):
            continue
        for nl, fol in zip(nl_parts, fol_parts):
            # Select multi-quantifier formulas
            n_quant = fol.count("∀") + fol.count("∃") + fol.count("all ") + fol.count("exists ")
            if n_quant >= 2 and parse_fol(fol) is not None:
                hard_folio.append({"nl": nl, "fol": fol})

    random.shuffle(hard_folio)
    print(f"  Multi-quantifier FOLIO premises: {len(hard_folio)}")

    diff_a_results = []
    for case in hard_folio[:15]:  # Try 15 to get 10
        pert = make_compound_perturbation(case["fol"], n_layers=3)
        if not pert:
            continue
        perturbed, cats = pert
        if check_equivalence(case["fol"], perturbed):
            continue
        # No-feedback correction
        correction = call_gpt4o_no_feedback(case["nl"], perturbed)
        correct = check_equivalence(case["fol"], correction) if correction and parse_fol(correction) else False
        diff_a_results.append({"nl": case["nl"][:60], "correct": correct})
        if len(diff_a_results) >= 10:
            break

    a_rate = sum(1 for r in diff_a_results if r["correct"]) / len(diff_a_results) if diff_a_results else 0
    print(f"  Tested: {len(diff_a_results)}, Correct: {sum(1 for r in diff_a_results if r['correct'])}")
    print(f"  Baseline correction rate: {a_rate:.1%}")
    print()

    # ── Difficulty B: Hand-constructed deep nesting + compound-2 ──────────────
    print("DIFFICULTY B: Hand-constructed deep nesting + compound-2")
    print("-" * 50)

    diff_b_results = []
    for case in HARD_FOL_BANK[:12]:
        # Verify parseable
        if parse_fol(case["fol"]) is None:
            continue
        pert = make_compound_perturbation(case["fol"], n_layers=2)
        if not pert:
            continue
        perturbed, cats = pert
        if check_equivalence(case["fol"], perturbed):
            continue
        correction = call_gpt4o_no_feedback(case["nl"], perturbed)
        correct = check_equivalence(case["fol"], correction) if correction and parse_fol(correction) else False
        diff_b_results.append({"nl": case["nl"][:60], "correct": correct, "cats": cats})
        if len(diff_b_results) >= 10:
            break

    b_rate = sum(1 for r in diff_b_results if r["correct"]) / len(diff_b_results) if diff_b_results else 0
    print(f"  Tested: {len(diff_b_results)}, Correct: {sum(1 for r in diff_b_results if r['correct'])}")
    print(f"  Baseline correction rate: {b_rate:.1%}")
    print()

    # ── Difficulty C: Adversarial perturbations (surface-plausible errors) ────
    print("DIFFICULTY C: Adversarial perturbations (preserve surface plausibility)")
    print("-" * 50)

    diff_c_results = []
    all_sources = HARD_FOL_BANK + [{"nl": c["nl"], "fol": c["fol"]} for c in hard_folio[:20]]
    random.shuffle(all_sources)

    for case in all_sources:
        if len(diff_c_results) >= 10:
            break
        if parse_fol(case["fol"]) is None:
            continue
        pert = make_adversarial_perturbation(case["fol"])
        if not pert:
            continue
        perturbed, cats = pert
        if check_equivalence(case["fol"], perturbed):
            continue
        correction = call_gpt4o_no_feedback(case["nl"], perturbed)
        correct = check_equivalence(case["fol"], correction) if correction and parse_fol(correction) else False
        diff_c_results.append({"nl": case["nl"][:60], "correct": correct, "cats": cats})

    c_rate = sum(1 for r in diff_c_results if r["correct"]) / len(diff_c_results) if diff_c_results else 0
    print(f"  Tested: {len(diff_c_results)}, Correct: {sum(1 for r in diff_c_results if r['correct'])}")
    print(f"  Baseline correction rate: {c_rate:.1%}")
    print()

    # ── Summary and Decision ─────────────────────────────────────────────────
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print()
    print(f"  Difficulty A (hard FOLIO + compound-3):     {a_rate:.1%}")
    print(f"  Difficulty B (hand-constructed + compound-2): {b_rate:.1%}")
    print(f"  Difficulty C (adversarial perturbations):    {c_rate:.1%}")
    print()

    # Decision
    levels_in_band = []
    for name, rate in [("A", a_rate), ("B", b_rate), ("C", c_rate)]:
        if 0.10 <= rate <= 0.30:
            levels_in_band.append((name, rate))

    if levels_in_band:
        chosen = levels_in_band[0]
        decision = "IN_BAND"
        decision_text = (
            f"Difficulty {chosen[0]} lands in 10-30% band ({chosen[1]:.1%}). "
            f"Use as candidate source for main experiment."
        )
    elif all(r > 0.30 for r in [a_rate, b_rate, c_rate]):
        decision = "ALL_TOO_EASY"
        decision_text = "All levels >30%. Need harder perturbations (compound-4+, combine difficulty levels)."
    elif all(r < 0.10 for r in [a_rate, b_rate, c_rate]):
        decision = "ALL_TOO_HARD"
        decision_text = "All levels <10%. LLMs can't translate at all. Stop and surface."
    else:
        # Some in 0-10%, some >30%
        decision = "MIXED"
        decision_text = "Mixed results. Use the closest level to the 10-30% band."
        # Pick the one closest to 20% (midpoint of target)
        all_rates = [("A", a_rate), ("B", b_rate), ("C", c_rate)]
        closest = min(all_rates, key=lambda x: abs(x[1] - 0.20))
        decision_text += f" Closest: Difficulty {closest[0]} at {closest[1]:.1%}."

    print(f"  DECISION: {decision}")
    print(f"  {decision_text}")
    print()

    # Save
    report = {
        "difficulty_a": {"rate": a_rate, "n": len(diff_a_results), "results": diff_a_results},
        "difficulty_b": {"rate": b_rate, "n": len(diff_b_results), "results": diff_b_results},
        "difficulty_c": {"rate": c_rate, "n": len(diff_c_results), "results": diff_c_results},
        "decision": decision,
        "decision_text": decision_text,
        "levels_in_band": [(name, rate) for name, rate in levels_in_band] if levels_in_band else None,
    }
    out_path = OUT_DIR / "step1_difficulty_calibration.json"
    out_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"Saved to: {out_path}")


if __name__ == "__main__":
    main()
