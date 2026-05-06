"""Inspect the v3 test-suite generator on a curated sentence set.

For each sentence in ``reports/inspect_sentences.jsonl`` print:
  - NL + gold FOL
  - The parsed ``TripartiteQuantification`` tree, indented to show
    restrictor/nucleus separation at each scope level
  - The canonical FOL emitted by ``compile_canonical_fol`` (Path A)
  - Each generated positive labeled by the rule that produced it:
      W = whole formula (canonical itself)
      a = AND-conjunct projection (rule a)
      b = existential restrictor projection (rule b)
  - Each contrastive with its ``mutation_kind`` and ``probe_relation``

Usage:
    python scripts/inspect_test_suite.py
    python scripts/inspect_test_suite.py --filter exp_b
    python scripts/inspect_test_suite.py --no-contrastives
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Tuple

_REPO = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO))

from siv.compiler import (
    _b_atom,
    _b_formula,
    _build_rename,
    _wrap_chain,
    compile_canonical_fol,
    compile_sentence_test_suite,
)
from siv.fol_parser import ParseError, parse_gold_fol
from siv.schema import (
    AtomicFormula,
    Formula,
    TripartiteQuantification,
)


# ─────────────────────────────────────────────────────────────────────────────
# Pretty-printers
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_atom(a: AtomicFormula) -> str:
    sign = "-" if a.negated else ""
    if a.pred == "__eq__" and len(a.args) == 2:
        return f"{sign}({a.args[0]} = {a.args[1]})"
    return f"{sign}{a.pred}({', '.join(a.args)})"


def _print_formula_tree(f: Formula, indent: int = 0) -> None:
    pad = "  " * indent
    if f.atomic is not None:
        print(f"{pad}atom: {_fmt_atom(f.atomic)}")
        return
    if f.quantification is not None:
        _print_quant(f.quantification, indent)
        return
    if f.negation is not None:
        print(f"{pad}negation:")
        _print_formula_tree(f.negation, indent + 1)
        return
    if f.connective is not None:
        print(f"{pad}{f.connective}:")
        for op in (f.operands or []):
            _print_formula_tree(op, indent + 1)
        return
    print(f"{pad}<empty>")


def _print_quant(q: TripartiteQuantification, indent: int) -> None:
    pad = "  " * indent
    qkind = "ALL " if q.quantifier == "universal" else "EX  "
    inner = ""
    if q.inner_quantifications:
        iq_parts = " ".join(
            f"{'ALL' if iq.quantifier == 'universal' else 'EX'} {iq.variable}"
            for iq in q.inner_quantifications
        )
        inner = f" inner=[{iq_parts}]"
    print(f"{pad}{qkind}{q.variable} (var_type={q.var_type}){inner}")
    print(f"{pad}  restrictor:")
    if not q.restrictor:
        print(f"{pad}    (empty)")
    for atom in q.restrictor:
        print(f"{pad}    {_fmt_atom(atom)}")
    print(f"{pad}  nucleus:")
    _print_formula_tree(q.nucleus, indent + 2)


# ─────────────────────────────────────────────────────────────────────────────
# Labelled positive walker
# ─────────────────────────────────────────────────────────────────────────────

def _walk_with_labels(
    node: Formula,
    enclosing: List[TripartiteQuantification],
    out: List[Tuple[str, str]],
) -> None:
    """Mirror of ``siv.compiler._subtest_walk`` that pairs each emission
    with the rule label (a / b) that produced it. The whole-formula
    canonical (label W) is added by the caller."""
    if node.atomic is not None or node.negation is not None:
        return
    if node.quantification is not None:
        q = node.quantification
        if q.quantifier == "existential":
            for atom in q.restrictor:
                fol = _emit_b(atom, q, enclosing)
                if fol is not None:
                    out.append(("b", fol))
        new_chain = enclosing + [q]
        _walk_with_labels(q.nucleus, new_chain, out)
        return
    if node.connective == "and":
        for op in node.operands or []:
            fol = _emit_a(op, enclosing)
            if fol is not None:
                out.append(("a", fol))
            _walk_with_labels(op, enclosing, out)
        return


def _emit_a(op: Formula, enclosing: List[TripartiteQuantification]):
    counter = [0]
    rename = _build_rename(enclosing, counter)
    op_fol = _b_formula(op, rename, counter)
    closure = _wrap_chain(op_fol, enclosing, rename)
    from siv.fol_utils import free_individual_variables
    if free_individual_variables(closure):
        return None
    return closure


def _emit_b(
    atom: AtomicFormula,
    inner_q: TripartiteQuantification,
    enclosing: List[TripartiteQuantification],
):
    counter = [0]
    rename = _build_rename(enclosing + [inner_q], counter)
    atom_fol = _b_atom(atom, rename)
    inner_fol = atom_fol
    if inner_q.variable in atom.args:
        inner_fol = "".join(
            ["exists ", rename[inner_q.variable], ".(", inner_fol, ")"]
        )
    for iq in inner_q.inner_quantifications:
        if iq.variable in atom.args:
            inner_fol = "".join(
                ["exists ", rename[iq.variable], ".(", inner_fol, ")"]
            )
    closure = _wrap_chain(inner_fol, enclosing, rename)
    from siv.fol_utils import free_individual_variables
    if free_individual_variables(closure):
        return None
    return closure


# ─────────────────────────────────────────────────────────────────────────────
# Per-sentence inspection
# ─────────────────────────────────────────────────────────────────────────────

def inspect_one(entry: dict, with_contrastives: bool, timeout_s: int) -> None:
    sid = entry["id"]
    cat = entry["category"]
    nl = entry["nl"]
    gold = entry["gold_fol"]
    print("=" * 78)
    print(f"  [{sid}]  ({cat})")
    print("=" * 78)
    print(f"  NL:    {nl}")
    print(f"  Gold:  {gold}")
    print()

    try:
        ext = parse_gold_fol(gold, nl=nl)
    except ParseError as e:
        print(f"  PARSE ERROR: {e}")
        print()
        return

    print("  TripartiteQuantification tree:")
    print("  " + "-" * 60)
    _print_formula_tree(ext.formula, indent=2)
    print()

    canonical = compile_canonical_fol(ext)
    print(f"  Canonical (Path A): {canonical}")
    print()

    suite = compile_sentence_test_suite(
        ext, with_contrastives=with_contrastives, timeout_s=timeout_s,
    )
    canonical_b = suite.positives[0].fol

    # Re-run a labeled walk and align with suite.positives
    labelled: List[Tuple[str, str]] = [("W", canonical_b)]
    _walk_with_labels(ext.formula, [], labelled)

    # Dedup keeping first-seen label.
    seen: dict[str, str] = {}
    order: List[str] = []
    for label, fol in labelled:
        if fol not in seen:
            seen[fol] = label
            order.append(fol)

    print(f"  Positives ({len(suite.positives)} emitted):")
    print("  " + "-" * 60)
    for i, p in enumerate(suite.positives, 1):
        label = seen.get(p.fol, "?")
        print(f"    [{i:02d}] ({label}) {p.fol}")
    print()

    if with_contrastives:
        print(f"  Contrastives ({len(suite.contrastives)} accepted):")
        print("  " + "-" * 60)
        if not suite.contrastives:
            print("    (none -- gate rejected every candidate mutant)")
        for i, c in enumerate(suite.contrastives, 1):
            mk = c.mutation_kind or "?"
            rel = c.probe_relation or "incompatible"
            print(f"    [{i:02d}] ({mk}, {rel}) {c.fol}")
        print()


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--sentences",
        default=str(_REPO / "reports" / "inspect_sentences.jsonl"),
    )
    ap.add_argument("--filter", default=None,
                    help="Only inspect entries whose category contains this substring.")
    ap.add_argument("--no-contrastives", action="store_true")
    ap.add_argument("--timeout-s", type=int, default=5)
    args = ap.parse_args()

    sentences = []
    for line in Path(args.sentences).read_text().splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if args.filter and args.filter not in e["category"]:
            continue
        sentences.append(e)

    print(f"Inspecting {len(sentences)} sentences "
          f"(contrastives={'off' if args.no_contrastives else 'on'})\n")

    for e in sentences:
        inspect_one(
            e,
            with_contrastives=not args.no_contrastives,
            timeout_s=args.timeout_s,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
