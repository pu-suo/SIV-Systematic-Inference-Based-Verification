"""Analyze decomposition quality from a FOLIO agreement report.

Derives predicate arity distribution from the `canonical_fol` strings in each
per_pair record of reports/folio_agreement.json. No re-extraction.

The canonical FOL is produced by siv/compiler.py with a consistent
`Name(arg1, arg2, ...)` surface form. Predicate names begin with an uppercase
ASCII letter; arguments are simple lowercase identifiers (variables or
constant ids). Predicates never appear as arguments, so a regex pass is
sufficient to enumerate atoms.

Usage:
    python scripts/analyze_decomposition.py \
        [--current reports/folio_agreement.json] \
        [--baseline reports/folio_agreement_v2.0.0_baseline.json]
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

_REPO_ROOT = Path(__file__).parent.parent

# Match `UpperCamel(arg, arg)` where args are bare identifiers. FOL keywords
# like `all`, `exists`, `not`, `and`, `or`, `implies`, `iff` are lowercase, so
# requiring an initial uppercase letter excludes them cleanly.
_ATOM_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*)\s*\(([^()]*)\)")


def atoms_of(fol: str) -> List[Tuple[str, int]]:
    """Return a list of (predicate_name, arity) for every atom in ``fol``."""
    out: List[Tuple[str, int]] = []
    for match in _ATOM_RE.finditer(fol):
        name = match.group(1)
        body = match.group(2).strip()
        if not body:
            arity = 0
        else:
            arity = len([a for a in body.split(",") if a.strip()])
        out.append((name, arity))
    return out


def camel_word_count(name: str) -> int:
    """Count CamelCase word boundaries in a predicate name.

    "WorkFromHome" → 3. "Tall" → 1. "HasTypeC" → 3 (Has, Type, C).
    """
    # Split before each uppercase letter that follows a lowercase letter or
    # another uppercase letter followed by lowercase (TypeC → Type + C).
    parts = re.findall(r"[A-Z][a-z]*|[A-Z]+(?=[A-Z]|$)", name)
    return max(1, len(parts))


def per_premise_atoms(rows: List[Dict[str, Any]]) -> List[List[Tuple[str, int]]]:
    return [atoms_of(r["canonical_fol"]) for r in rows]


def arity_counts(per_premise: List[List[Tuple[str, int]]]) -> Dict[int, int]:
    c: Counter = Counter()
    for atoms in per_premise:
        for _, ar in atoms:
            c[ar] += 1
    return dict(c)


def all_unary_premise_count(per_premise: List[List[Tuple[str, int]]]) -> int:
    n = 0
    for atoms in per_premise:
        if not atoms:
            continue
        if all(ar == 1 for _, ar in atoms):
            n += 1
    return n


def premises_with_long_unary(
    per_premise: List[List[Tuple[str, int]]], min_words: int = 3,
) -> int:
    """Number of premises whose FOL contains at least one unary predicate
    with ``min_words`` or more CamelCase tokens."""
    n = 0
    for atoms in per_premise:
        if any(ar == 1 and camel_word_count(name) >= min_words for name, ar in atoms):
            n += 1
    return n


def long_unary_predicate_names(
    per_premise: List[List[Tuple[str, int]]], min_words: int = 3,
) -> Counter:
    c: Counter = Counter()
    for atoms in per_premise:
        for name, ar in atoms:
            if ar == 1 and camel_word_count(name) >= min_words:
                c[name] += 1
    return c


def summarize(rows: List[Dict[str, Any]], label: str) -> Dict[str, Any]:
    per_pred = per_premise_atoms(rows)
    arities = arity_counts(per_pred)
    unary = arities.get(1, 0)
    binary = arities.get(2, 0)
    total = unary + binary
    long_names = long_unary_predicate_names(per_pred)
    return {
        "label": label,
        "n_premises": len(rows),
        "unary_atoms": unary,
        "binary_atoms": binary,
        "binary_share": (binary / total) if total else 0.0,
        "all_unary_premises": all_unary_premise_count(per_pred),
        "all_unary_share": all_unary_premise_count(per_pred) / len(rows) if rows else 0.0,
        "long_unary_premises": premises_with_long_unary(per_pred),
        "long_unary_occurrences": sum(long_names.values()),
        "long_unary_distinct": len(long_names),
        "top_long_unary": long_names.most_common(15),
    }


def mean_recall(data: Dict[str, Any], key: str) -> Optional[float]:
    return data.get(key, {}).get("overall", {}).get("mean_recall")


def index_by_nl(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {r["nl"]: r for r in rows}


def before_after_examples(
    baseline_rows: List[Dict[str, Any]],
    current_rows: List[Dict[str, Any]],
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Find premises present in both reports where baseline was all-unary (or
    contained a long flattened predicate) and current has at least one binary
    atom and no long flattened predicate."""
    baseline_ix = index_by_nl(baseline_rows)
    out: List[Dict[str, Any]] = []
    for cur in current_rows:
        base = baseline_ix.get(cur["nl"])
        if base is None:
            continue
        base_atoms = atoms_of(base["canonical_fol"])
        cur_atoms = atoms_of(cur["canonical_fol"])
        if not base_atoms or not cur_atoms:
            continue
        base_all_unary = all(ar == 1 for _, ar in base_atoms)
        base_has_long = any(
            ar == 1 and camel_word_count(n) >= 3 for n, ar in base_atoms
        )
        cur_has_binary = any(ar == 2 for _, ar in cur_atoms)
        cur_has_long = any(
            ar == 1 and camel_word_count(n) >= 3 for n, ar in cur_atoms
        )
        improved = (base_all_unary or base_has_long) and cur_has_binary and not cur_has_long
        if improved:
            out.append({
                "nl": cur["nl"],
                "before_fol": base["canonical_fol"],
                "after_fol": cur["canonical_fol"],
            })
            if len(out) >= limit:
                break
    return out


def format_report(
    current: Dict[str, Any],
    baseline: Optional[Dict[str, Any]],
) -> str:
    cur_rows = current["per_pair"]
    cur_sum = summarize(cur_rows, "current")
    base_sum = summarize(baseline["per_pair"], "baseline") if baseline else None

    lines: List[str] = []
    lines.append("# Decomposition analysis")
    lines.append("")
    lines.append(f"Current report: n_evaluated={current.get('n_evaluated')} "
                 f"failures={current.get('n_failures')}")
    if baseline:
        lines.append(
            f"Baseline report: n_evaluated={baseline.get('n_evaluated')} "
            f"failures={baseline.get('n_failures')}"
        )
    lines.append("")

    lines.append("## 1. Arity distribution")
    lines.append("")
    lines.append("| Metric | Baseline | Current | Target |")
    lines.append("|---|---|---|---|")
    def _row(name, b, c, target):
        bv = b if b is not None else "—"
        return f"| {name} | {bv} | {c} | {target} |"
    if base_sum:
        lines.append(_row("Unary atoms", base_sum["unary_atoms"], cur_sum["unary_atoms"], "< 400"))
        lines.append(_row("Binary atoms", base_sum["binary_atoms"], cur_sum["binary_atoms"], "≥ 224 (2×baseline)"))
        lines.append(_row(
            "Binary share", f"{base_sum['binary_share']:.1%}",
            f"{cur_sum['binary_share']:.1%}", "≥ 35%",
        ))
    else:
        lines.append(_row("Unary atoms", None, cur_sum["unary_atoms"], "< 400"))
        lines.append(_row("Binary atoms", None, cur_sum["binary_atoms"], "≥ 224"))
        lines.append(_row("Binary share", None, f"{cur_sum['binary_share']:.1%}", "≥ 35%"))
    lines.append("")

    lines.append("## 2. All-unary premises")
    lines.append("")
    if base_sum:
        lines.append(
            f"- Baseline: {base_sum['all_unary_premises']}/{base_sum['n_premises']} "
            f"({base_sum['all_unary_share']:.1%})"
        )
    lines.append(
        f"- Current:  {cur_sum['all_unary_premises']}/{cur_sum['n_premises']} "
        f"({cur_sum['all_unary_share']:.1%})"
    )
    lines.append(f"- Target:  < 20%")
    lines.append("")

    lines.append("## 3. Long unary predicates (3+ CamelCase words, arity 1)")
    lines.append("")
    if base_sum:
        lines.append(
            f"- Baseline: {base_sum['long_unary_premises']} premises "
            f"({base_sum['long_unary_occurrences']} occurrences, "
            f"{base_sum['long_unary_distinct']} distinct names)"
        )
    lines.append(
        f"- Current:  {cur_sum['long_unary_premises']} premises "
        f"({cur_sum['long_unary_occurrences']} occurrences, "
        f"{cur_sum['long_unary_distinct']} distinct names)"
    )
    lines.append(f"- Target:  < 20 premises")
    if cur_sum["top_long_unary"]:
        lines.append("")
        lines.append("Top current long-unary names:")
        for name, n in cur_sum["top_long_unary"]:
            lines.append(f"  - {name} (×{n})")
    lines.append("")

    lines.append("## 4. Self-consistency recall")
    lines.append("")
    base_rec = mean_recall(baseline, "self_consistency") if baseline else None
    cur_rec = mean_recall(current, "self_consistency")
    lines.append(f"- Baseline: {base_rec}")
    lines.append(f"- Current:  {cur_rec}")
    lines.append(f"- Target:   ≥ 0.95")
    lines.append("")

    lines.append("## 5. Before/after examples (up to 10)")
    lines.append("")
    examples = before_after_examples(
        baseline["per_pair"] if baseline else [],
        cur_rows,
        limit=10,
    ) if baseline else []
    if not examples:
        lines.append("_No baseline provided, or no matching improved premises found._")
    else:
        for i, ex in enumerate(examples, 1):
            lines.append(f"**{i}.** {ex['nl']}")
            lines.append(f"- before: `{ex['before_fol']}`")
            lines.append(f"- after:  `{ex['after_fol']}`")
            lines.append("")

    lines.append("## Recommendation")
    lines.append("")
    targets_met = (
        cur_sum["binary_share"] >= 0.35
        and cur_sum["all_unary_share"] < 0.20
        and cur_sum["long_unary_premises"] < 20
        and (cur_rec is None or cur_rec >= 0.95)
    )
    partial = cur_sum["binary_atoms"] > (
        2 * base_sum["binary_atoms"] if base_sum else 224
    )
    if targets_met:
        lines.append("**Prompt fix sufficient.** All Phase B targets met.")
    elif partial:
        lines.append(
            "**Partial.** Binary predicates more than doubled but absolute "
            "targets not yet met. Phase C tripwire should close the remaining "
            "gap."
        )
    else:
        lines.append(
            "**Model upgrade may be needed.** Prompt fix did not produce the "
            "expected decomposition lift. Verify cache was cleared; consider "
            "stronger negative examples or a more capable model."
        )

    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", default="reports/folio_agreement.json")
    ap.add_argument("--baseline", default="reports/folio_agreement_v2.0.0_baseline.json")
    ap.add_argument("--out", default=None, help="Write report to this path; else stdout.")
    args = ap.parse_args()

    current = json.loads((_REPO_ROOT / args.current).read_text())
    base_path = _REPO_ROOT / args.baseline
    baseline = json.loads(base_path.read_text()) if base_path.exists() else None

    report = format_report(current, baseline)
    if args.out:
        out = _REPO_ROOT / args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report)
        print(f"wrote {out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
