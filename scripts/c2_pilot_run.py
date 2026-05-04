"""Minimal C2 pilot runner — no heavy imports until needed."""
import os, json, sys, time, hashlib
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

OUT = Path(__file__).parent.parent / "reports" / "c2_pilots"
CACHE = OUT / ".cache"
OUT.mkdir(parents=True, exist_ok=True)
CACHE.mkdir(parents=True, exist_ok=True)

import openai
CLIENT = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def call_cached(model, prompt):
    key = hashlib.sha256(f"{model}:{prompt}".encode()).hexdigest()[:16]
    path = CACHE / f"{model}_{key}.json"
    if path.exists():
        return json.loads(path.read_text())["response"]
    r = CLIENT.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        temperature=0, max_tokens=512,
    )
    text = r.choices[0].message.content.strip()
    path.write_text(json.dumps({"model": model, "response": text}))
    return text


def extract_fol(text):
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 3:
            inner = parts[1].strip()
            if "\n" in inner:
                inner = inner.split("\n", 1)[1]
            return inner.strip()
    lines = [l.strip() for l in text.split("\n") if l.strip() and not l.startswith("The ") and not l.startswith("Here")]
    return lines[0] if lines else text.strip()


def check_equiv(corrected, gold):
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from siv.fol_utils import normalize_fol_string
    from siv.vampire_interface import check_entailment
    try:
        norm_gold = normalize_fol_string(gold)
        fwd = check_entailment(corrected, norm_gold, timeout=10)
        if fwd is not True:
            return "not_equivalent"
        bwd = check_entailment(norm_gold, corrected, timeout=10)
        return "equivalent" if bwd is True else "not_equivalent"
    except Exception as e:
        return f"error:{e}"


def load_candidates():
    """Load 30 candidates from Exp A + Exp B."""
    import random
    rng = random.Random(42)
    root = Path(__file__).parent.parent

    nl_map = {}
    for line in (root / "reports/test_suites/test_suites.jsonl").read_text().strip().split("\n"):
        row = json.loads(line)
        nl_map[row["premise_id"]] = row.get("nl", "")

    # Exp B
    exp2_gold = {}
    for line in (root / "reports/experiments/exp2/curated_premises.jsonl").read_text().strip().split("\n"):
        row = json.loads(line)
        exp2_gold[row["premise_id"]] = row["gold_fol"]

    exp_b = []
    for line in (root / "reports/experiments/exp2/scored_candidates.jsonl").read_text().strip().split("\n"):
        row = json.loads(line)
        if row["candidate_type"] in ("partial", "overweak", "overstrong"):
            pid = row["premise_id"]
            exp_b.append({"pid": pid, "nl": nl_map.get(pid,""), "gold": exp2_gold.get(pid,""),
                         "broken": row["candidate_fol"], "type": row["candidate_type"], "src": "exp_b"})

    # Exp A
    exp1_gold = {}
    for line in (root / "reports/experiments/exp1/aligned_subset_manifest.jsonl").read_text().strip().split("\n"):
        row = json.loads(line)
        if row.get("passes"):
            exp1_gold[row["premise_id"]] = row["gold_fol"]

    exp_a = []
    for line in (root / "reports/experiments/exp1/scored_candidates.jsonl").read_text().strip().split("\n"):
        row = json.loads(line)
        if row["candidate_type"] in ("B_arg_swap", "B_negation_drop"):
            pid = row["premise_id"]
            exp_a.append({"pid": pid, "nl": nl_map.get(pid,""), "gold": exp1_gold.get(pid,""),
                         "broken": row["candidate_fol"], "type": row["candidate_type"], "src": "exp_a"})

    partial = [c for c in exp_b if c["type"] == "partial"]
    overweak = [c for c in exp_b if c["type"] == "overweak"]
    overstrong = [c for c in exp_b if c["type"] == "overstrong"]
    arg_swap = [c for c in exp_a if c["type"] == "B_arg_swap"]
    neg_drop = [c for c in exp_a if c["type"] == "B_negation_drop"]

    pool = (rng.sample(partial, min(6, len(partial))) +
            rng.sample(overweak, min(5, len(overweak))) +
            rng.sample(overstrong, min(4, len(overstrong))) +
            rng.sample(arg_swap, min(8, len(arg_swap))) +
            rng.sample(neg_drop, min(7, len(neg_drop))))
    rng.shuffle(pool)
    return pool[:30]


PROMPT = """You are given a natural-language sentence and a first-order logic (FOL) translation that may contain errors. Produce ONLY the corrected FOL formula. Use the same predicate/constant naming conventions. No explanation.

Natural language: {nl}

Candidate FOL (may be incorrect): {broken}

Corrected FOL:"""


def run_pilot1():
    """Pilot 1: no-feedback baseline correction rate."""
    candidates = load_candidates()
    results_path = OUT / "pilot1_results.jsonl"

    # Check what's already done
    done = set()
    if results_path.exists():
        for line in results_path.read_text().strip().split("\n"):
            if line.strip():
                r = json.loads(line)
                done.add(f"{r['model']}:{r['pid']}")

    models = ["gpt-4o", "gpt-4o-mini"]

    with open(results_path, "a") as f:
        for i, cand in enumerate(candidates):
            for model in models:
                key = f"{model}:{cand['pid']}"
                if key in done:
                    continue

                prompt = PROMPT.format(nl=cand["nl"], broken=cand["broken"])
                response = call_cached(model, prompt)
                corrected = extract_fol(response)
                verdict = check_equiv(corrected, cand["gold"])

                row = {"model": model, "pid": cand["pid"], "type": cand["type"],
                       "src": cand["src"], "verdict": verdict, "corrected": corrected}
                f.write(json.dumps(row) + "\n")
                f.flush()
                print(f"[{i+1}/{len(candidates)}] {model} {cand['pid']} ({cand['type']}): {verdict}")


def summarize_pilot1():
    """Print pilot 1 summary from saved results."""
    results_path = OUT / "pilot1_results.jsonl"
    if not results_path.exists():
        print("No pilot 1 results yet.")
        return

    from collections import defaultdict
    by_model = defaultdict(lambda: defaultdict(list))
    for line in results_path.read_text().strip().split("\n"):
        if line.strip():
            r = json.loads(line)
            by_model[r["model"]][r["type"]].append(r["verdict"])

    print("\nPILOT 1 RESULTS")
    print("=" * 60)
    print(f"{'Model':<14} {'Type':<16} {'Equiv':>6} {'Total':>6} {'Rate':>8}")
    print("-" * 60)
    for model in sorted(by_model):
        total_e, total_n = 0, 0
        for etype in sorted(by_model[model]):
            verdicts = by_model[model][etype]
            equiv = sum(1 for v in verdicts if v == "equivalent")
            n = len(verdicts)
            total_e += equiv
            total_n += n
            print(f"{model:<14} {etype:<16} {equiv:>6} {n:>6} {equiv/n:>7.0%}")
        print(f"{model:<14} {'OVERALL':<16} {total_e:>6} {total_n:>6} {total_e/total_n:>7.0%}")
        print()


PROMPT_SCORE = """You are given a natural-language sentence and a FOL translation that may contain errors. A scoring system assigned it a quality score. Produce ONLY the corrected FOL formula.

Natural language: {nl}

Candidate FOL (may be incorrect): {broken}

Quality score: {score:.2f} out of 1.00

Corrected FOL:"""

PROMPT_CATEGORY = """You are given a natural-language sentence and a FOL translation that may contain errors. A diagnostic system identified issues. Produce ONLY the corrected FOL formula.

Natural language: {nl}

Candidate FOL (may be incorrect): {broken}

Diagnostic:
- Sub-entailment probes passed: {pos_passed}/{pos_total}
- Contrastive probes incorrectly entailed: {con_entailed}/{con_total}
- {category_note}

Corrected FOL:"""

PROMPT_PROBES = """You are given a natural-language sentence and a FOL translation that may contain errors. A diagnostic system tested it against logical probes. Produce ONLY the corrected FOL formula.

Natural language: {nl}

Candidate FOL (may be incorrect): {broken}

Failed probes (candidate SHOULD entail these but does NOT):
{failed_positives}

Incorrectly entailed probes (candidate should NOT entail these):
{entailed_contrastives}

Corrected FOL:"""


def get_probe_feedback(cand):
    """Get SIV probe feedback for a candidate."""
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from siv.gold_suite_generator import generate_test_suite_from_gold
    from siv.scorer import score as siv_score

    result = generate_test_suite_from_gold(
        cand["gold"], nl=cand["nl"], verify_round_trip=False,
        with_contrastives=True, timeout_s=10,
    )
    if result.suite is None:
        return None

    report = siv_score(result.suite, cand["broken"], timeout_s=10)

    failed_pos = []
    entailed_con = []
    for kind, fol, verdict in report.per_test_results:
        if kind == "positive" and verdict != "entailed":
            failed_pos.append(fol)
        elif kind == "contrastive" and fol and verdict == "entailed":
            entailed_con.append(fol)

    return {
        "recall": report.recall,
        "pos_total": report.positives_total,
        "pos_passed": report.positives_entailed,
        "con_total": report.contrastives_total,
        "con_entailed": report.contrastives_total - report.contrastives_rejected,
        "failed_pos": failed_pos,
        "entailed_con": entailed_con,
    }


def run_pilot2():
    """Pilot 2: leakage probe — 4 conditions on 20 candidates."""
    candidates = load_candidates()[:20]
    results_path = OUT / "pilot2_results.jsonl"
    model = "gpt-4o"

    done = set()
    if results_path.exists():
        for line in results_path.read_text().strip().split("\n"):
            if line.strip():
                r = json.loads(line)
                done.add(f"{r['condition']}:{r['pid']}")

    print("Generating probe feedback...")
    feedbacks = {}
    for cand in candidates:
        fb = get_probe_feedback(cand)
        if fb:
            feedbacks[cand["pid"]] = fb
    print(f"  Got feedback for {len(feedbacks)}/{len(candidates)}")

    conditions = ["no_feedback", "score_only", "category", "probes"]

    with open(results_path, "a") as f:
        for i, cand in enumerate(candidates):
            if cand["pid"] not in feedbacks:
                continue
            fb = feedbacks[cand["pid"]]

            for cond in conditions:
                key = f"{cond}:{cand['pid']}"
                if key in done:
                    continue

                if cond == "no_feedback":
                    prompt = PROMPT.format(nl=cand["nl"], broken=cand["broken"])
                elif cond == "score_only":
                    prompt = PROMPT_SCORE.format(nl=cand["nl"], broken=cand["broken"], score=fb["recall"])
                elif cond == "category":
                    note = ("Issue: fails to entail expected consequences (underspec)."
                            if fb["pos_passed"] < fb["pos_total"]
                            else "Issue: entails formulas it should not (overstrong)."
                            if fb["con_entailed"] > 0 else "")
                    prompt = PROMPT_CATEGORY.format(
                        nl=cand["nl"], broken=cand["broken"],
                        pos_passed=fb["pos_passed"], pos_total=fb["pos_total"],
                        con_entailed=fb["con_entailed"], con_total=fb["con_total"],
                        category_note=note)
                elif cond == "probes":
                    fp = "\n".join(f"  - {p}" for p in fb["failed_pos"][:5]) or "  (none)"
                    ec = "\n".join(f"  - {p}" for p in fb["entailed_con"][:5]) or "  (none)"
                    prompt = PROMPT_PROBES.format(
                        nl=cand["nl"], broken=cand["broken"],
                        failed_positives=fp, entailed_contrastives=ec)

                response = call_cached(model, prompt)
                corrected = extract_fol(response)
                verdict = check_equiv(corrected, cand["gold"])

                row = {"condition": cond, "model": model, "pid": cand["pid"],
                       "type": cand["type"], "verdict": verdict, "corrected": corrected}
                f.write(json.dumps(row) + "\n")
                f.flush()

            print(f"  [{i+1}/{len(candidates)}] {cand['pid']} ({cand['type']}) done")

    # Summary
    from collections import defaultdict
    by_cond = defaultdict(list)
    for line in results_path.read_text().strip().split("\n"):
        if line.strip():
            r = json.loads(line)
            by_cond[r["condition"]].append(r["verdict"])

    print("\nPILOT 2 RESULTS")
    print("=" * 50)
    nf_rate = 0
    for cond in conditions:
        verdicts = by_cond.get(cond, [])
        equiv = sum(1 for v in verdicts if v == "equivalent")
        n = len(verdicts)
        rate = equiv / n if n else 0
        if cond == "no_feedback":
            nf_rate = rate
        gain = rate - nf_rate
        print(f"  {cond:<14}: {equiv}/{n} = {rate:.0%} (gain: {gain:+.0%})")

    print("\n  Decision: pick coarsest granularity with gain >= 5pp")


def run_pilot4():
    """Pilot 4: model scaling on first 10 candidates."""
    candidates = load_candidates()[:10]
    results_path = OUT / "pilot4_results.jsonl"

    done = set()
    if results_path.exists():
        for line in results_path.read_text().strip().split("\n"):
            if line.strip():
                r = json.loads(line)
                done.add(f"{r['model']}:{r['pid']}")

    models = ["gpt-4o", "gpt-4o-mini"]

    with open(results_path, "a") as f:
        for i, cand in enumerate(candidates):
            for model in models:
                key = f"{model}:{cand['pid']}"
                if key in done:
                    continue
                prompt = PROMPT.format(nl=cand["nl"], broken=cand["broken"])
                response = call_cached(model, prompt)
                corrected = extract_fol(response)
                verdict = check_equiv(corrected, cand["gold"])
                row = {"model": model, "pid": cand["pid"], "type": cand["type"],
                       "verdict": verdict}
                f.write(json.dumps(row) + "\n")
                f.flush()
            print(f"  [{i+1}/{len(candidates)}] {cand['pid']} ({cand['type']})")

    # Summary
    from collections import defaultdict
    by_model = defaultdict(list)
    for line in results_path.read_text().strip().split("\n"):
        if line.strip():
            r = json.loads(line)
            by_model[r["model"]].append(r["verdict"])

    print("\nPILOT 4 RESULTS (scaling)")
    print("=" * 40)
    for model in models:
        verdicts = by_model.get(model, [])
        equiv = sum(1 for v in verdicts if v == "equivalent")
        n = len(verdicts)
        print(f"  {model:<14}: {equiv}/{n} = {equiv/n:.0%}" if n else f"  {model}: no data")


def run_pilot3():
    """Pilot 3: over-correction check on partial candidates."""
    candidates = load_candidates()
    partials = [c for c in candidates if c["type"] == "partial"]
    results_path = OUT / "pilot3_results.jsonl"
    model = "gpt-4o"

    done = set()
    if results_path.exists():
        for line in results_path.read_text().strip().split("\n"):
            if line.strip():
                r = json.loads(line)
                done.add(f"{r['condition']}:{r['pid']}")

    print(f"Pilot 3: {len(partials)} partial candidates")
    print("Generating probe feedback...")
    feedbacks = {}
    for cand in partials:
        fb = get_probe_feedback(cand)
        if fb:
            feedbacks[cand["pid"]] = fb
    print(f"  Got feedback for {len(feedbacks)}/{len(partials)}")

    with open(results_path, "a") as f:
        for i, cand in enumerate(partials):
            if cand["pid"] not in feedbacks:
                continue
            fb = feedbacks[cand["pid"]]

            for cond in ["score_only", "category"]:
                key = f"{cond}:{cand['pid']}"
                if key in done:
                    continue

                if cond == "score_only":
                    prompt = PROMPT_SCORE.format(nl=cand["nl"], broken=cand["broken"], score=fb["recall"])
                else:
                    note = "Issue: fails to entail expected consequences (underspec)."
                    prompt = PROMPT_CATEGORY.format(
                        nl=cand["nl"], broken=cand["broken"],
                        pos_passed=fb["pos_passed"], pos_total=fb["pos_total"],
                        con_entailed=fb["con_entailed"], con_total=fb["con_total"],
                        category_note=note)

                response = call_cached(model, prompt)
                corrected = extract_fol(response)
                verdict = check_equiv(corrected, cand["gold"])

                # Score the correction against v2 suite
                try:
                    from siv.gold_suite_generator import generate_test_suite_from_gold
                    from siv.scorer import score as siv_score
                    res = generate_test_suite_from_gold(
                        cand["gold"], nl=cand["nl"], verify_round_trip=False,
                        with_contrastives=True, timeout_s=10)
                    if res.suite:
                        rep = siv_score(res.suite, corrected, timeout_s=10)
                        corrected_recall = rep.recall
                    else:
                        corrected_recall = None
                except:
                    corrected_recall = None

                row = {"condition": cond, "model": model, "pid": cand["pid"],
                       "broken_recall": fb["recall"], "corrected_recall": corrected_recall,
                       "verdict": verdict,
                       "regressed": corrected_recall is not None and corrected_recall < fb["recall"]}
                f.write(json.dumps(row) + "\n")
                f.flush()

            print(f"  [{i+1}/{len(partials)}] {cand['pid']}: broken_recall={fb['recall']:.2f}")

    # Summary
    from collections import defaultdict
    by_cond = defaultdict(lambda: {"improved": 0, "regressed": 0, "unchanged": 0, "n": 0})
    for line in results_path.read_text().strip().split("\n"):
        if line.strip():
            r = json.loads(line)
            cond = r["condition"]
            by_cond[cond]["n"] += 1
            if r["verdict"] == "equivalent":
                by_cond[cond]["improved"] += 1
            elif r.get("regressed"):
                by_cond[cond]["regressed"] += 1
            else:
                by_cond[cond]["unchanged"] += 1

    print("\nPILOT 3 RESULTS (partial candidates only)")
    print("=" * 50)
    print(f"  {'Condition':<14} {'Improved':>9} {'Unchanged':>10} {'Regressed':>10} {'n':>4}")
    for cond in ["score_only", "category"]:
        d = by_cond[cond]
        print(f"  {cond:<14} {d['improved']:>9} {d['unchanged']:>10} {d['regressed']:>10} {d['n']:>4}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        run_pilot1()
        summarize_pilot1()
    elif cmd == "pilot2":
        run_pilot2()
    elif cmd == "pilot3":
        run_pilot3()
    elif cmd == "pilot4":
        run_pilot4()
    elif cmd == "summary":
        summarize_pilot1()
