# Phase 1P Diagnostic Summary

## Tentative Category Distribution

| Category | Count | % |
|---|---|---|
| vocabulary_only | 18 | 36% |
| quantifier_scope_diff | 8 | 16% |
| restrictor_structure_diff | 8 | 16% |
| extraction_failure | 7 | 14% |
| const_vs_pred_asymmetry | 4 | 8% |
| compound_vs_decomposed | 3 | 6% |
| exact_match | 2 | 4% |

## Stratum Distribution

| Stratum | Count |
|---|---|
| S2_universal_simple | 12 |
| S3_universal_multi_restrictor | 12 |
| S5_relational | 10 |
| S4_nested_quantifier | 8 |
| S1_atomic | 3 |
| S6_negation | 2 |
| unparseable | 2 |
| S8_other | 1 |

## Mechanical Agreement Rate

Premises where SIV and gold agree (modulo vocabulary): **20/50** (40%)

Premises needing human review: **30/50**

## Disagreement Categories (needs review)

| Category | Count | % of disagreements |
|---|---|---|
| quantifier_scope_diff | 8 | 27% |
| restrictor_structure_diff | 8 | 27% |
| extraction_failure | 7 | 23% |
| const_vs_pred_asymmetry | 4 | 13% |
| compound_vs_decomposed | 3 | 10% |

## Representative Examples per Category

### compound_vs_decomposed (3 cases)

- **P0965**: All books written by Neil Gaiman have sold more than one thousand copies....
  - SIV: `all x.((Book(x) & WrittenBy(x, neilGaiman)) -> SoldMoreThanOneThousand`
  - Gold: `all x ((Book(x) & WrittenBy(x, neilGaiman)) -> exists y (MoreThan(y, n`
- **P0795**: If a horse falls in a race, it poses risks to its rider....
  - SIV: `all x.(Horse(x) -> exists y.((Race(y) & FallsIn(x, y)) & exists z.(Rid`
  - Gold: `all x (Horse(x) & InRace(x) & Falls(x) -> PoseRiskTo(x, rider))`
- **P0792**: James is a customer who is not between the ages of 60 and 80....
  - SIV: `(Customer(james) & -AgeBetween60And80(james))`
  - Gold: `Customer(james) & (-exists y(Between(y, num60, num80) & Age(james, y))`

### const_vs_pred_asymmetry (4 cases)

- **P1150**: If a European plays football, they play what Americans call soccer....
  - SIV: `all x.(European(x) -> (exists y.(Football(y) & Plays(x, y)) -> exists `
  - Gold: `all x (FootballPlayer(x) & European(x) -> exists y (Call(american, y, `
- **P1250**: Top soccer players are soccer players who can use both the left foot and right f...
  - SIV: `all x.(TopSoccerPlayer(x) -> (SoccerPlayer(x) & exists y.(LeftFoot(y) `
  - Gold: `all x (SoccerPlayer(x) & UseEfficiently(x, leftFoot) & UseEfficiently(`
- **P1561**: A werewolf is a human that can turn into a wolf....
  - SIV: `all x.(Werewolf(x) -> exists y.((Human(x) & Wolf(y)) & CanTurnInto(x, `
  - Gold: `all x (Human(x) & CanTurnInto(x, wolf) -> Werewolf(x))`

### extraction_failure (7 cases)

- **P0689**: Everyone who took the bar exam is knowledgeable about criminal procedures....
  - SIV: `EXTRACTION FAILED`
  - Gold: `all x (Take(x, barExam) -> KnowledgeableAbout(x, criminalProceeder))`
- **P1041**: If Robin's friends study hard, then they grew up with parents who worked as doct...
  - SIV: `EXTRACTION FAILED`
  - Gold: `all x (RobinsFriends(x) & StudyHard(x) -> exists y exists z (-(y=z) & `
- **P1025**: If two soccer teams score the same number of goals in one UCL final during both ...
  - SIV: `EXTRACTION FAILED`
  - Gold: `all x all y (SoccerTeam(x) & SoccerTeam(y) & SameScore(x, y) & During(`

### quantifier_scope_diff (8 cases)

- **P0302**: Pre-recorded content is a copyright violation....
  - SIV: `CopyrightViolation(x)`
  - Gold: `all x (Prerecorded(x) -> CopyrightViolation(x))`
- **P1621**: A neuroimaging technique is either an invasive neuroimaging technique or a nonin...
  - SIV: `exists x.(NeuroimagingTechnique(x) & (InvasiveNeuroimagingTechnique(x)`
  - Gold: `all x (NeuroimagingTechnique(x) -> (((Invasive(x) & -(Noninvasive(x)))`
- **P1261**: Rhos Aelwyd F.C. is a Welsh football club....
  - SIV: `WelshFootballClub(rhosAelwydFc)`
  - Gold: `all x (Rhosaelwydfc(x) -> FootballClub(x) & Welsh(x))`

### restrictor_structure_diff (8 cases)

- **P0663**: Tower A is neither a building in New Haven nor a skyscraper in Manhattan....
  - SIV: `-((BuildingIn(towerA, newHaven) | SkyscraperIn(towerA, manhattan)))`
  - Gold: `Buildings(towerA) & (-InNewHaven(towerA)) & (-ManhattanSkyscraper(towe`
- **P0352**: All of this brand's products produced in the US are sold in the US....
  - SIV: `all x.((ProductOfBrand(x) & ProducedIn(x, us)) -> SoldIn(x, us))`
  - Gold: `all x ((ThisBrand(x) & Product(x) & ProducedIn(x, us)) -> SoldIn(x, us`
- **P1382**: None of the easy Leetcode problems have an AC rate lower than 20 percent....
  - SIV: `all x.(EasyLeetcodeProblem(x) -> -ACRateLowerThan20Percent(x))`
  - Gold: `all x ((LeetcodeProblems(x) & Easy(x)) -> -HaveAnACRateLowerThan(x, pe`
