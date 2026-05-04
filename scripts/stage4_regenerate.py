"""
Stage 4b: Regenerate candidates for non-equivalent premises and re-run Exp 2.

Protocol:
  1. Identify non-equivalent premises (v1 canonical ≠ v2 gold via Vampire)
  2. Regenerate candidates against v2 gold using same GPT-4o protocol
  3. Re-score ALL candidates (original for equivalent, regenerated for non-equiv)
  4. Report ρ for: (a) full set with regeneration, (b) full without, (c) equiv-only

Run: python scripts/stage4_regenerate.py
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

import numpy as np
from scipy import stats as scipy_stats

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(_REPO_ROOT / ".env")

from experiments.common import (
    align_symbols,
    extract_symbols_from_fol,
    rewrite_fol_strings,
    rewrite_test_suite,
)
from siv.compiler import compile_canonical_fol
from siv.contrastive_generator import derive_witness_axioms
from siv.fol_parser import parse_gold_fol
from siv.fol_utils import parse_fol
from siv.gold_suite_generator import generate_test_suite_from_gold
from siv.scorer import ScoreReport, score
from siv.vampire_interface import check_entailment, is_vampire_available

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

EXP2_DIR = _REPO_ROOT / "reports" / "experiments" / "exp2"
OUT_DIR = _REPO_ROOT / "reports" / "stage4"

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

_LABEL_TO_TYPE = {
    "CANDIDATE_PARTIAL": "partial",
    "CANDIDATE_OVERWEAK": "overweak",
    "CANDIDATE_OVERSTRONG": "overstrong",
    "CANDIDATE_GIBBERISH": "gibberish",
}

REGEN_CACHE_DIR = OUT_DIR / ".regen_cache"


def _call_llm(prompt: str, premise_id: str, attempt: int = 0) -> str:
    """Call GPT-4o. Caches responses."""
    REGEN_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = REGEN_CACHE_DIR / f"{premise_id}_attempt{attempt}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text()).get("response", "")

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
    cache_path.write_text(json.dumps({
        "premise_id": premise_id, "attempt": attempt, "response": text
    }))
    return text


def _parse_llm_response(response: str) -> dict:
    result = {}
    for line in response.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        match = re.match(r"^(CANDIDATE_\w+)\s*:\s*(.+)$", line)
        if match:
            label = match.group(1).upper()
            fol = match.group(2).strip()
            result[label] = fol
    return result


def _classify_by_entailment(forward, reverse):
    if forward is None or reverse is None:
        return "verification_failed"
    if forward and reverse:
        return "equivalent"
    if forward and not reverse:
        return "overweak"
    if not forward and reverse:
        return "overstrong"
    return "incompatible"


def identify_non_equivalent(premises: dict, corr_premise_ids: list) -> tuple:
    """Run Vampire equivalence check between v1 canonical and v2 gold."""
    equivalent = []
    non_equivalent = []

    for pid in corr_premise_ids:
        p = premises[pid]
        v1_canonical = p["siv_canonical_fol"]
        ext = parse_gold_fol(p["gold_fol"], nl=p["nl"])
        v2_canonical = compile_canonical_fol(ext)

        fwd = check_entailment(v1_canonical, v2_canonical, timeout=5)
        bwd = check_entailment(v2_canonical, v1_canonical, timeout=5)

        if fwd is True and bwd is True:
            equivalent.append(pid)
        else:
            non_equivalent.append(pid)

    return equivalent, non_equivalent


def regenerate_candidates(premises: dict, non_equiv_pids: list) -> dict:
    """Generate new candidates for non-equivalent premises against v2 gold."""
    regen_candidates = {}  # pid -> list of kept candidates

    for pid in non_equiv_pids:
        p = premises[pid]
        ext = parse_gold_fol(p["gold_fol"], nl=p["nl"])
        v2_canonical = compile_canonical_fol(ext)

        pred_sigs = ", ".join(
            f"{pr.name}/{pr.arity}({', '.join(pr.arg_types)})"
            for pr in ext.predicates
        )
        constants = ", ".join(c.id for c in ext.constants) or "(none)"

        kept = []
        for attempt in range(2):
            prompt = CANDIDATE_GEN_PROMPT.format(
                nl=p["nl"],
                gold_fol=v2_canonical,
                predicate_signatures=pred_sigs,
                constants=constants,
            )

            response = _call_llm(prompt, f"v2_{pid}", attempt)
            parsed = _parse_llm_response(response)

            if len(parsed) < 4 and attempt == 0:
                logger.warning("%s attempt %d: only %d candidates, retrying",
                               pid, attempt, len(parsed))
                continue

            for label, fol in parsed.items():
                ctype = _LABEL_TO_TYPE.get(label)
                if ctype is None:
                    continue

                expr = parse_fol(fol)
                if expr is None:
                    logger.warning("%s %s: parse failure: %s", pid, ctype, fol[:60])
                    continue

                forward = check_entailment(v2_canonical, fol, timeout=10)
                reverse = check_entailment(fol, v2_canonical, timeout=10)
                vampire_cat = _classify_by_entailment(forward, reverse)

                keep = False
                if vampire_cat == "equivalent":
                    pass
                elif vampire_cat == "verification_failed":
                    pass
                elif ctype == "partial":
                    keep = vampire_cat in ("overweak", "incompatible")
                elif ctype == "overweak":
                    keep = vampire_cat == "overweak"
                elif ctype == "overstrong":
                    keep = vampire_cat == "overstrong"
                elif ctype == "gibberish":
                    keep = vampire_cat == "incompatible"

                if keep:
                    kept.append({
                        "premise_id": pid,
                        "candidate_type": ctype,
                        "candidate_fol": fol,
                        "vampire_category": vampire_cat,
                    })

            if len(parsed) >= 4:
                break

        regen_candidates[pid] = kept
        logger.info("  %s: kept %d/%d types", pid, len(kept),
                    len(set(c["candidate_type"] for c in kept)))

    return regen_candidates


def score_candidate_v2(v2_suite, v2_canonical, candidate_fol, timeout=10):
    """Score candidate against v2 suite with soft alignment."""
    try:
        siv_symbols = extract_symbols_from_fol(v2_canonical)
        cand_symbols = extract_symbols_from_fol(candidate_fol)
        alignment = align_symbols(siv_symbols, cand_symbols, threshold=0.6)
        rewritten_suite = rewrite_test_suite(v2_suite, alignment)
        raw_witnesses = derive_witness_axioms(v2_suite.extraction)
        rewritten_witnesses = rewrite_fol_strings(raw_witnesses, alignment)
        return score(rewritten_suite, candidate_fol, timeout_s=timeout,
                     witness_axioms_override=rewritten_witnesses)
    except Exception as e:
        logger.warning("v2 scoring failed: %s", e)
        return None


def compute_rho(scored_rows: list) -> dict:
    """Compute mean Spearman ρ using Exp 2 methodology."""
    gt_ranks = {"gold": 1, "overstrong": 2, "partial": 2, "overweak": 3, "gibberish": 4}

    by_premise = defaultdict(dict)
    for row in scored_rows:
        recall = row.get("v2_recall")
        if recall is not None:
            by_premise[row["premise_id"]][row["candidate_type"]] = recall

    rho_per_premise = []
    premise_ids_used = []

    for pid, type_scores in by_premise.items():
        non_gold_types = [t for t in ["overstrong", "partial", "overweak", "gibberish"]
                          if t in type_scores]
        if len(non_gold_types) < 3:
            continue

        premise_ids_used.append(pid)
        gt_ranks_vec = [gt_ranks[t] for t in non_gold_types]
        metric_scores = [type_scores[t] for t in non_gold_types]

        if len(set(metric_scores)) > 1:
            rho, _ = scipy_stats.spearmanr(metric_scores, [-r for r in gt_ranks_vec])
            rho_per_premise.append(rho)
        else:
            rho_per_premise.append(0.0)

    rhos = np.array(rho_per_premise)
    if len(rhos) == 0:
        return {"mean_rho": None, "ci_lo": None, "ci_hi": None, "n": 0}

    mean_rho = float(rhos.mean())
    rng = np.random.RandomState(42)
    boot = [rng.choice(rhos, size=len(rhos), replace=True).mean() for _ in range(1000)]
    ci_lo = float(np.percentile(boot, 2.5))
    ci_hi = float(np.percentile(boot, 97.5))

    return {
        "mean_rho": round(mean_rho, 4),
        "ci_lo": round(ci_lo, 4),
        "ci_hi": round(ci_hi, 4),
        "n": len(rhos),
        "per_premise": {pid: float(r) for pid, r in zip(premise_ids_used, rho_per_premise)},
    }


def main():
    if not is_vampire_available():
        print("ERROR: Vampire required.")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load Exp 2 data
    premises = {}
    for line in (EXP2_DIR / "curated_premises.jsonl").read_text().strip().split("\n"):
        row = json.loads(line)
        premises[row["premise_id"]] = row

    scored_v1 = []
    for line in (EXP2_DIR / "scored_candidates.jsonl").read_text().strip().split("\n"):
        if line.strip():
            scored_v1.append(json.loads(line))

    # Identify premises used in rank correlation
    by_premise_v1 = defaultdict(dict)
    for row in scored_v1:
        by_premise_v1[row["premise_id"]][row["candidate_type"]] = row

    corr_premise_ids = []
    for pid, type_map in by_premise_v1.items():
        non_gold = [t for t in ["overstrong", "partial", "overweak", "gibberish"] if t in type_map]
        if len(non_gold) >= 3:
            corr_premise_ids.append(pid)

    print("=" * 70)
    print("STAGE 4b: Principled Filter + Regeneration")
    print("=" * 70)
    print(f"\nCorrelation premises: {len(corr_premise_ids)}")

    # Step 1: Equivalence filter
    print("\n--- Step 1: Vampire equivalence filter ---")
    equivalent, non_equivalent = identify_non_equivalent(premises, corr_premise_ids)
    print(f"  Equivalent: {len(equivalent)}")
    print(f"  Non-equivalent: {len(non_equivalent)}")
    print(f"  Non-equiv set: {non_equivalent}")

    # Step 2: Regenerate candidates for non-equivalent premises
    print(f"\n--- Step 2: Regenerating candidates for {len(non_equivalent)} premises ---")
    regen = regenerate_candidates(premises, non_equivalent)

    regen_summary = {}
    for pid, cands in regen.items():
        types_got = set(c["candidate_type"] for c in cands)
        regen_summary[pid] = {
            "kept": len(cands),
            "types": sorted(types_got),
            "missing": sorted(set(["partial", "overweak", "overstrong", "gibberish"]) - types_got),
        }
        print(f"  {pid}: {len(cands)} kept, types={sorted(types_got)}")
        if regen_summary[pid]["missing"]:
            print(f"         missing: {regen_summary[pid]['missing']}")

    # Step 3: Generate v2 suites and score everything
    print(f"\n--- Step 3: Scoring all candidates ---")

    # Generate v2 suites for all correlation premises
    v2_suites = {}
    for pid in corr_premise_ids:
        p = premises[pid]
        result = generate_test_suite_from_gold(
            p["gold_fol"], nl=p["nl"], verify_round_trip=False,
            with_contrastives=True, timeout_s=10,
        )
        if result.suite:
            ext = parse_gold_fol(p["gold_fol"], nl=p["nl"])
            canonical = compile_canonical_fol(ext)
            v2_suites[pid] = (result.suite, canonical)

    print(f"  v2 suites: {len(v2_suites)}/{len(corr_premise_ids)}")

    # Score: three sets
    # (a) Full set with regeneration: use regen for non-equiv, original for equiv
    # (b) Full set without regeneration: use original candidates for all (= Stage 4 initial)
    # (c) Equivalent-only subset: only equiv premises with original candidates

    scored_a = []  # With regeneration
    scored_b = []  # Without regeneration (original candidates)
    scored_c = []  # Equivalent-only

    t0 = time.time()
    for pid in corr_premise_ids:
        if pid not in v2_suites:
            continue
        suite, canonical = v2_suites[pid]
        p = premises[pid]

        if pid in equivalent:
            # Use original candidates for equivalent premises
            for ctype, row in by_premise_v1[pid].items():
                candidate_fol = row["candidate_fol"]
                if ctype == "gold":
                    candidate_fol = canonical

                report = score_candidate_v2(suite, canonical, candidate_fol)
                recall = report.recall if report else None

                entry = {"premise_id": pid, "candidate_type": ctype, "v2_recall": recall}
                scored_a.append(entry)
                scored_b.append(entry)
                scored_c.append(entry)
        else:
            # Non-equivalent premise
            # (a) Use regenerated candidates
            regen_cands = {c["candidate_type"]: c for c in regen.get(pid, [])}
            # Always include gold
            report_gold = score_candidate_v2(suite, canonical, canonical)
            gold_recall = report_gold.recall if report_gold else None
            scored_a.append({"premise_id": pid, "candidate_type": "gold", "v2_recall": gold_recall})

            for ctype in ["overstrong", "partial", "overweak", "gibberish"]:
                if ctype in regen_cands:
                    report = score_candidate_v2(suite, canonical, regen_cands[ctype]["candidate_fol"])
                    recall = report.recall if report else None
                    scored_a.append({"premise_id": pid, "candidate_type": ctype, "v2_recall": recall})

            # (b) Use original candidates (same as Stage 4 initial run)
            for ctype, row in by_premise_v1[pid].items():
                candidate_fol = row["candidate_fol"]
                if ctype == "gold":
                    candidate_fol = canonical
                report = score_candidate_v2(suite, canonical, candidate_fol)
                recall = report.recall if report else None
                scored_b.append({"premise_id": pid, "candidate_type": ctype, "v2_recall": recall})

    elapsed = time.time() - t0
    print(f"  Scoring complete in {elapsed:.1f}s")

    # Step 4: Compute ρ for all three sets
    print(f"\n--- Step 4: Rank correlations ---")
    rho_a = compute_rho(scored_a)
    rho_b = compute_rho(scored_b)
    rho_c = compute_rho(scored_c)

    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"  v1 locked ρ:                                0.8563 [0.8236, 0.8811] n=35")
    print(f"  (a) Full set WITH regeneration:             {rho_a['mean_rho']:.4f} [{rho_a['ci_lo']:.4f}, {rho_a['ci_hi']:.4f}] n={rho_a['n']}")
    print(f"  (b) Full set WITHOUT regeneration:          {rho_b['mean_rho']:.4f} [{rho_b['ci_lo']:.4f}, {rho_b['ci_hi']:.4f}] n={rho_b['n']}")
    print(f"  (c) Equivalent-only subset:                 {rho_c['mean_rho']:.4f} [{rho_c['ci_lo']:.4f}, {rho_c['ci_hi']:.4f}] n={rho_c['n']}")
    print()

    # Gate decision on (a)
    if rho_a["mean_rho"] >= 0.81:
        gate = "PASS"
        msg = "Headline preserved with regeneration."
    elif rho_a["mean_rho"] >= 0.78:
        gate = "INVESTIGATE"
        msg = "In investigation band."
    else:
        gate = "STOP"
        msg = "Below threshold even with regeneration."

    print(f"  Gate (on a): {gate} — {msg}")
    print()

    # Mean by type for (a)
    print("  Mean v2 recall by type (set a):")
    by_type_a = defaultdict(list)
    for row in scored_a:
        if row["v2_recall"] is not None:
            by_type_a[row["candidate_type"]].append(row["v2_recall"])
    for t in ["gold", "overstrong", "partial", "overweak", "gibberish"]:
        vals = by_type_a.get(t, [])
        if vals:
            print(f"    {t:12s}: {np.mean(vals):.4f} (n={len(vals)})")
    print()

    # Save report
    report = {
        "equivalent_premises": equivalent,
        "non_equivalent_premises": non_equivalent,
        "regen_summary": regen_summary,
        "rho_a_full_with_regen": rho_a,
        "rho_b_full_without_regen": rho_b,
        "rho_c_equiv_only": rho_c,
        "gate": gate,
        "v1_locked_rho": 0.8563,
    }
    out_path = OUT_DIR / "stage4b_regeneration.json"
    out_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"Report saved to: {out_path}")


if __name__ == "__main__":
    main()
