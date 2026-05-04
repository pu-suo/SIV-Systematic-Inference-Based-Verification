"""
Experiment D — Score-sensitivity for hand-corrected FOLIO gold annotations.

Reframed Exp D (PART 2 of EMNLP results pass): score-sensitivity result, NOT a
detection-rate claim.

For each of 30 hand-corrected premises in docs/corrections_template.md:
  1. Parse the c_correct_fol; record parse_status.
  2. Generate a v2 SIV test suite from the corrected FOL via
     siv.gold_suite_generator.generate_test_suite_from_gold; record n_positives,
     n_contrastives, suite_status.
  3. Sanity-score the corrected gold against its own corrected suite — should
     yield SIV recall = 1.0 by construction (C7).
  4. Score the broken gold against the corrected suite WHERE possible. Most
     broken golds will not parse — that's why they're broken.
  5. Compute delta = score_corrected − score_broken when both are defined.

Outputs (deterministic; no seeds needed; no LLM calls):
  reports/exp_d_score_sensitivity/results.jsonl
  reports/exp_d_score_sensitivity/summary.json
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

from siv.fol_utils import parse_fol
from siv.gold_suite_generator import generate_test_suite_from_gold
from siv.scorer import score
from siv.vampire_interface import is_vampire_available

ROOT = Path(__file__).parent.parent
CORRECTIONS_PATH = ROOT / "docs" / "corrections_template.md"
BROKEN_POOL_PATH = ROOT / "reports" / "experiments" / "exp3" / "broken_gold_pool.jsonl"
OUT_DIR = ROOT / "reports" / "exp_d_score_sensitivity"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_PATH = OUT_DIR / "results.jsonl"
SUMMARY_PATH = OUT_DIR / "summary.json"

# Vampire timeout per check; deterministic per-call resource cap.
TIMEOUT_S = 5


def parse_corrections_md(path: Path) -> List[Dict]:
    """Parse the corrections template into per-premise dicts.

    Field shape (per entry):
      premise_id, nl, gold_fol_broken, broken_reason, broken_evidence,
      c_correct_fol, rationale, introduced_predicates
    """
    text = path.read_text()
    sections = re.split(r"^## ", text, flags=re.MULTILINE)
    entries: List[Dict] = []
    for section in sections:
        section = section.strip()
        if not section.startswith("P"):
            continue
        m_id = re.match(r"^(P\d{4})", section)
        if not m_id:
            continue
        premise_id = m_id.group(1)

        def grab(label: str, body: str) -> Optional[str]:
            m = re.search(rf"^{re.escape(label)}:\s*(.+?)(?=\n\S|\n###|\n---|\Z)", body, re.MULTILINE | re.DOTALL)
            if m:
                return m.group(1).strip().strip('"')
            return None

        nl = grab("NL", section)
        gold_broken = grab("Gold FOL (broken)", section)
        broken_reason = grab("Broken reason", section)
        broken_evidence = grab("Broken evidence", section)
        c_correct = grab("c_correct_fol", section)
        rationale = grab("rationale", section)
        introduced = grab("introduced_predicates", section)
        entries.append({
            "premise_id": premise_id,
            "nl": nl,
            "gold_fol_broken": gold_broken,
            "broken_reason": broken_reason,
            "broken_evidence": broken_evidence,
            "c_correct_fol": c_correct,
            "rationale": rationale,
            "introduced_predicates": introduced,
        })
    return entries


def load_broken_pool(path: Path) -> Dict[str, Dict]:
    """Load broken pool indexed by premise_id."""
    out: Dict[str, Dict] = {}
    with open(path) as f:
        for line in f:
            entry = json.loads(line)
            out[entry["premise_id"]] = entry
    return out


def score_to_dict(report) -> Dict:
    return {
        "recall": report.recall,
        "precision": report.precision,
        "f1": report.f1,
        "positives_entailed": report.positives_entailed,
        "positives_total": report.positives_total,
        "contrastives_rejected": report.contrastives_rejected,
        "contrastives_total": report.contrastives_total,
    }


def primary_score(report) -> float:
    """Headline SIV score: f1 if defined (suite has contrastives), else recall."""
    if report.f1 is not None:
        return report.f1
    return report.recall


def main():
    if not is_vampire_available():
        raise SystemExit("Vampire is required for Exp D score-sensitivity. Install per scripts/setup.sh.")

    entries = parse_corrections_md(CORRECTIONS_PATH)
    if len(entries) != 30:
        raise SystemExit(f"Expected 30 entries in corrections_template.md, got {len(entries)}.")
    broken_pool = load_broken_pool(BROKEN_POOL_PATH)

    rows: List[Dict] = []
    anomaly_count = 0
    delta_lt_zero_premises: List[str] = []
    sanity_violations: List[str] = []

    for entry in entries:
        pid = entry["premise_id"]
        anomaly_notes: List[str] = []

        # Parse the corrected FOL.
        corrected_fol = entry["c_correct_fol"]
        try:
            parsed = parse_fol(corrected_fol)
            corrected_parse_status = "ok" if parsed is not None else "fail"
            if parsed is None:
                anomaly_notes.append("corrected FOL did not parse")
        except Exception as e:
            corrected_parse_status = f"fail:{type(e).__name__}:{e}"
            anomaly_notes.append(f"corrected FOL parse exception: {corrected_parse_status}")

        broken_fol = broken_pool.get(pid, {}).get("gold_fol", entry.get("gold_fol_broken"))

        suite_status = "skipped"
        n_positives = 0
        n_contrastives = 0
        score_corrected: Optional[float] = None
        score_corrected_full: Optional[Dict] = None
        score_broken: Optional[float] = None
        score_broken_full: Optional[Dict] = None
        delta: Optional[float] = None
        broken_parse_status = "not_attempted"

        if corrected_parse_status == "ok":
            # Generate v2 suite from corrected FOL. Skip round-trip verification
            # because hand corrections introduce predicate vocabulary that may
            # differ from the gold's lexical surface; round-trip tests would
            # fail for irrelevant lexical reasons.
            result = generate_test_suite_from_gold(
                corrected_fol,
                nl=entry.get("nl") or "",
                verify_round_trip=False,
                with_contrastives=True,
                timeout_s=TIMEOUT_S,
            )
            if result.suite is None or result.error:
                suite_status = f"fail:{result.error}"
                anomaly_notes.append(f"suite generation failed: {result.error}")
            else:
                suite = result.suite
                n_positives = result.num_positives
                n_contrastives = result.num_contrastives
                if n_positives == 0:
                    suite_status = "fail:no_positives"
                    anomaly_notes.append("suite generated with 0 positives")
                else:
                    suite_status = "ok"

                    # Step 3: sanity — corrected vs its own suite.
                    sanity_report = score(suite, corrected_fol, timeout_s=TIMEOUT_S)
                    score_corrected_full = score_to_dict(sanity_report)
                    score_corrected = primary_score(sanity_report)
                    if sanity_report.recall != 1.0:
                        sanity_violations.append(
                            f"{pid}: recall={sanity_report.recall} (expected 1.0)"
                        )
                        anomaly_notes.append(
                            f"sanity violation: corrected recall={sanity_report.recall}"
                        )

                    # Step 4: score broken against corrected suite (if broken parses).
                    if broken_fol:
                        try:
                            broken_parsed = parse_fol(broken_fol)
                            if broken_parsed is None:
                                broken_parse_status = "fail"
                            else:
                                broken_parse_status = "ok"
                                broken_report = score(suite, broken_fol, timeout_s=TIMEOUT_S)
                                score_broken_full = score_to_dict(broken_report)
                                score_broken = primary_score(broken_report)
                        except Exception as e:
                            broken_parse_status = f"fail:{type(e).__name__}"
                    else:
                        broken_parse_status = "no_broken_fol_in_pool"

                    # Step 5: delta.
                    if score_corrected is not None and score_broken is not None:
                        delta = score_corrected - score_broken
                        if delta < 0:
                            delta_lt_zero_premises.append(pid)
                            anomaly_notes.append(f"delta < 0 (broken scored higher): {delta}")
                            anomaly_count += 1

        rows.append({
            "premise_id": pid,
            "nl": entry.get("nl"),
            "broken_fol": broken_fol,
            "corrected_fol": corrected_fol,
            "broken_reason": entry.get("broken_reason"),
            "broken_parse_status": broken_parse_status,
            "corrected_parse_status": corrected_parse_status,
            "suite_status": suite_status,
            "n_positives": n_positives,
            "n_contrastives": n_contrastives,
            "score_corrected_vs_corrected_suite": score_corrected,
            "score_corrected_full": score_corrected_full,
            "score_broken_vs_corrected_suite": score_broken,
            "score_broken_full": score_broken_full,
            "delta": delta,
            "anomaly_notes": anomaly_notes,
        })

    # Write results.jsonl.
    with open(RESULTS_PATH, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    # Stop conditions.
    n_corrected_parse_fail = sum(1 for r in rows if r["corrected_parse_status"] != "ok")
    if n_corrected_parse_fail > 5:
        raise SystemExit(
            f"STOP: {n_corrected_parse_fail} of 30 corrected formulas failed to parse (>5)."
        )
    if sanity_violations:
        raise SystemExit(
            f"STOP: sanity violations on {len(sanity_violations)} premises: {sanity_violations}"
        )
    if anomaly_count > 3:
        raise SystemExit(
            f"STOP: {anomaly_count} delta<0 anomalies (>3): {delta_lt_zero_premises}"
        )

    # Aggregate summary.
    n_total = len(rows)
    n_corrected_parse_ok = sum(1 for r in rows if r["corrected_parse_status"] == "ok")
    n_suite_gen_ok = sum(1 for r in rows if r["suite_status"] == "ok")
    n_suite_gen_fail = sum(1 for r in rows if r["suite_status"].startswith("fail"))
    n_broken_parse_ok = sum(1 for r in rows if r["broken_parse_status"] == "ok")
    n_broken_parse_fail = sum(
        1 for r in rows
        if r["broken_parse_status"] not in ("ok", "not_attempted", "no_broken_fol_in_pool")
    )

    deltas = [r["delta"] for r in rows if r["delta"] is not None]
    n_with_defined_delta = len(deltas)
    n_with_null_delta = n_total - n_with_defined_delta

    sc_corr = [r["score_corrected_vs_corrected_suite"] for r in rows
               if r["score_corrected_vs_corrected_suite"] is not None]
    sc_brk = [r["score_broken_vs_corrected_suite"] for r in rows
              if r["score_broken_vs_corrected_suite"] is not None]
    mean_score_corrected = sum(sc_corr) / len(sc_corr) if sc_corr else None
    mean_score_broken = sum(sc_brk) / len(sc_brk) if sc_brk else None

    if deltas:
        sorted_deltas = sorted(deltas)
        mean_delta = sum(deltas) / len(deltas)
        median_delta = sorted_deltas[len(sorted_deltas) // 2]
        min_delta = sorted_deltas[0]
        max_delta = sorted_deltas[-1]
    else:
        mean_delta = median_delta = min_delta = max_delta = None

    bins = {"0.0-0.2": 0, "0.2-0.4": 0, "0.4-0.6": 0, "0.6-0.8": 0, "0.8-1.0": 0}
    for d in deltas:
        if d < 0.2:
            bins["0.0-0.2"] += 1
        elif d < 0.4:
            bins["0.2-0.4"] += 1
        elif d < 0.6:
            bins["0.4-0.6"] += 1
        elif d < 0.8:
            bins["0.6-0.8"] += 1
        else:
            bins["0.8-1.0"] += 1

    n_delta_gt_zero = sum(1 for d in deltas if d > 0)
    n_delta_eq_zero = sum(1 for d in deltas if d == 0)
    n_delta_lt_zero = sum(1 for d in deltas if d < 0)

    summary = {
        "score_metric": "f1 if suite has contrastives else recall",
        "vampire_timeout_s": TIMEOUT_S,
        "n_total": n_total,
        "n_corrected_parse_ok": n_corrected_parse_ok,
        "n_corrected_parse_fail": n_total - n_corrected_parse_ok,
        "n_suite_gen_ok": n_suite_gen_ok,
        "n_suite_gen_fail": n_suite_gen_fail,
        "n_broken_parse_ok": n_broken_parse_ok,
        "n_broken_parse_fail": n_broken_parse_fail,
        "n_with_defined_delta": n_with_defined_delta,
        "n_with_null_delta": n_with_null_delta,
        "mean_score_corrected": mean_score_corrected,
        "mean_score_broken": mean_score_broken,
        "mean_delta": mean_delta,
        "median_delta": median_delta,
        "min_delta": min_delta,
        "max_delta": max_delta,
        "delta_distribution_bins": bins,
        "n_delta_gt_zero": n_delta_gt_zero,
        "n_delta_eq_zero": n_delta_eq_zero,
        "n_delta_lt_zero": n_delta_lt_zero,
        "anomaly_premises_delta_lt_zero": delta_lt_zero_premises,
        "broken_reason_breakdown_in_30": dict(Counter(r["broken_reason"] for r in rows)),
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2))

    print(f"Wrote {RESULTS_PATH}")
    print(f"Wrote {SUMMARY_PATH}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
