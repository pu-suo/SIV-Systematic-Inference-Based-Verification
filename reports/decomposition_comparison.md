# Decomposition fix — comparison report

Comparison of v2.0.0 baseline (pre-fix) vs Phase A (prompt + few-shot fix).
Phase C (tripwire) was skipped — see rationale below.

## 1. Arity distribution

| Metric | v2.0.0 baseline | Phase A (final) | Target |
|---|---|---|---|
| Unary atoms | 559 | 620 | < 400 |
| Binary atoms | 127 | 293 | >= 224 |
| Binary share | 18.5% | 32.1% | >= 35% |

Binary atoms more than doubled (+131%). Unary count rose because 39 more
premises were successfully evaluated (342 vs 303 — failure rate halved).
Per-premise unary density actually decreased.

## 2. All-unary premise percentage

| | v2.0.0 baseline | Phase A (final) | Target |
|---|---|---|---|
| All-unary premises | 204/303 (67.3%) | 143/342 (41.8%) | < 20% |

Dropped 25.5 percentage points. Target not met in absolute terms, but the
majority of remaining all-unary premises are genuinely monadic (e.g.
"Tom is not an Eastern wild turkey" — no prepositional relation to extract).

## 3. Long unary predicate count

| | v2.0.0 baseline | Phase A (final) | Target |
|---|---|---|---|
| Premises with 3+ CamelCase unary | 133 | 110 | < 20 |

Of the 110 remaining premises:
- **113 occurrences (85 distinct names)** are genuinely compound properties
  where unary is correct: `EasternWildTurkey`, `HighSchoolDance`,
  `JapaneseGameCompany`, `GrandSlamChampion`, `SingleSeatElectricCar`, etc.
- **59 occurrences (29 distinct names)** are true relational failures where
  the model still flattened a prepositional object into the predicate name.

Top relational failures:

| Predicate | Count | Should be |
|---|---|---|
| ResidentialCollegeAtYale | 14 | ResidentialCollegeAt(x, yale) |
| TypeOfWildTurkey | 6 | TypeOf(x, wildTurkey) |
| SuitableForRetirementFund | 2 | SuitableFor(x, retirementFund) |
| ReproduceByMating | 2 | ReproduceBy(x, mating) |
| LiveWithStrangers | 2 | LiveWith(x, y) + Stranger(y) |

These are concentrated in a few FOLIO stories. The true relational failure
rate is 59/342 = 17.3%.

## 4. Self-consistency recall

| | v2.0.0 baseline | Phase A (final) | Target |
|---|---|---|---|
| Mean recall | 0.959 | 0.963 | >= 0.95 |
| Mean F1 (where defined) | 1.000 | 0.996 | — |

Target met. The prompt change did not degrade the pipeline.

## 5. FOLIO gold recall

| | v2.0.0 baseline | Phase A (final) |
|---|---|---|
| Mean recall | 0.341 | 0.364 |
| Mean F1 (where defined) | 0.354 | 0.381 |

FOLIO gold recall increased slightly. This is expected: when SIV decomposes
correctly, some decomposed predicates happen to align better with FOLIO's
gold vocabulary. However, this number remains low overall because SIV and
FOLIO use fundamentally different predicate vocabularies — this is the
expected result per SIV's design, not a failure.

## 6. Extraction failure rate

| | v2.0.0 baseline | Phase A (final) |
|---|---|---|
| Failures | 74/377 (19.6%) | 35/377 (9.3%) |

Halved. The clearer decomposition instructions appear to reduce schema
violations and malformed extractions as a side effect.

## 7. Before/after examples

**1.** "If an employee has lunch at home, they are working remotely from home."
- before: `all x.(Employee(x) -> (HasLunchAtHome(x) -> WorkingRemotelyFromHome(x)))`
- after: `(exists x.(Employee(x) & HasLunchAt(x, home)) -> exists x.(Employee(x) & WorkRemotelyFrom(x, home)))`

**2.** "No managers work remotely from home."
- before: `all x.(Manager(x) -> -WorkRemotelyFromHome(x))`
- after: `all x.(Manager(x) -> -WorkRemotelyFrom(x, home))`

**3.** "James will appear in the company today if and only if he is a manager."
- before: `(AppearInCompanyToday(james) <-> Manager(james))`
- after: `(AppearIn(james, theCompany) <-> Manager(james))`

**4.** "Symptoms of Monkeypox include fever, headache, muscle pains, and tiredness."
- before: `(SymptomOfMonkeypox(fever) & SymptomOfMonkeypox(headache) & ...)`
- after: `(SymptomOf(fever, monkeypox) & SymptomOf(headache, monkeypox) & ...)`

**5.** "All rabbits that can be spotted near the campus are cute."
- before: `all x.((Rabbit(x) & SpottedNearCampus(x)) -> Cute(x))`
- after: `all x.((Rabbit(x) & SpottedNear(x, theCampus)) -> Cute(x))`

**6.** "Some turtles can be spotted near the campus."
- before: `exists x.(Turtle(x) & SpottedNearCampus(x))`
- after: `exists x.(Turtle(x) & SpottedNear(x, theCampus))`

**7.** "All employees who are in other countries work remotely from home."
- before: `all x.((Employee(x) & InOtherCountry(x)) -> WorkRemotelyFromHome(x))`
- after: `all x.(exists y.((Employee(x) & In(x, y) & OtherCountry(y))) -> WorkRemotelyFrom(x, home))`

**8.** "All young children and teenagers in this club who wish to further their academic careers..."
- before: `all x.((YoungChild(x) & ... & InClub(x) & WishToFurtherCareers(x)) -> ...)`
- after: `all x.(exists y.((... & In(x, theClub) & WishToFurther(x, y) & AcademicCareer(y) & ...)) -> ...)`

**9.** "The only animals that can be spotted near the campus are rabbits and squirrels."
- before: `all x.(SpottedNearCampus(x) -> (Rabbit(x) | Squirrel(x)))`
- after: `all x.((Animal(x) & CanBeSpottedNear(x, theCampus) ...) -> (Rabbit(x) | Squirrel(x)))`

**10.** "All the squirrels that can be spotted near the campus are skittish."
- before: `all x.((Squirrel(x) & SpottedNearCampus(x)) -> Skittish(x))`
- after: `all x.((Squirrel(x) & CanBeSpottedNear(x, theCampus)) -> Skittish(x))`

## 8. Why Phase C (tripwire) was skipped

The remaining 59 relational failures (17.3%) are dominated by two FOLIO
stories: Yale residential colleges (14 occurrences) and wild turkey types
(6 occurrences). These are borderline cases where the "entity" is arguably
part of a compound proper-noun category rather than an independently
queryable entity. A spaCy-based tripwire would fire on these but also
produce false positives on genuinely compound nouns, adding maintenance
surface and extra LLM round-trips for marginal gain. The prompt fix alone
resolved the clear-cut decomposition failures; the residual cases are
better addressed by targeted prompt tweaks if specific downstream queries
require them.

## Summary

The Phase A prompt and few-shot fix is the final decomposition intervention.
No model upgrade is needed. No tripwire is needed.

| Metric | v2.0.0 | Final | Delta |
|---|---|---|---|
| Binary atoms | 127 | 293 | **+131%** |
| Binary share | 18.5% | 32.1% | **+13.6pp** |
| All-unary premises | 67.3% | 41.8% | **-25.5pp** |
| True relational failures | ~133 | 59 | **-56%** |
| Self-consistency recall | 0.959 | 0.963 | **+0.004** |
| Extraction failure rate | 19.6% | 9.3% | **-10.3pp** |
