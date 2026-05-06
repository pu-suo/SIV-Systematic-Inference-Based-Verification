"""Post-regeneration audit: scan v3 positives for the failure modes that
caused the previous v3 regression.

Hard checks (any hit fails the gate):
  - type-unsoundness: a probe in which a known constant appears in the
    bound-variable position of a type predicate (the ``DrinkRegularly(
    caffeine, coffee)``-style defect).
  - vacuously-bound variable: an ``exists v.(...)`` or ``all v.(...)``
    whose body does not mention ``v``.

Soft summary:
  - mean #positives / #contrastives per premise
  - distribution of contrastive probe_relations
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

V3 = Path("reports/test_suites/test_suites_v3.jsonl")


def vacuously_bound(fol: str) -> str | None:
    """Return the offending variable name iff some quantifier in ``fol``
    binds a variable that doesn't appear inside its scope."""
    for m in re.finditer(r"(all|exists)\s+(v\d+)\.\(", fol):
        var = m.group(2)
        i = m.end()
        depth = 1
        while i < len(fol) and depth > 0:
            if fol[i] == "(":
                depth += 1
            elif fol[i] == ")":
                depth -= 1
            i += 1
        body = fol[m.end():i - 1]
        if not re.search(rf"\b{re.escape(var)}\b", body):
            return var
    return None


def type_unsound(fol: str, canonical: str, constants: set[str]) -> str | None:
    """Return the offending atom iff a probe replaces a *bound-variable
    position* in the canonical with a constant — the defective shape
    ``DrinkRegularly(caffeine, coffee)`` derived from canonical
    ``∀x.(DrinkRegularly(x, coffee) → ...)`` (the removed
    universal-instantiation operator).

    Precise check: for every predicate-call (pred, args) in the probe, look
    up the canonical's atom with the same ``pred``. If the canonical's
    arguments at any position are *bound variables* (matching ``\\bv?[a-z]\\b``
    in the canonical's vocabulary or showing up after an enclosing
    ``all|exists v.`` binder) and the probe substitutes a known constant
    there, flag it. Ground-instance premises where the canonical's atoms
    already use constants in those positions are not flagged."""
    canonical_atoms: dict[str, list[list[str]]] = {}
    for m in re.finditer(r"([A-Z][A-Za-z0-9_]*)\(([^)]+)\)", canonical):
        pred = m.group(1)
        args = [a.strip() for a in m.group(2).split(",")]
        canonical_atoms.setdefault(pred, []).append(args)

    # Bound vars in canonical: identifiers introduced by ``all`` / ``exists``.
    bound = set(re.findall(r"\b(?:all|exists)\s+(\w+)\.", canonical))

    for m in re.finditer(r"([A-Z][A-Za-z0-9_]*)\(([^)]+)\)", fol):
        pred = m.group(1)
        probe_args = [a.strip() for a in m.group(2).split(",")]
        if pred not in canonical_atoms:
            continue
        for canon_args in canonical_atoms[pred]:
            if len(canon_args) != len(probe_args):
                continue
            for canon_a, probe_a in zip(canon_args, probe_args):
                if canon_a in bound and probe_a in constants:
                    return f"{pred}({m.group(2)})"
    return None


def main() -> int:
    n = 0
    n_type_unsound = 0
    n_vacuous = 0
    n_pos_total = 0
    n_con_total = 0
    relation_counter: Counter[str] = Counter()
    examples_unsound = []
    examples_vacuous = []
    suites_with_constants = 0

    for line in V3.read_text().splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        n += 1
        constants = {c["id"] for c in e.get("extraction_json", {}).get("constants", [])}
        constants |= {c["id"] for c in e.get("extraction_json", {}).get("entities", [])}
        if constants:
            suites_with_constants += 1
        for p in e["positives"]:
            n_pos_total += 1
            v = vacuously_bound(p["fol"])
            if v is not None:
                n_vacuous += 1
                if len(examples_vacuous) < 5:
                    examples_vacuous.append((e["premise_id"], p["fol"]))
            t = type_unsound(p["fol"], e["canonical_fol"], constants)
            if t is not None:
                n_type_unsound += 1
                if len(examples_unsound) < 5:
                    examples_unsound.append((e["premise_id"], t, p["fol"]))
        for c in e["contrastives"]:
            n_con_total += 1
            relation_counter[c.get("probe_relation") or "incompatible"] += 1

    print(f"premises:                 {n}")
    print(f"  with constants:         {suites_with_constants}")
    print(f"positives total:          {n_pos_total}")
    print(f"  type-unsound (FAIL):    {n_type_unsound}")
    print(f"  vacuously bound (FAIL): {n_vacuous}")
    print(f"contrastives total:       {n_con_total}")
    print(f"  by relation:            {dict(relation_counter)}")
    print(f"mean positives:           {n_pos_total / n:.2f}")
    print(f"mean contrastives:        {n_con_total / n:.2f}")
    if examples_unsound:
        print("\nType-unsound examples:")
        for pid, atom, fol in examples_unsound:
            print(f"  {pid}: {atom} in {fol[:100]}")
    if examples_vacuous:
        print("\nVacuously-bound examples:")
        for pid, fol in examples_vacuous:
            print(f"  {pid}: {fol[:100]}")
    return 0 if (n_type_unsound == 0 and n_vacuous == 0) else 2


if __name__ == "__main__":
    raise SystemExit(main())
