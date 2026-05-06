"""Rewrite Exp B candidates from v2 LLM-extraction vocabulary to v3
parser-from-gold vocabulary.

Background: the v2 frozen Exp B candidates use constant/predicate names from
the LLM extractor (e.g. ``theMetropolitanMuseumOfArt``, ``nyc``). The v3
test-suite probes use constants taken straight from the FOLIO gold FOL
strings (``metropolitanMuseumOfArt``, ``nYC``). The vocabulary mismatch is
external to the metric being evaluated and depresses ρ on the v3-suite
regression. Rewriting candidates into v3 vocabulary takes that variance out.

Alignment strategy (per premise):
  - Constants: lowercase + strip leading ``the`` if followed by a letter,
    then match v2 → v3 by normalized form.
  - Predicates: case-fold match.
  - Anything that doesn't align on this rule is left as-is (fallback to v2
    spelling). A summary at the end reports how many tokens couldn't be
    aligned.

Output: ``reports/experiments/exp2/scored_candidates_v3aligned.jsonl`` —
same row schema as the input, with ``candidate_fol`` rewritten and a new
``v2_candidate_fol`` field preserving the original.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_REPO = Path(__file__).parent.parent


def _load_index(path: Path) -> dict:
    out = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        out[e["premise_id"]] = e
    return out


def _norm_const(s: str) -> str:
    s = s.lower()
    return re.sub(r"^the(?=[a-z])", "", s)


def _norm_pred(s: str) -> str:
    return s.lower()


def _symbols(entry: dict) -> tuple[list[str], list[str]]:
    ext = entry.get("extraction_json") or {}
    consts = sorted(
        {c["id"] for c in (ext.get("constants") or []) + (ext.get("entities") or [])}
    )
    preds = sorted({p["name"] for p in (ext.get("predicates") or [])})
    return consts, preds


def _alphanum_bag(s: str) -> str:
    return "".join(sorted(re.sub(r"[^a-z0-9]", "", s.lower())))


def _align(src_syms: list[str], dst_syms: list[str], norm) -> dict[str, str]:
    """Per-premise alignment from src vocabulary to dst vocabulary.

    Layered match (first hit wins):
      1. Exact equality.
      2. Normalized equality (``norm`` argument: lowercase + strip ``the``).
      3. Bag equality on alphanumeric chars (handles ``october311950`` vs
         ``31October1950``).
      4. Substring containment in either direction (handles
         ``TypeOfLeukemia`` vs ``Leukemia``, ``frederickMonhoff`` vs
         ``monhoff``).
    """
    by_exact = {s: s for s in dst_syms}
    by_norm: dict[str, list[str]] = {}
    by_bag: dict[str, list[str]] = {}
    for s in dst_syms:
        by_norm.setdefault(norm(s), []).append(s)
        by_bag.setdefault(_alphanum_bag(s), []).append(s)

    out: dict[str, str] = {}
    for s in src_syms:
        if s in by_exact:
            out[s] = s
            continue
        bucket = by_norm.get(norm(s))
        if bucket:
            out[s] = bucket[0]
            continue
        bucket = by_bag.get(_alphanum_bag(s))
        if bucket:
            out[s] = bucket[0]
            continue
        # Substring containment fallback: prefer the candidate closest in
        # length to ``s`` (handles ``Hold`` → ``Holds`` over
        # ``HoldingCompany`` when both match).
        s_lc = s.lower()
        candidates = [
            d for d in dst_syms
            if s_lc in d.lower() or d.lower() in s_lc
        ]
        if candidates:
            candidates.sort(key=lambda d: abs(len(d) - len(s)))
            out[s] = candidates[0]
    return out


def _rewrite(fol: str, mapping: dict[str, str]) -> str:
    # Apply longest src first so e.g. "thePhilippines" replaces before "the".
    for src in sorted(mapping, key=len, reverse=True):
        if src == mapping[src]:
            continue
        fol = re.sub(rf"\b{re.escape(src)}\b", mapping[src], fol)
    return fol


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--candidates",
        default=str(_REPO / "reports" / "experiments" / "exp2" / "scored_candidates.jsonl"),
    )
    ap.add_argument(
        "--v2-suites",
        default=str(_REPO / "reports" / "test_suites" / "test_suites.jsonl"),
    )
    ap.add_argument(
        "--v3-suites",
        default=str(_REPO / "reports" / "test_suites" / "test_suites_v3.jsonl"),
    )
    ap.add_argument(
        "--output",
        default=str(
            _REPO
            / "reports"
            / "experiments"
            / "exp2"
            / "scored_candidates_v3aligned.jsonl"
        ),
    )
    args = ap.parse_args()

    v2 = _load_index(Path(args.v2_suites))
    v3 = _load_index(Path(args.v3_suites))

    rewritten = []
    n = 0
    n_changed = 0
    n_unaligned_const = 0
    n_unaligned_pred = 0
    unaligned_examples: list[tuple[str, str, str]] = []  # (pid, kind, sym)

    for line in Path(args.candidates).read_text().splitlines():
        if not line.strip():
            continue
        cand = json.loads(line)
        pid = cand["premise_id"]
        n += 1
        v2_entry = v2.get(pid)
        v3_entry = v3.get(pid)
        if not v2_entry or not v3_entry:
            cand["v2_candidate_fol"] = cand["candidate_fol"]
            rewritten.append(cand)
            continue

        v2_consts, v2_preds = _symbols(v2_entry)
        v3_consts, v3_preds = _symbols(v3_entry)

        const_map = _align(v2_consts, v3_consts, _norm_const)
        pred_map = _align(v2_preds, v3_preds, _norm_pred)

        for s in v2_consts:
            if s not in const_map and re.search(rf"\b{re.escape(s)}\b", cand["candidate_fol"]):
                n_unaligned_const += 1
                if len(unaligned_examples) < 10:
                    unaligned_examples.append((pid, "const", s))
        for s in v2_preds:
            if s not in pred_map and re.search(rf"\b{re.escape(s)}\b", cand["candidate_fol"]):
                n_unaligned_pred += 1
                if len(unaligned_examples) < 10:
                    unaligned_examples.append((pid, "pred", s))

        original = cand["candidate_fol"]
        merged = {**pred_map, **const_map}  # const wins on collisions
        rewritten_fol = _rewrite(original, merged)
        if rewritten_fol != original:
            n_changed += 1
        cand["v2_candidate_fol"] = original
        cand["candidate_fol"] = rewritten_fol
        rewritten.append(cand)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for c in rewritten:
            f.write(json.dumps(c) + "\n")

    print(f"candidates total:                {n}")
    print(f"  rewritten (changed):           {n_changed}")
    print(f"  unaligned constant references: {n_unaligned_const}")
    print(f"  unaligned predicate references: {n_unaligned_pred}")
    if unaligned_examples:
        print("\n  Unaligned examples (first 10):")
        for pid, kind, s in unaligned_examples:
            print(f"    {pid}  {kind:5s}  {s}")
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
