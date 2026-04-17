# Decomposition analysis

Current report: n_evaluated=342 failures=35
Baseline report: n_evaluated=303 failures=74

## 1. Arity distribution

| Metric | Baseline | Current | Target |
|---|---|---|---|
| Unary atoms | 559 | 620 | < 400 |
| Binary atoms | 127 | 293 | ≥ 224 (2×baseline) |
| Binary share | 18.5% | 32.1% | ≥ 35% |

## 2. All-unary premises

- Baseline: 204/303 (67.3%)
- Current:  143/342 (41.8%)
- Target:  < 20%

## 3. Long unary predicates (3+ CamelCase words, arity 1)

- Baseline: 133 premises (233 occurrences, 179 distinct names)
- Current:  110 premises (172 occurrences, 114 distinct names)
- Target:  < 20 premises

Top current long-unary names:
  - ResidentialCollegeAtYale (×14)
  - TypeOfWildTurkey (×6)
  - SingleSeatElectricCar (×3)
  - FamilyFriendlyAnimatedFilm (×3)
  - HighSchoolDance (×2)
  - JapaneseGameCompany (×2)
  - GrandSlamChampion (×2)
  - OscarNominatedActor (×2)
  - ProfessionalTennisPlayer (×2)
  - BrownSwissCattle (×2)
  - SuitableForRetirementFund (×2)
  - NeedToEarnMoney (×2)
  - NeedsToEarnMoney (×2)
  - HasRatingGreaterThanFour (×2)
  - NLPTask (×2)

## 4. Self-consistency recall

- Baseline: 0.9587458745874587
- Current:  0.9627680311890838
- Target:   ≥ 0.95

## 5. Before/after examples (up to 10)

**1.** All young children and teenagers in this club who wish to further their academic careers and educational opportunities are students who attend the school.
- before: `all x.((YoungChild(x) & Teenager(x) & InClub(x) & WishToFurtherCareers(x)) -> (Student(x) & Attend(x, theSchool)))`
- after:  `all x.(exists y.((YoungChild(x) & Teenager(x) & In(x, theClub) & WishToFurther(x, y) & AcademicCareer(y) & EducationalOpportunity(y))) -> (Student(x) & Attend(x, theSchool)))`

**2.** If an employee has lunch at home, they are working remotely from home.
- before: `all x.(Employee(x) -> (HasLunchAtHome(x) -> WorkingRemotelyFromHome(x)))`
- after:  `(exists x.(Employee(x) & HasLunchAt(x, home)) -> exists x.(Employee(x) & WorkRemotelyFrom(x, home)))`

**3.** All employees who are in other countries work remotely from home.
- before: `all x.((Employee(x) & InOtherCountry(x)) -> WorkRemotelyFromHome(x))`
- after:  `all x.(exists y.((Employee(x) & In(x, y) & OtherCountry(y))) -> WorkRemotelyFrom(x, home))`

**4.** No managers work remotely from home.
- before: `all x.(Manager(x) -> -WorkRemotelyFromHome(x))`
- after:  `all x.(Manager(x) -> -WorkRemotelyFrom(x, home))`

**5.** James will appear in the company today if and only if he is a manager.
- before: `(AppearInCompanyToday(james) <-> Manager(james))`
- after:  `(AppearIn(james, theCompany) <-> Manager(james))`

**6.** Symptoms of Monkeypox include fever, headache, muscle pains, and tiredness.
- before: `(SymptomOfMonkeypox(fever) & SymptomOfMonkeypox(headache) & SymptomOfMonkeypox(musclePains) & SymptomOfMonkeypox(tiredness))`
- after:  `(SymptomOf(fever, monkeypox) & SymptomOf(headache, monkeypox) & SymptomOf(musclePains, monkeypox) & SymptomOf(tiredness, monkeypox))`

**7.** All rabbits that can be spotted near the campus are cute.
- before: `all x.((Rabbit(x) & SpottedNearCampus(x)) -> Cute(x))`
- after:  `all x.((Rabbit(x) & SpottedNear(x, theCampus)) -> Cute(x))`

**8.** Some turtles can be spotted near the campus.
- before: `exists x.(Turtle(x) & SpottedNearCampus(x))`
- after:  `exists x.(Turtle(x) & SpottedNear(x, theCampus))`

**9.** The only animals that can be spotted near the campus are rabbits and squirrels.
- before: `all x.(SpottedNearCampus(x) -> (Rabbit(x) | Squirrel(x)))`
- after:  `all x.((Animal(x) & CanBeSpottedNear(x, theCampus) & Campus(theCampus)) -> (Rabbit(x) | Squirrel(x)))`

**10.** All the squirrels that can be spotted near the campus are skittish.
- before: `all x.((Squirrel(x) & SpottedNearCampus(x)) -> Skittish(x))`
- after:  `all x.((Squirrel(x) & CanBeSpottedNear(x, theCampus)) -> Skittish(x))`

## Recommendation

**Partial.** Binary predicates more than doubled but absolute targets not yet met. Phase C tripwire should close the remaining gap.
