"""
MALLS-LE equivalence metric: bidirectional entailment via Vampire.

For each (candidate, gold) pair, checks both directions:
  candidate ⊨ gold  AND  gold ⊨ candidate
If both succeed → 1.0 (logically equivalent), else 0.0.

Two variants:
  - raw: no vocabulary alignment (fails across different predicate names)
  - aligned: symbol alignment via siv.aligner before checking entailment
"""
from __future__ import annotations

from typing import Dict, List, Optional

from siv.fol_utils import normalize_fol_string
from siv.vampire_interface import check_entailment


def malls_le_equivalence(
    candidate_fol: str,
    gold_fol: str,
    timeout: int = 10,
) -> Optional[float]:
    """Check bidirectional entailment without vocabulary alignment.

    Returns 1.0 (equivalent), 0.0 (not equivalent), or None (parse error).
    """
    cand = normalize_fol_string(candidate_fol)
    gold = normalize_fol_string(gold_fol)
    if not cand or not gold:
        return None

    forward = check_entailment(cand, gold, timeout=timeout)
    if forward is None:
        return None
    if forward is False:
        return 0.0

    backward = check_entailment(gold, cand, timeout=timeout)
    if backward is None:
        return None
    return 1.0 if backward else 0.0


def malls_le_equivalence_aligned(
    candidate_fol: str,
    gold_fol: str,
    timeout: int = 10,
) -> Optional[float]:
    """Check bidirectional entailment with symbol alignment.

    Aligns candidate vocabulary to gold vocabulary before checking,
    giving MALLS-LE its best possible shot.
    """
    from siv.aligner import align_symbols, extract_symbols_from_fol

    cand_norm = normalize_fol_string(candidate_fol)
    gold_norm = normalize_fol_string(gold_fol)
    if not cand_norm or not gold_norm:
        return None

    gold_symbols = extract_symbols_from_fol(gold_norm)
    cand_symbols = extract_symbols_from_fol(cand_norm)
    alignment = align_symbols(gold_symbols, cand_symbols)

    # Build substitution: candidate name → gold name
    rename_map: Dict[str, str] = {}
    for gold_name, cand_name in alignment.predicate_map.items():
        if gold_name != cand_name:
            rename_map[cand_name] = gold_name
    for gold_name, cand_name in alignment.constant_map.items():
        if gold_name != cand_name:
            rename_map[cand_name] = gold_name

    # Apply renaming to candidate FOL
    aligned_cand = cand_norm
    if rename_map:
        import re
        pattern = re.compile(
            r"|".join(
                rf"(?<![A-Za-z0-9_]){re.escape(old)}(?![A-Za-z0-9_])"
                for old in sorted(rename_map, key=len, reverse=True)
            )
        )
        aligned_cand = pattern.sub(
            lambda m: rename_map[m.group(0)], aligned_cand
        )

    return malls_le_equivalence(aligned_cand, gold_norm, timeout=timeout)


def malls_le_batch(
    candidates: List[str],
    golds: List[str],
    timeout: int = 10,
    aligned: bool = False,
) -> Dict[str, object]:
    """Batch MALLS-LE over parallel premise lists.

    Returns {"mean": float, "per_premise": [float|None, ...]}.
    """
    if len(candidates) != len(golds):
        raise ValueError("candidates and golds must have the same length")

    fn = malls_le_equivalence_aligned if aligned else malls_le_equivalence
    per_premise = [fn(c, g, timeout=timeout) for c, g in zip(candidates, golds)]

    scored = [v for v in per_premise if v is not None]
    mean = sum(scored) / len(scored) if scored else 0.0

    return {"mean": mean, "per_premise": per_premise}
