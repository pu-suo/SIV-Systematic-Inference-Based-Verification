"""Convert reports/folio_agreement.json to reports/folio_agreement.csv.

Per-premise reporting view of the Phase 5 SIV evaluation output. Reads
the JSON as-is — does not re-run extraction, normalize predicates, or
compute aggregates. See SIV.md §6.6 and §17.
"""

import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
JSON_PATH = REPO_ROOT / "reports" / "folio_agreement.json"
CSV_PATH = REPO_ROOT / "reports" / "folio_agreement.csv"

COLUMNS = [
    "story_id",
    "status",
    "nl",
    "folio_gold_fol",
    "siv_extraction_view",
    "siv_tests",
    "siv_translation",
    "folio_gold_score",
    "siv_translation_score",
]


def _fmt_num(v):
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def format_score(score: dict) -> str:
    r = _fmt_num(score["recall"])
    p = _fmt_num(score["precision"])
    f = _fmt_num(score["f1"])
    pe = _fmt_num(score["positives_entailed"])
    pt = _fmt_num(score["positives_total"])
    cr = _fmt_num(score["contrastives_rejected"])
    ct = _fmt_num(score["contrastives_total"])
    return (
        f"recall={r} precision={p} f1={f} "
        f"(P:{pe}/{pt} C:{cr}/{ct})"
    )


def format_gold_score(ff: dict) -> str:
    if ff["parse_error"]:
        return f"PARSE_ERROR (normalized: {ff['gold_fol_normalized']})"
    return format_score(ff["score"])


def format_extraction_view(p: dict) -> str:
    return (
        "[reconstructed from report — not raw extraction]\n"
        f"top_formula_case: {p['top_formula_case']}\n"
        f"structural_class: {p['structural_class']}\n"
        f"canonical_fol: {p['canonical_fol']}"
    )


def format_tests(per_test_results: list) -> str:
    return "\n".join(
        f"[{t['kind']}|{t['verdict']}] {t['fol']}"
        for t in per_test_results
    )


def row_for_evaluated(p: dict) -> dict:
    ff = p["folio_faithfulness"]
    return {
        "story_id": p["story_id"],
        "status": "evaluated",
        "nl": p["nl"],
        "folio_gold_fol": ff["gold_fol_raw"],
        "siv_extraction_view": format_extraction_view(p),
        "siv_tests": format_tests(p["self_consistency"]["per_test_results"]),
        "siv_translation": p["canonical_fol"],
        "folio_gold_score": format_gold_score(ff),
        "siv_translation_score": format_score(p["self_consistency"]),
    }


def row_for_failure(f: dict) -> dict:
    return {
        "story_id": f["story_id"],
        "status": f"FAILURE: {f['error_kind']}",
        "nl": f["nl"],
        "folio_gold_fol": "",
        "siv_extraction_view": f["error"],
        "siv_tests": "",
        "siv_translation": "",
        "folio_gold_score": "",
        "siv_translation_score": "",
    }


def main() -> int:
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))

    n_pairs_total = data["n_pairs_total"]
    n_evaluated = data["n_evaluated"]
    n_failures = data["n_failures"]

    rows = [row_for_evaluated(p) for p in data["per_pair"]]
    rows += [row_for_failure(f) for f in data["failures"]]

    with CSV_PATH.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)

    total = len(rows)
    evaluated = sum(1 for r in rows if r["status"] == "evaluated")
    failures = sum(1 for r in rows if r["status"].startswith("FAILURE:"))
    parse_errors = sum(
        1 for r in rows if r["folio_gold_score"].startswith("PARSE_ERROR")
    )

    print(f"wrote {CSV_PATH.relative_to(REPO_ROOT)}")
    print(f"total rows:           {total}")
    print(f"evaluated rows:       {evaluated}")
    print(f"failure rows:         {failures}")
    print(f"gold PARSE_ERROR rows: {parse_errors}")

    ok = (
        evaluated == n_evaluated
        and failures == n_failures
        and total == n_pairs_total
        and evaluated + failures == total
    )
    if not ok:
        print(
            f"MISMATCH: JSON reports n_pairs_total={n_pairs_total}, "
            f"n_evaluated={n_evaluated}, n_failures={n_failures}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
