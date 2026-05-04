"""
C2 Design Investigation 1: Load-bearing sentence rate in FOLIO.

Question: What fraction of FOLIO premise sentences are load-bearing for the
entailment label? Decides whether Bridge 2 is feasible without hand-construction.

Method:
- Sample 50 FOLIO premises from well-formed-gold subset (gold FOL passes Vampire
  entailment of the labeled conclusion). Stratify across labels (≥15 each).
- For each premise, for each sentence: remove it and check if label changes.
- A sentence is "load-bearing" if full premises produce correct label but
  premises-minus-sentence produce a different label.

Decision rule:
- ≥60% premises have ≥1 load-bearing sentence AND mean ≥1.0: Bridge 2 feasible.
- 30-60%: feasible but needs filtering.
- <30%: not feasible, fall back to Bridge 1.

Run: python scripts/c2_investigation_1.py
"""
from __future__ import annotations

import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from datasets import load_dataset
from siv.vampire_interface import prove_strict, is_vampire_available
from siv.fol_utils import parse_fol

OUT_DIR = _REPO_ROOT / "reports" / "c2_investigations"

# Label mapping: FOLIO uses "True"/"False"/"Uncertain"
FOLIO_TO_NLI = {"True": "entailment", "False": "contradiction", "Uncertain": "neutral"}


def load_folio_stories(split: str = "train"):
    """Load FOLIO stories with multi-sentence premises."""
    ds = load_dataset("tasksource/folio", split=split)
    stories = []
    for row in ds:
        nl_parts = [p.strip() for p in row["premises"].split("\n") if p.strip()]
        fol_parts = [p.strip() for p in row["premises-FOL"].split("\n") if p.strip()]
        if len(nl_parts) != len(fol_parts):
            continue
        if len(nl_parts) < 2:
            continue  # Need ≥2 sentences to test removal
        stories.append({
            "story_id": row["story_id"],
            "example_id": row.get("example_id"),
            "nl_sentences": nl_parts,
            "fol_sentences": fol_parts,
            "conclusion": row["conclusion"],
            "conclusion_fol": row["conclusion-FOL"],
            "gold_label": FOLIO_TO_NLI[row["label"]],
        })
    return stories


def check_fol_parseable(fol_list: list, conclusion_fol: str) -> bool:
    """Check all FOLs parse without error."""
    for f in fol_list:
        if parse_fol(f) is None:
            return False
    if parse_fol(conclusion_fol) is None:
        return False
    return True


def get_vampire_label(premise_fols: list, conclusion_fol: str, timeout: int = 10) -> str:
    """Run prove_strict and return NLI label."""
    label, _ = prove_strict(premise_fols, conclusion_fol, timeout=timeout)
    return label


def main():
    if not is_vampire_available():
        print("ERROR: Vampire required.")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    random.seed(42)

    print("=" * 70)
    print("INVESTIGATION 1: Load-bearing sentence rate in FOLIO")
    print("=" * 70)
    print()

    # Step 1: Load stories and find well-formed-gold subset
    print("Loading FOLIO train split...")
    stories = load_folio_stories("train")
    print(f"  Stories with ≥2 sentences: {len(stories)}")
    print()

    # Step 2: Filter to well-formed gold (all FOLs parse AND Vampire reproduces label)
    print("Filtering to well-formed-gold subset (all FOLs parse + Vampire confirms label)...")
    well_formed = {"entailment": [], "contradiction": [], "neutral": []}
    parse_failures = 0
    label_mismatches = 0

    t0 = time.time()
    for story in stories:
        if not check_fol_parseable(story["fol_sentences"], story["conclusion_fol"]):
            parse_failures += 1
            continue

        vampire_label = get_vampire_label(
            story["fol_sentences"], story["conclusion_fol"], timeout=10
        )
        if vampire_label == story["gold_label"]:
            well_formed[story["gold_label"]].append(story)
        else:
            label_mismatches += 1

    elapsed = time.time() - t0
    total_wf = sum(len(v) for v in well_formed.values())
    print(f"  Well-formed-gold: {total_wf} (in {elapsed:.1f}s)")
    print(f"  Parse failures: {parse_failures}")
    print(f"  Label mismatches (Vampire ≠ gold): {label_mismatches}")
    for label, lst in well_formed.items():
        print(f"    {label}: {len(lst)}")
    print()

    # Step 3: Stratified sample of 50 (≥15 per label)
    sample = []
    for label in ["entailment", "contradiction", "neutral"]:
        pool = well_formed[label]
        random.shuffle(pool)
        n_take = min(20, len(pool))  # Take up to 20 per label, at least 15
        if n_take < 15 and len(pool) < 15:
            print(f"  WARNING: only {len(pool)} {label} stories available (need 15)")
            n_take = len(pool)
        sample.extend(pool[:n_take])

    # Trim to 50 if we oversampled
    if len(sample) > 50:
        random.shuffle(sample)
        sample = sample[:50]

    print(f"  Sampled {len(sample)} stories for investigation")
    label_dist = defaultdict(int)
    for s in sample:
        label_dist[s["gold_label"]] += 1
    print(f"    Per label: {dict(label_dist)}")
    print()

    # Step 4: For each story, test each sentence for load-bearing-ness
    print("Testing load-bearing sentences...")
    results = []
    total_sentences = 0
    total_load_bearing = 0

    for i, story in enumerate(sample):
        n_sents = len(story["fol_sentences"])
        lb_sentences = []

        for j in range(n_sents):
            # Remove sentence j
            reduced_fols = story["fol_sentences"][:j] + story["fol_sentences"][j+1:]
            reduced_label = get_vampire_label(
                reduced_fols, story["conclusion_fol"], timeout=10
            )
            is_lb = (reduced_label != story["gold_label"])
            lb_sentences.append({
                "sentence_idx": j,
                "nl": story["nl_sentences"][j],
                "fol": story["fol_sentences"][j],
                "is_load_bearing": is_lb,
                "full_label": story["gold_label"],
                "reduced_label": reduced_label,
            })
            if is_lb:
                total_load_bearing += 1
            total_sentences += 1

        # Also test vacuous replacement (tautology)
        vacuous_flips = 0
        for j in range(n_sents):
            tautology = "all x.(x = x)"
            replaced_fols = (
                story["fol_sentences"][:j]
                + [tautology]
                + story["fol_sentences"][j+1:]
            )
            replaced_label = get_vampire_label(
                replaced_fols, story["conclusion_fol"], timeout=10
            )
            if replaced_label != story["gold_label"]:
                vacuous_flips += 1

        n_lb = sum(1 for s in lb_sentences if s["is_load_bearing"])
        results.append({
            "story_id": story["story_id"],
            "gold_label": story["gold_label"],
            "n_sentences": n_sents,
            "n_load_bearing": n_lb,
            "has_load_bearing": n_lb > 0,
            "vacuous_replacement_flips": vacuous_flips,
            "sentences": lb_sentences,
        })

        if (i + 1) % 10 == 0:
            print(f"  Processed {i+1}/{len(sample)} stories...")

    print()

    # Step 5: Compute statistics
    n_stories = len(results)
    n_with_lb = sum(1 for r in results if r["has_load_bearing"])
    frac_with_lb = n_with_lb / n_stories if n_stories > 0 else 0
    mean_lb = total_load_bearing / n_stories if n_stories > 0 else 0
    total_vacuous_flips = sum(r["vacuous_replacement_flips"] for r in results)

    # Per-label breakdown
    per_label = {}
    for label in ["entailment", "contradiction", "neutral"]:
        label_results = [r for r in results if r["gold_label"] == label]
        if label_results:
            n = len(label_results)
            n_lb_label = sum(1 for r in label_results if r["has_load_bearing"])
            mean_lb_label = sum(r["n_load_bearing"] for r in label_results) / n
            per_label[label] = {
                "n": n,
                "n_with_load_bearing": n_lb_label,
                "frac_with_load_bearing": round(n_lb_label / n, 4),
                "mean_load_bearing_per_premise": round(mean_lb_label, 4),
            }

    # Step 6: Decision
    if frac_with_lb >= 0.60 and mean_lb >= 1.0:
        decision = "FEASIBLE_AT_SCALE"
        decision_text = (
            "Bridge 2 is feasible at scale via natural FOLIO sampling. "
            f"≥60% threshold met ({frac_with_lb:.1%}), mean ≥1.0 met ({mean_lb:.2f})."
        )
    elif frac_with_lb >= 0.30:
        decision = "FEASIBLE_WITH_FILTERING"
        decision_text = (
            "Bridge 2 is feasible but candidate pool needs careful filtering. "
            f"30-60% band: {frac_with_lb:.1%}, mean: {mean_lb:.2f}. "
            "Will need to oversample to get n=80."
        )
    else:
        decision = "NOT_FEASIBLE"
        decision_text = (
            "Bridge 2 is NOT feasible without hand-curation. "
            f"<30% threshold: {frac_with_lb:.1%}. "
            "Bridge 1 becomes primary, Bridge 2 as robustness check on curated subset."
        )

    # Print results
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    print()
    print(f"  Stories sampled: {n_stories}")
    print(f"  Total sentences tested: {total_sentences}")
    print(f"  Total load-bearing sentences: {total_load_bearing}")
    print()
    print(f"  Fraction of premises with ≥1 load-bearing sentence: {frac_with_lb:.1%}")
    print(f"  Mean load-bearing sentences per premise: {mean_lb:.2f}")
    print(f"  Vacuous-replacement flips (total): {total_vacuous_flips}")
    print()
    print("  Per-label breakdown:")
    for label, stats in per_label.items():
        print(f"    {label}: {stats['n_with_load_bearing']}/{stats['n']} "
              f"({stats['frac_with_load_bearing']:.1%}) have LB, "
              f"mean={stats['mean_load_bearing_per_premise']:.2f}")
    print()
    print(f"  DECISION: {decision}")
    print(f"  {decision_text}")
    print()

    # Save report
    report = {
        "n_stories_sampled": n_stories,
        "total_sentences_tested": total_sentences,
        "total_load_bearing": total_load_bearing,
        "frac_with_load_bearing": round(frac_with_lb, 4),
        "mean_load_bearing_per_premise": round(mean_lb, 4),
        "total_vacuous_replacement_flips": total_vacuous_flips,
        "per_label": per_label,
        "decision": decision,
        "decision_text": decision_text,
        "per_story_results": results,
    }

    out_path = OUT_DIR / "investigation_1_load_bearing.json"
    out_path.write_text(json.dumps(report, indent=2))
    print(f"Report saved to: {out_path}")

    # Also write markdown summary
    md_path = OUT_DIR / "investigation_1_load_bearing.md"
    md_lines = [
        "# Investigation 1: Load-bearing Sentence Rate in FOLIO",
        "",
        "## Summary",
        "",
        f"- Stories sampled: {n_stories}",
        f"- Total sentences tested: {total_sentences}",
        f"- Total load-bearing sentences: {total_load_bearing}",
        f"- **Fraction with ≥1 load-bearing sentence: {frac_with_lb:.1%}**",
        f"- **Mean load-bearing sentences per premise: {mean_lb:.2f}**",
        f"- Vacuous-replacement flips: {total_vacuous_flips}",
        "",
        "## Per-label Breakdown",
        "",
        "| Label | N | Has LB | % | Mean LB |",
        "|-------|---|--------|---|---------|",
    ]
    for label, stats in per_label.items():
        md_lines.append(
            f"| {label} | {stats['n']} | {stats['n_with_load_bearing']} | "
            f"{stats['frac_with_load_bearing']:.1%} | {stats['mean_load_bearing_per_premise']:.2f} |"
        )
    md_lines.extend([
        "",
        "## Decision",
        "",
        f"**{decision}**: {decision_text}",
        "",
        "## Decision Rule (pre-registered)",
        "",
        "- ≥60% with LB AND mean ≥1.0 → Bridge 2 feasible at scale",
        "- 30-60% → feasible but needs filtering/oversampling",
        "- <30% → not feasible, fall back to Bridge 1",
    ])
    md_path.write_text("\n".join(md_lines))
    print(f"Markdown saved to: {md_path}")


if __name__ == "__main__":
    main()
