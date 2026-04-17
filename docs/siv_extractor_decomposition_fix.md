# SIV Extractor Decomposition Fix — Claude Code Prompts

## Context for Claude Code

You are working on SIV (Systematic Inference-based Verification), a metric
for evaluating natural-language-to-FOL translations. The project is at
v2.0.0 — seven phases shipped, full pipeline working.

**The problem we're fixing:** SIV's extractor (an LLM call to
gpt-4o-2024-08-06) is systematically flattening multi-argument relations
into long unary predicates, burying entities inside predicate names instead
of extracting them as separate constants/variables with binary predicates.

Examples of the bug:
- NL: "work remotely from home" → **Current:** `WorkRemotelyFromHome(x)` → **Correct:** `WorkFrom(x, home)` with `home` as a constant
- NL: "has lunch at home" → **Current:** `HasLunchAtHome(x)` → **Correct:** `HasLunch(x, home)` with `home` as a constant
- NL: "attend the company building" → **Current:** `AttendCompanyBuilding(x)` → **Correct:** `Attend(x, y)` + `CompanyBuilding(y)`
- NL: "symptoms of Monkeypox" → **Current:** `SymptomOfMonkeypox(fever)` → **Correct:** `SymptomOf(fever, monkeypox)` with `monkeypox` as a constant
- NL: "made by Japanese game companies" → **Current:** `MadeByJapaneseCompany(x)` → **Correct:** `MadeBy(x, y)` + `JapaneseGameCompany(y)`
- NL: "lives in tax havens" → **Current:** `LiveInTaxHaven(x)` → **Correct:** `LiveIn(x, y)` + `TaxHaven(y)`

**Scale of the problem:** In the FOLIO evaluation (377 premises), 67% of
evaluated premises (203/302) have ZERO binary predicates. 114 premises
contain long flattened unary predicates (3+ CamelCase words at arity 1).
The extractor produces 510 unary predicates vs only 112 binary across the
entire corpus.

**Why this matters:** SIV's §3 Principle 2 says binary decomposition is
"non-negotiable" — every multi-participant event decomposes into atomic
binary relations. §3 Principle 2 explicitly says `Schedule(person, meeting,
customer)` should become `Schedule(person, meeting)` + `With(meeting,
customer)`, NOT `ScheduleMeetingWithCustomer(person)`. The entire downstream
usability argument — that SIV translations expose queryable entities for
knowledge graphs and theorem provers — collapses when entities are trapped
inside predicate name strings.

**Root cause:** The extraction system prompt (`prompts/extraction_system.txt`)
contains no decomposition rule. Three of the 14 few-shot examples
(`prompts/extraction_examples.json`) teach the flattening pattern:
`WorkFromHome`, `ForecastRain`, `HasFunctionalBrainstems`. The model is
capable of decomposition (it does it correctly in 99 premises), but it has
no consistent instruction to do it everywhere.

**What NOT to change:** The architecture (§6), the compiler, the contrastive
generator, the scorer, the invariants, the schema, the validator, the
`Formula` type, the `SentenceExtraction` model. The fix is in the extraction
prompt, the few-shot examples, and a new tripwire. Everything downstream of
extraction is fine.

### Key files to read before starting any phase

- `docs/SIV.md` §3 (the three principles — especially Principle 2)
- `docs/SIV.md` §5 (forbidden concepts)
- `docs/SIV.md` §6.1 (pre-analyzer)
- `docs/SIV.md` §6.3 (extractor)
- `prompts/extraction_system.txt` (current system prompt)
- `prompts/extraction_examples.json` (current 14 few-shot examples)
- `siv/pre_analyzer.py` (existing tripwire pattern to follow)
- `siv/extractor.py` (existing retry logic)
- `siv/frozen_config.py` (model config)

---

## Phase A — Fix the prompt and few-shot examples

**This is the highest-leverage fix. Do this first.**

### Read before starting

- `docs/SIV.md` §3 Principle 2 in full.
- `prompts/extraction_system.txt` in full.
- `prompts/extraction_examples.json` in full.
- `siv/extractor.py` — understand how the system prompt and examples are
  assembled into the LLM call.

### Task 1: Add a decomposition rule to `prompts/extraction_system.txt`

Add a new section to the PATTERNS block of `extraction_system.txt` titled
`DECOMPOSITION (non-negotiable)`. This section must communicate the
following rules clearly and without ambiguity:

1. **Every prepositional phrase that references a distinct entity must
   produce a binary predicate with that entity as a separate argument.**
   "work from home" → `WorkFrom(x, home)` with `home` declared as a
   Constant. "attend the company building" → `Attend(x, y)` with
   `companyBuilding` declared as a Constant (or `y` bound by a
   quantifier with `CompanyBuilding(y)` in the restrictor). Never
   `WorkFromHome(x)` or `AttendCompanyBuilding(x)`.

2. **"Of" relations are always binary.** "symptoms of Monkeypox" →
   `SymptomOf(x, monkeypox)`, arity 2. "capital city of the nation" →
   `CapitalCityOf(x, y)`, arity 2. Never flatten the second argument
   into the predicate name.

3. **Locatives, instrumentals, and indirect objects are entities, not
   predicate-name suffixes.** "has lunch at the office" → `HasLunchAt(x,
   office)`. "trained with machine learning algorithms" → `TrainedWith(x,
   machineLearningAlgorithms)`. The noun phrase after the preposition is
   always a constant or a quantified variable, never part of the
   predicate string.

4. **The test for whether something is an entity:** if a downstream query
   might ask "which X involves [this noun]?", then that noun must be a
   separate argument, not part of the predicate name. "home" in "work
   from home" is an entity because someone might query "who works from
   home?" and retrieve `home` as a binding. If it's buried in
   `WorkFromHome(x)`, that query is impossible.

5. **True properties (not relational) remain unary.** "is tall" →
   `Tall(x)`. "is spicy" → `Spicy(x)`. These have no prepositional
   argument to extract. Do not force a binary predicate where no second
   entity exists in the sentence.

Keep the rule under 200 words. Be direct. No hedging, no "consider
whether," no soft language. The LLM must understand this is mandatory.

### Task 2: Fix the three bad few-shot examples in `prompts/extraction_examples.json`

Find and fix these three examples:

**Example: "Archie can walk if and only if he has functional brainstems."**
- Current: `HasFunctionalBrainstems(archie)` — arity 1.
- This one is borderline. "Functional brainstems" is arguably a property,
  not a separate entity. Leave it as-is OR decompose to
  `Has(archie, y)` + `FunctionalBrainstem(y)`. Use your judgment —
  "brainstems" is unlikely to be a downstream query target. If you leave
  it, add a comment in the system prompt clarifying that compound
  adjective+noun properties (where the noun is not independently
  queryable) can stay unary.

**Example: "If the forecast calls for rain, then all employees work from home."**
- Current: `ForecastRain(weather)` + `WorkFromHome(x)` — both arity 1.
- Fix `WorkFromHome(x)` → `WorkFrom(x, home)` with `home` as a Constant.
  This is the canonical case: "home" is a location entity.
- Fix `ForecastRain(weather)` → `ForecastCallsFor(weather, rain)` with
  `rain` as a Constant, arity 2. "Rain" is an entity the forecast
  references.

**Example: "People in this club who chaperone high school dances are not students who attend the school."**
- Current: `PersonInClub(x)` — arity 1.
- This one is a judgment call. "this club" is a specific entity. Fix to:
  `PersonIn(x, y)` + `Club(y)` with an inner existential on `y`, OR
  `InClub(x, thisClub)` with `thisClub` as a Constant. The current
  example already correctly decomposes `Chaperone(x, y)` +
  `HighSchoolDance(y)` and `Attend(x, theSchool)`, so the only issue
  is `PersonInClub`. Fix it to be consistent with the decomposition
  rule.

### Task 3: Add 4 new few-shot examples targeting the failure classes

Add these to `extraction_examples.json`. They must demonstrate the
decomposition rule on the exact patterns that failed in the FOLIO run.
Each example must be complete (full `SentenceExtraction` JSON with all
null fields populated — match the format of the existing 14 exactly).

**New example 1 — Verb + Preposition + Location:**
Sentence: "All managers have lunch at the office."
Must produce: `Manager(x)` in restrictor, `HaveLunch(x, y)` +
`Office(y)` in the nucleus (or `HaveLunchAt(x, office)` with `office`
as a Constant). NOT `HaveLunchAtTheOffice(x)`.

**New example 2 — "of" relation:**
Sentence: "Symptoms of the flu include fever and headache."
Must produce: `SymptomOf(fever, flu)` and `SymptomOf(headache, flu)` —
binary, with `flu`, `fever`, `headache` as Constants. NOT
`SymptomOfFlu(fever)`.

**New example 3 — Passive + agent:**
Sentence: "All games on the list are made by Japanese companies."
Must produce: restrictor `Game(x)` + `OnList(x, theList)` with
`theList` as a Constant; nucleus `MadeBy(x, y)` +
`JapaneseCompany(y)` with existential on `y`. NOT
`MadeByJapaneseCompany(x)`.

**New example 4 — "lives in" / locative:**
Sentence: "All well-paid people live in tax havens."
Must produce: restrictor `WellPaid(x)` + `Person(x)`; nucleus
`LiveIn(x, y)` + `TaxHaven(y)` with existential on `y`. NOT
`LiveInTaxHaven(x)`.

### Constraints

- Do NOT add any fields to the schema, to `SentenceExtraction`, to
  `Formula`, or to any Pydantic model. The schema is correct; the
  prompt is wrong.
- Do NOT modify the compiler, generator, scorer, or invariants.
- Do NOT add any item from §5 (forbidden concepts).
- Do NOT change the model in `frozen_config.py` yet. Phase B evaluates
  whether a model change is needed.
- Clear the extraction cache (`.siv_cache/extraction_cache.jsonl`) after
  modifying the prompt or examples, so that the next run uses the new
  prompt. The cache keys are SHA256 hashes of the full prompt; stale
  cache entries will prevent the new prompt from being used.

### Verification

After making the changes, manually verify that the updated prompt and
examples are self-consistent:
- Every few-shot example in `extraction_examples.json` must obey the
  new decomposition rule. If any existing example violates it (beyond
  the three identified above), fix it.
- The system prompt's DECOMPOSITION section must not contradict any
  other section of the system prompt.
- Run `pytest tests/test_extractor.py tests/test_schema.py` — these
  must remain green. The tests use mocked LLM responses, so the prompt
  changes don't affect them, but confirm nothing is broken.
- Inspect the `_restrictor_extraction()` fixture in
  `tests/test_extractor.py`. It already correctly uses binary
  predicates (`Schedule(x, y)`, `Attend(x, z)`). Confirm the fixture
  is consistent with the new decomposition rule. If not, update it.

### Commit

Single commit. Message: "Fix extractor prompt: add mandatory
decomposition rule, fix flattened few-shot examples, add 4 new
decomposition examples."

---

## Phase B — Evaluate whether gpt-4o is sufficient

**Do this after Phase A is committed.**

### Read before starting

- `siv/frozen_config.py`
- `scripts/run_folio_evaluation.py`
- `reports/folio_agreement.json` (Phase 5 results — this is the baseline)

### Task

Run the full FOLIO evaluation with the Phase A prompt changes. Then
measure whether the decomposition problem is fixed.

**Step 1:** Clear the extraction cache:
```bash
rm -f .siv_cache/extraction_cache.jsonl
```

**Step 2:** Run the evaluation:
```bash
python scripts/run_folio_evaluation.py
```

**Step 3:** Analyze the results. Write a script
`scripts/analyze_decomposition.py` that reads the new
`reports/folio_agreement.json` and reports:

1. **Arity distribution.** For every predicate in every SIV translation:
   count arity-1 vs arity-2. Compare to the Phase 5 baseline
   (510 unary / 112 binary). Target: binary predicates should at least
   double (>224), unary should drop below 400.

2. **All-unary premise count.** How many premises have zero binary
   predicates? Baseline: 203/302 (67%). Target: under 20%.

3. **Long unary predicate count.** How many arity-1 predicates have 3+
   CamelCase words (the flattening signature)? Baseline: 114 premises.
   Target: under 20.

4. **Self-consistency recall.** Must remain ≥ 0.95 mean recall. The
   prompt change should not break the pipeline.

5. **Show 10 examples** where the same NL sentence was previously
   flattened (in the Phase 5 baseline) and is now decomposed. This is
   the before/after evidence.

If the decomposition targets are NOT met (binary still under 200,
all-unary still over 30%), then the model may not be following the new
prompt instructions reliably. In that case:

- First, check if the cache was properly cleared. Stale cache entries
  will return old extractions regardless of prompt changes.
- If the cache is cleared and the model still flattens, try adding
  stronger negative examples to the prompt: show an INCORRECT
  flattened extraction followed by the CORRECT decomposed extraction,
  labeled explicitly as "WRONG" and "RIGHT".
- If that still fails, the model may not be capable enough. Document
  the failure rate and recommend testing with a more capable model
  (see frozen_config.py — the PRIMARY_MODEL can be changed). Options
  to try: `gpt-4o-2025-xx` (latest snapshot if available), `gpt-4-turbo`,
  or `o3-mini` if it supports structured output. The model must support
  OpenAI JSON Schema `response_format` with `strict: true`.

### Constraints

- Do NOT modify the prompt or examples in this phase. Phase A's changes
  are frozen; this phase is measurement only.
- Do NOT change the model yet. If the conclusion is "model needs
  upgrading," document it and stop. Phase B is evaluation, not action.
- The evaluation script writes to `reports/folio_agreement.json`. Save
  the Phase 5 baseline first:
  ```bash
  cp reports/folio_agreement.json reports/folio_agreement_v2.0.0_baseline.json
  ```

### Deliverables

- `scripts/analyze_decomposition.py` (the analysis script)
- `reports/folio_agreement.json` (updated with Phase A prompt)
- `reports/decomposition_analysis.md` — a short document (under 1 page)
  reporting the five metrics above, with a clear recommendation:
  "prompt fix sufficient" or "model upgrade needed."

### Commit

Single commit. Message: "Phase B: evaluate decomposition fix on FOLIO
corpus."

---

## Phase C — Add a decomposition tripwire

**Do this after Phase B confirms the prompt fix is directionally
correct (even if not perfect).**

### Read before starting

- `siv/pre_analyzer.py` — this is the pattern to follow. The existing
  tripwires (`requires_restrictor`, `requires_negation`) detect
  structural features via spaCy and enforce them post-extraction. The
  decomposition tripwire follows the same architecture.
- `siv/extractor.py` — understand the retry logic. On tripwire
  violation, the extractor retries once with the violation message
  appended. Same mechanism applies here.
- `docs/SIV.md` §6.1 (pre-analyzer contract).

### Task 1: Add `requires_decomposition` to `pre_analyzer.py`

Add a third flag to `RequiredFeatures`:

```python
@dataclass(frozen=True)
class RequiredFeatures:
    requires_restrictor: bool
    requires_negation: bool
    requires_decomposition: List[str]  # list of NL noun phrases that
                                        # must appear as entities/constants,
                                        # not inside predicate names
```

Detection logic in `compute_required_features`:

1. Parse the sentence with spaCy.
2. For each token where `dep_` is `pobj` (object of preposition) or
   `dative` (indirect object): if the token (or its subtree head) is a
   noun or proper noun (`pos_` in `{"NOUN", "PROPN"}`), record its
   lemma as a required-decomposition entity.
3. Additionally, for each prepositional phrase headed by "of", "in",
   "at", "from", "to", "by", "with" where the object is a noun:
   record the object's lemma.
4. Return the list of lemmas. An empty list means no decomposition
   is structurally required.

This is a heuristic, not a perfect detector. It will have false
positives (some prepositional objects are genuinely part of a compound
adjective, not a separate entity). That's acceptable — the tripwire
triggers a retry, not a hard failure. The retry prompt tells the LLM
"the noun X should be a separate entity, not part of a predicate name;
decompose accordingly." If the LLM still flattens on retry, the
extraction proceeds (same as the existing tripwires — one retry, then
accept).

### Task 2: Add tripwire enforcement to `siv/extractor.py`

In the post-extraction validation (where `requires_restrictor` and
`requires_negation` are currently checked), add:

For each lemma in `requires_decomposition`:
1. Collect all predicate names from the extraction.
2. Split each predicate name into CamelCase words and lowercase them.
3. If the lemma appears inside a predicate name BUT does not appear as
   a constant id, entity id, or quantified variable argument anywhere
   in the extraction's formula tree — the entity is trapped.
4. Raise `SchemaViolation(f"Entity '{lemma}' is trapped inside predicate
   name '{pred_name}' — decompose into a binary predicate with '{lemma}'
   as a separate argument.")`.
5. On retry, append this message to the user content (same pattern as
   existing tripwires).

**Important edge cases:**
- If the lemma appears BOTH in a predicate name AND as a constant/entity,
  that's fine — the entity is extracted even if the predicate name also
  mentions it.
- Common words that are genuinely part of predicate semantics (e.g.,
  "is", "are", "the") should be excluded. Filter to nouns/proper nouns
  only (the spaCy POS tag check in step 2 of the detection logic
  handles this).
- The lemma match should be case-insensitive and stem-insensitive
  (compare lowercased forms).

### Task 3: Update `docs/SIV.md` §6.1

Add `requires_decomposition` to the pre-analyzer spec. Keep it parallel
to the existing two flags. Add a short description:

> `requires_decomposition`: a list of noun lemmas from prepositional
> objects in the sentence. If any of these lemmas appears inside a
> predicate name in the extraction but is not separately declared as a
> constant, entity, or variable argument, the tripwire fires.

### Task 4: Tests

Add to `tests/test_pre_analyzer.py`:
- Test that "All employees work from home" produces
  `requires_decomposition` containing `"home"`.
- Test that "All dogs are mammals" produces an empty list.
- Test that "She has lunch at the office" produces
  `requires_decomposition` containing `"office"`.

Add to `tests/test_extractor.py`:
- Mocked test: extraction with `WorkFromHome(x)` for "work from home"
  triggers decomposition tripwire, retry produces `WorkFrom(x, home)`,
  test passes.
- Mocked test: extraction already has `WorkFrom(x, home)` — no
  tripwire fires.
- Mocked test: both retries flatten — extraction proceeds (no infinite
  loop), same as existing tripwire behavior.

### Constraints

- The `RequiredFeatures` dataclass gains one field. Nothing else in the
  pre-analyzer changes. No modal, temporal, proportional, or ontological
  detection.
- The tripwire follows the existing retry pattern exactly: one retry,
  then accept. No infinite loops. No hard failures on decomposition
  violations — the tripwire is best-effort, not a gate.
- Do NOT add anything from §5 (forbidden concepts).
- All existing tests must remain green.

### Commit

Single commit. Message: "Add decomposition tripwire to pre-analyzer
and extractor."

---

## Phase D — Re-run FOLIO evaluation and compare

**Do this after Phase C is committed.**

### Read before starting

- `scripts/run_folio_evaluation.py`
- `scripts/analyze_decomposition.py` (from Phase B)
- `reports/folio_agreement_v2.0.0_baseline.json` (saved in Phase B)

### Task

**Step 1:** Clear the extraction cache:
```bash
rm -f .siv_cache/extraction_cache.jsonl
```

**Step 2:** Run the full evaluation:
```bash
python scripts/run_folio_evaluation.py
```

**Step 3:** Run the decomposition analysis from Phase B against the new
results:
```bash
python scripts/analyze_decomposition.py
```

**Step 4:** Write `reports/decomposition_comparison.md` comparing three
columns: v2.0.0 baseline → Phase A (prompt only) → Phase D (prompt +
tripwire). Report:

1. **Arity distribution** (unary / binary counts).
2. **All-unary premise percentage.**
3. **Long-unary predicate count.**
4. **Self-consistency recall** (must remain ≥ 0.95).
5. **FOLIO gold recall** — note that this number may go DOWN because
   SIV now uses more binary predicates which diverge even further from
   gold's vocabulary. That is expected and correct: the vocabulary
   divergence number was always contaminated; a lower recall with better
   decomposition is more honest than a higher recall with flattened
   predicates. State this explicitly.
6. **10 before/after examples** showing the decomposition fix working
   on real FOLIO premises.
7. **Remaining flattening cases** — premises where the tripwire fired
   but the model still flattened. Count and categorize: are these
   genuine compound properties (where unary is correct) or real
   failures?

**Step 5:** If remaining flattening cases exceed 15% of premises,
recommend a model upgrade in the report. Identify which models support
OpenAI JSON Schema `response_format` with `strict: true` and are
candidates. Do NOT change the model; document the recommendation.

### Constraints

- Do NOT modify the prompt, examples, pre-analyzer, or extractor in
  this phase. This is measurement only.
- Do NOT change any scoring thresholds or gates.
- Preserve the previous reports by saving with timestamp suffixes.

### Deliverables

- `reports/folio_agreement.json` (updated)
- `reports/decomposition_comparison.md`

### Commit

Single commit. Message: "Phase D: FOLIO re-evaluation with
decomposition fix, comparison report."

---

## Ordering and dependencies

```
Phase A (prompt + examples)
    │
    ▼
Phase B (evaluate → is prompt fix enough?)
    │
    ├── if yes ──► Phase C (tripwire) ──► Phase D (final eval)
    │
    └── if no ───► diagnose further (cache? stronger examples? model?)
                   then retry Phase B
```

Phase A is the critical path. If Phase A alone fixes >80% of flattening
cases, Phase C (tripwire) is a safety net. If Phase A fixes <50%, the
prompt needs more work before adding a tripwire on top.

## What success looks like

After all four phases:
- Binary predicates ≥ 35% of all predicates (up from 18%)
- All-unary premises < 20% (down from 67%)
- Long flattened unary predicates < 20 (down from 114)
- Self-consistency recall ≥ 0.95 (maintained)
- Every prepositional object in the NL that is a noun appears as a
  constant or entity in the extraction, not buried in a predicate name
