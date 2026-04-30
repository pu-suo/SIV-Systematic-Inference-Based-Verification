# SIV vs FOLIO Gold Extraction Comparison

## P0302 (story 200, S2_universal_simple)

**NL**: Pre-recorded content is a copyright violation.

**SIV canonical**:
```
CopyrightViolation(x)
```

**FOLIO gold**:
```
∀x (Prerecorded(x) → CopyrightViolation(x))
```

**Tentative category**: `quantifier_scope_diff` + `connective_diff`

**Auto-detected differences**:

- Predicate counts: SIV=1, gold=2

- Gold-only predicates: Prerecorded/1


**Linguistic argument**: _to be filled by reviewer_

---

## P0096 (story 346, S2_universal_simple)

**NL**: All Nobel physics laureates are full-time scientists.

**SIV canonical**:
```
all x.(NobelPhysicsLaureate(x) -> FullTimeScientist(x))
```

**FOLIO gold**:
```
∀x (NobelPhysicsLaureate(x) → FullTimeScientist(x))
```

**Tentative category**: `vocabulary_only`

**Auto-detected differences**:

- Predicate counts: SIV=2, gold=2


**Linguistic argument**: _to be filled by reviewer_

---

## P0786 (story 207, S1_atomic)

**NL**: TOra is under the GNU General Public License.

**SIV canonical**:
```
UnderLicense(tOra, gnuGeneralPublicLicense)
```

**FOLIO gold**:
```
UnderGNULicense(tora)
```

**Tentative category**: `vocabulary_only`

**Auto-detected differences**:

- Predicate counts: SIV=1, gold=1

- SIV-only predicates: UnderLicense/2

- Gold-only predicates: UnderGNULicense/1

- SIV-only constants: gnuGeneralPublicLicense, tOra

- Gold-only constants: tora


**Linguistic argument**: _to be filled by reviewer_

---

## P0719 (story 302, S2_universal_simple)

**NL**: Everything that requires talent requires practice.

**SIV canonical**:
```
all x.(Requires(x, talent) -> Requires(x, practice))
```

**FOLIO gold**:
```
∀x (Require(x, talent) → Require(x, practice))
```

**Tentative category**: `vocabulary_only`

**Auto-detected differences**:

- Predicate counts: SIV=1, gold=1

- SIV-only predicates: Requires/2

- Gold-only predicates: Require/2


**Linguistic argument**: _to be filled by reviewer_

---

## P0663 (story 433, S1_atomic)

**NL**: Tower A is neither a building in New Haven nor a skyscraper in Manhattan.

**SIV canonical**:
```
-((BuildingIn(towerA, newHaven) | SkyscraperIn(towerA, manhattan)))
```

**FOLIO gold**:
```
Buildings(towerA) ∧ (¬InNewHaven(towerA)) ∧ (¬ManhattanSkyscraper(towerA))
```

**Tentative category**: `restrictor_structure_diff`

**Auto-detected differences**:

- Predicate counts: SIV=2, gold=3

- SIV-only predicates: BuildingIn/2, SkyscraperIn/2

- Gold-only predicates: Buildings/1, InNewHaven/1, ManhattanSkyscraper/1

- SIV-only constants: manhattan, newHaven


**Linguistic argument**: _to be filled by reviewer_

---

## P0394 (story 476, S2_universal_simple)

**NL**: All wage earners are human.

**SIV canonical**:
```
all x.(WageEarner(x) -> Human(x))
```

**FOLIO gold**:
```
∀x (WageEarner(x) → Human(x))
```

**Tentative category**: `vocabulary_only`

**Auto-detected differences**:

- Predicate counts: SIV=2, gold=2


**Linguistic argument**: _to be filled by reviewer_

---

## P0282 (story 474, S2_universal_simple)

**NL**: All humans are capable of abstract thoughts.

**SIV canonical**:
```
all x.(Human(x) -> CapableOfAbstractThoughts(x))
```

**FOLIO gold**:
```
∀x (Human(x) → CapableOf(x, abstractThought))
```

**Tentative category**: `vocabulary_only`

**Auto-detected differences**:

- Predicate counts: SIV=2, gold=2

- SIV-only predicates: CapableOfAbstractThoughts/1

- Gold-only predicates: CapableOf/2

- Gold-only constants: abstractThought


**Linguistic argument**: _to be filled by reviewer_

---

## P1621 (story 396, S2_universal_simple)

**NL**: A neuroimaging technique is either an invasive neuroimaging technique or a noninvasive neuroimaging technique.

**SIV canonical**:
```
exists x.(NeuroimagingTechnique(x) & (InvasiveNeuroimagingTechnique(x) | NoninvasiveNeuroimagingTechnique(x)))
```

**FOLIO gold**:
```
∀x (NeuroimagingTechnique(x) → (Invasive(x) ⊕ Noninvasive(x)))
```

**Tentative category**: `quantifier_scope_diff` + `connective_diff`

**Auto-detected differences**:

- Predicate counts: SIV=3, gold=3

- SIV-only predicates: InvasiveNeuroimagingTechnique/1, NoninvasiveNeuroimagingTechnique/1

- Gold-only predicates: Invasive/1, Noninvasive/1


**Linguistic argument**: _to be filled by reviewer_

---

## P0249 (story 484, S2_universal_simple)

**NL**: All sci-fi movies are movies.

**SIV canonical**:
```
all x.(SciFiMovie(x) -> Movie(x))
```

**FOLIO gold**:
```
∀x (ScifiMovie(x) → Movie(x))
```

**Tentative category**: `vocabulary_only`

**Auto-detected differences**:

- Predicate counts: SIV=2, gold=2

- SIV-only predicates: SciFiMovie/1

- Gold-only predicates: ScifiMovie/1


**Linguistic argument**: _to be filled by reviewer_

---

## P1261 (story 224, S2_universal_simple)

**NL**: Rhos Aelwyd F.C. is a Welsh football club.

**SIV canonical**:
```
WelshFootballClub(rhosAelwydFc)
```

**FOLIO gold**:
```
∀x (Rhosaelwydfc(x) → FootballClub(x) ∧ Welsh(x))
```

**Tentative category**: `quantifier_scope_diff` + `connective_diff`

**Auto-detected differences**:

- Predicate counts: SIV=1, gold=3

- SIV-only predicates: WelshFootballClub/1

- Gold-only predicates: FootballClub/1, Rhosaelwydfc/1, Welsh/1

- SIV-only constants: rhosAelwydFc


**Linguistic argument**: _to be filled by reviewer_

---

## P0118 (story 264, S2_universal_simple)

**NL**: All certified public accountants have good business sense.

**SIV canonical**:
```
all x.(CertifiedPublicAccountant(x) -> GoodBusinessSense(x))
```

**FOLIO gold**:
```
∀x (CertifiedPublicAccoutant(x) → Have(x, goodBusinessSense))
```

**Tentative category**: `vocabulary_only`

**Auto-detected differences**:

- Predicate counts: SIV=2, gold=2

- SIV-only predicates: CertifiedPublicAccountant/1, GoodBusinessSense/1

- Gold-only predicates: CertifiedPublicAccoutant/1, Have/2

- Gold-only constants: goodBusinessSense


**Linguistic argument**: _to be filled by reviewer_

---

## P0111 (story 423, S2_universal_simple)

**NL**: Everyone at the business conference is either an investor or an entrepreneur.

**SIV canonical**:
```
all x.(At(x, businessConference) -> (Investor(x) | Entrepreneur(x)))
```

**FOLIO gold**:
```
∀x (At(x, businessConference) → (Investor(x) ⊕ Entrepreneur(x)))
```

**Tentative category**: `vocabulary_only`

**Auto-detected differences**:

- Predicate counts: SIV=3, gold=3


**Linguistic argument**: _to be filled by reviewer_

---

## P0257 (story 393, S1_atomic)

**NL**: Modus Ponens is a component of a major part of reasoning rule.

**SIV canonical**:
```
exists x.(exists y.((MajorPartOf(x, y) & ReasoningRule(y))) & ComponentOf(modusPonens, x))
```

**FOLIO gold**:
```
ArgumentForm(modusPonens)
```

**Tentative category**: `quantifier_scope_diff`

**Auto-detected differences**:

- Predicate counts: SIV=3, gold=1

- SIV-only predicates: ComponentOf/2, MajorPartOf/2, ReasoningRule/1

- Gold-only predicates: ArgumentForm/1


**Linguistic argument**: _to be filled by reviewer_

---

## P0639 (story 288, S2_universal_simple)

**NL**: Tissues are soft.

**SIV canonical**:
```
all x.(Tissue(x) -> Soft(x))
```

**FOLIO gold**:
```
∀x (Tissue(x) → Soft(x))
```

**Tentative category**: `vocabulary_only`

**Auto-detected differences**:

- Predicate counts: SIV=2, gold=2


**Linguistic argument**: _to be filled by reviewer_

---

## P0689 (story 465, S2_universal_simple)

**NL**: Everyone who took the bar exam is knowledgeable about criminal procedures.

**SIV canonical**:
```
None
```

**FOLIO gold**:
```
∀x (Take(x, barExam) → KnowledgeableAbout(x, criminalProceeder))
```

**Tentative category**: `extraction_failure`

**Auto-detected differences**:

- Predicate counts: SIV=0, gold=0


**Linguistic argument**: _to be filled by reviewer_

---

## P0965 (story 415, S4_nested_quantifier)

**NL**: All books written by Neil Gaiman have sold more than one thousand copies.

**SIV canonical**:
```
all x.((Book(x) & WrittenBy(x, neilGaiman)) -> SoldMoreThanOneThousandCopies(x))
```

**FOLIO gold**:
```
∀x ((Book(x) ∧ WrittenBy(x, neilGaiman)) → ∃y (MoreThan(y, num1000) ∧ SoldCopies(x, y)))
```

**Tentative category**: `compound_vs_decomposed` + `const_vs_pred_asymmetry`, `quantifier_scope_diff`

**Auto-detected differences**:

- Predicate counts: SIV=3, gold=4

- SIV-only predicates: SoldMoreThanOneThousandCopies/1

- Gold-only predicates: MoreThan/2, SoldCopies/2

- Gold-only constants: num1000


**Linguistic argument**: _to be filled by reviewer_

---

## P1150 (story 274, S4_nested_quantifier)

**NL**: If a European plays football, they play what Americans call soccer.

**SIV canonical**:
```
all x.(European(x) -> (exists y.(Football(y) & Plays(x, y)) -> exists z.(Soccer(z) & Plays(x, z))))
```

**FOLIO gold**:
```
∀x (FootballPlayer(x) ∧ European(x) → ∃y (Call(american, y, soccer) ∧ Play(x, y)))
```

**Tentative category**: `const_vs_pred_asymmetry` + `quantifier_scope_diff`, `connective_diff`

**Auto-detected differences**:

- Predicate counts: SIV=4, gold=4

- SIV-only predicates: Football/1, Plays/2, Soccer/1

- Gold-only predicates: Call/3, FootballPlayer/1, Play/2

- Gold-only constants: american, soccer


**Linguistic argument**: _to be filled by reviewer_

---

## P0055 (story 417, S3_universal_multi_restrictor)

**NL**: All monitors in the library are made before 2010.

**SIV canonical**:
```
all x.((Monitor(x) & In(x, library)) -> MadeBefore2010(x))
```

**FOLIO gold**:
```
∀x ((Monitor(x) ∧ In(x, library)) → ProducedBefore(x, yr2010))
```

**Tentative category**: `vocabulary_only`

**Auto-detected differences**:

- Predicate counts: SIV=3, gold=3

- SIV-only predicates: MadeBefore2010/1

- Gold-only predicates: ProducedBefore/2

- Gold-only constants: yr2010


**Linguistic argument**: _to be filled by reviewer_

---

## P1041 (story 370, S4_nested_quantifier)

**NL**: If Robin's friends study hard, then they grew up with parents who worked as doctors.

**SIV canonical**:
```
None
```

**FOLIO gold**:
```
∀x (RobinsFriends(x) ∧ StudyHard(x) → ∃y ∃z (¬(y=z) ∧ GrowUpWith(x, y) ∧ GrowUpWith(x, z) ∧ ParentOf(y, x) ∧ ParentOf(z, x) ∧ Doctor(y) ∧ Doctor(z)))
```

**Tentative category**: `extraction_failure`

**Auto-detected differences**:

- Predicate counts: SIV=0, gold=0


**Linguistic argument**: _to be filled by reviewer_

---

## P0352 (story 436, S3_universal_multi_restrictor)

**NL**: All of this brand's products produced in the US are sold in the US.

**SIV canonical**:
```
all x.((ProductOfBrand(x) & ProducedIn(x, us)) -> SoldIn(x, us))
```

**FOLIO gold**:
```
∀x ((ThisBrand(x) ∧ Product(x) ∧ ProducedIn(x, us)) → SoldIn(x, us))
```

**Tentative category**: `restrictor_structure_diff`

**Auto-detected differences**:

- Predicate counts: SIV=3, gold=4

- SIV-only predicates: ProductOfBrand/1

- Gold-only predicates: Product/1, ThisBrand/1


**Linguistic argument**: _to be filled by reviewer_

---

## P1382 (story 429, S3_universal_multi_restrictor)

**NL**: None of the easy Leetcode problems have an AC rate lower than 20 percent.

**SIV canonical**:
```
all x.(EasyLeetcodeProblem(x) -> -ACRateLowerThan20Percent(x))
```

**FOLIO gold**:
```
∀x ((LeetcodeProblems(x) ∧ Easy(x)) → ¬HaveAnACRateLowerThan(x, percent20))
```

**Tentative category**: `restrictor_structure_diff`

**Auto-detected differences**:

- Predicate counts: SIV=2, gold=3

- SIV-only predicates: ACRateLowerThan20Percent/1, EasyLeetcodeProblem/1

- Gold-only predicates: Easy/1, HaveAnACRateLowerThan/2, LeetcodeProblems/1

- Gold-only constants: percent20


**Linguistic argument**: _to be filled by reviewer_

---

## P1250 (story 125, S3_universal_multi_restrictor)

**NL**: Top soccer players are soccer players who can use both the left foot and right foot very efficiently.

**SIV canonical**:
```
all x.(TopSoccerPlayer(x) -> (SoccerPlayer(x) & exists y.(LeftFoot(y) & CanUseEfficiently(x, y)) & exists z.(RightFoot(z) & CanUseEfficiently(x, z))))
```

**FOLIO gold**:
```
∀x (SoccerPlayer(x) ∧ UseEfficiently(x, leftFoot) ∧ UseEfficiently(x, rightFoot) → TopSoccerPlayer(x))
```

**Tentative category**: `const_vs_pred_asymmetry` + `quantifier_scope_diff`

**Auto-detected differences**:

- Predicate counts: SIV=5, gold=3

- SIV-only predicates: CanUseEfficiently/2, LeftFoot/1, RightFoot/1

- Gold-only predicates: UseEfficiently/2

- Gold-only constants: leftFoot, rightFoot


**Linguistic argument**: _to be filled by reviewer_

---

## P1354 (story 76, S3_universal_multi_restrictor)

**NL**: People born and living in New York City are New Yorkers.

**SIV canonical**:
```
all x.((Person(x) & BornIn(x, newYorkCity) & LiveIn(x, newYorkCity)) -> NewYorker(x))
```

**FOLIO gold**:
```
∀x ((BornIn(x, newYorkCity) ∧ LiveIn(x, newYorkCity)) → NewYorker(x))
```

**Tentative category**: `restrictor_structure_diff`

**Auto-detected differences**:

- Predicate counts: SIV=4, gold=3

- SIV-only predicates: Person/1


**Linguistic argument**: _to be filled by reviewer_

---

## P1025 (story 188, S4_nested_quantifier)

**NL**: If two soccer teams score the same number of goals in one UCL final during both regular and extra time, they need to play the penalty shoot-out.

**SIV canonical**:
```
None
```

**FOLIO gold**:
```
∀x ∀y (SoccerTeam(x) ∧ SoccerTeam(y) ∧ SameScore(x, y) ∧ During(regularTime) ∧ During(extraTime) → PlayPenalty(x, y))
```

**Tentative category**: `extraction_failure`

**Auto-detected differences**:

- Predicate counts: SIV=0, gold=0


**Linguistic argument**: _to be filled by reviewer_

---

## P0795 (story 173, S3_universal_multi_restrictor)

**NL**: If a horse falls in a race, it poses risks to its rider.

**SIV canonical**:
```
all x.(Horse(x) -> exists y.((Race(y) & FallsIn(x, y)) & exists z.(RiderOf(z, x) & PosesRisksTo(x, z))))
```

**FOLIO gold**:
```
∀x (Horse(x) ∧ InRace(x) ∧ Falls(x) → PoseRiskTo(x, rider))
```

**Tentative category**: `compound_vs_decomposed` + `quantifier_scope_diff`

**Auto-detected differences**:

- Predicate counts: SIV=5, gold=4

- SIV-only predicates: FallsIn/2, PosesRisksTo/2, Race/1, RiderOf/2

- Gold-only predicates: Falls/1, InRace/1, PoseRiskTo/2

- Gold-only constants: rider


**Linguistic argument**: _to be filled by reviewer_

---

## P0378 (story 243, S4_nested_quantifier)

**NL**: If the meal is popular at the party, then it is delicious.

**SIV canonical**:
```
(PopularAt(theMeal, theParty) -> Delicious(theMeal))
```

**FOLIO gold**:
```
∀x ∀y (Meal(y) ∧ PopularAt(y, party) → Delicious(y))
```

**Tentative category**: `quantifier_scope_diff`

**Auto-detected differences**:

- Predicate counts: SIV=2, gold=3

- Gold-only predicates: Meal/1

- SIV-only constants: theMeal, theParty

- Gold-only constants: party


**Linguistic argument**: _to be filled by reviewer_

---

## P0861 (story 412, S4_nested_quantifier)

**NL**: Some fruits sold in New Haven are shipped from Mexico.

**SIV canonical**:
```
exists x.((Fruit(x) & SoldIn(x, newHaven)) & ShippedFrom(x, mexico))
```

**FOLIO gold**:
```
∃x ∃y (Fruit(x) ∧ SoldIn(x, newHaven) ∧ ShippedFrom(x, mexico) ∧ (¬(x=y)) ∧ Fruit(y) ∧ SoldIn(y, newHaven) ∧ ShippedFrom(y, mexico))
```

**Tentative category**: `quantifier_scope_diff`

**Auto-detected differences**:

- Predicate counts: SIV=3, gold=3


**Linguistic argument**: _to be filled by reviewer_

---

## P1106 (story 450, S3_universal_multi_restrictor)

**NL**: Flightless birds cannot fly over a vast distance.

**SIV canonical**:
```
all x.(FlightlessBird(x) -> -(FlyOver(x, distance)))
```

**FOLIO gold**:
```
∀x (Flightless(x) ∧ Bird(x) → ¬FlyOver(x, vastDistance))
```

**Tentative category**: `restrictor_structure_diff`

**Auto-detected differences**:

- Predicate counts: SIV=2, gold=3

- SIV-only predicates: FlightlessBird/1

- Gold-only predicates: Bird/1, Flightless/1

- SIV-only constants: distance

- Gold-only constants: vastDistance


**Linguistic argument**: _to be filled by reviewer_

---

## P0528 (story 399, S3_universal_multi_restrictor)

**NL**: If someone in Love City is good with pets, then they are not scared of animals.

**SIV canonical**:
```
None
```

**FOLIO gold**:
```
∀x ((GoodWith(x, pet) ∧ In(x, loveCity)) → ¬ScaredOf(x, animal))
```

**Tentative category**: `extraction_failure`

**Auto-detected differences**:

- Predicate counts: SIV=0, gold=0


**Linguistic argument**: _to be filled by reviewer_

---

## P1563 (story 175, S4_nested_quantifier)

**NL**: If someone has been scratched or bitten by some entity, they have been attacked by that entity.

**SIV canonical**:
```
None
```

**FOLIO gold**:
```
∀x ∃y (BittenBy(x, y) ∨ ScratchedBy(x, y)) → AttackedBy(x,y)
```

**Tentative category**: `extraction_failure`

**Auto-detected differences**:

- Predicate counts: SIV=0, gold=0


**Linguistic argument**: _to be filled by reviewer_

---

## P0030 (story 422, S3_universal_multi_restrictor)

**NL**: All customers in James' family who subscribe to AMC A-List are eligible to watch three movies every week without any additional fees.

**SIV canonical**:
```
all x.((Customer(x) & InFamily(x, james) & SubscribeTo(x, amcAList)) -> all y.(Movie(y) -> EligibleToWatch(x, y)))
```

**FOLIO gold**:
```
∀x ((Customer(x) ∧ In(x, jameSFamily) ∧ SubscribedTo(x, aMCAList)) →  EligibleForThreeFreeMoviesEveryWeekWithoutAdditionalFees(x))
```

**Tentative category**: `quantifier_scope_diff` + `connective_diff`

**Auto-detected differences**:

- Predicate counts: SIV=5, gold=4

- SIV-only predicates: EligibleToWatch/2, InFamily/2, Movie/1, SubscribeTo/2

- Gold-only predicates: EligibleForThreeFreeMoviesEveryWeekWithoutAdditionalFees/1, In/2, SubscribedTo/2

- SIV-only constants: amcAList, james

- Gold-only constants: aMCAList, jameSFamily


**Linguistic argument**: _to be filled by reviewer_

---

## P1465 (story 316, S3_universal_multi_restrictor)

**NL**: Every terrifying building on Halloween is a creepy haunted house.

**SIV canonical**:
```
all x.((Terrifying(x) & Building(x) & OnHalloween(x)) -> CreepyHauntedHouse(x))
```

**FOLIO gold**:
```
∀x (TerrifyingBuilding(x) ∧ OnHalloween(x) → CreepyHauntedHouse(x))
```

**Tentative category**: `restrictor_structure_diff`

**Auto-detected differences**:

- Predicate counts: SIV=4, gold=3

- SIV-only predicates: Building/1, Terrifying/1

- Gold-only predicates: TerrifyingBuilding/1


**Linguistic argument**: _to be filled by reviewer_

---

## P1561 (story 175, S3_universal_multi_restrictor)

**NL**: A werewolf is a human that can turn into a wolf.

**SIV canonical**:
```
all x.(Werewolf(x) -> exists y.((Human(x) & Wolf(y)) & CanTurnInto(x, y)))
```

**FOLIO gold**:
```
∀x (Human(x) ∧ CanTurnInto(x, wolf) → Werewolf(x))
```

**Tentative category**: `const_vs_pred_asymmetry` + `quantifier_scope_diff`

**Auto-detected differences**:

- Predicate counts: SIV=4, gold=3

- SIV-only predicates: Wolf/1

- Gold-only constants: wolf


**Linguistic argument**: _to be filled by reviewer_

---

## P0298 (story 321, S4_nested_quantifier)

**NL**: All working people who hate working for others want to be entrepreneurs.

**SIV canonical**:
```
all x.((Working(x) & HateWorkingForOthers(x)) -> WantToBeEntrepreneur(x))
```

**FOLIO gold**:
```
∀x (∃y ∃z (¬(y=x) ∧ ¬(z=x) ∧ ¬(y=z) ∧ HateWorkingFor(x, y) ∧ HateWorkingFor(x, z)) → Entrepreneur(x))
```

**Tentative category**: `quantifier_scope_diff`

**Auto-detected differences**:

- Predicate counts: SIV=3, gold=2

- SIV-only predicates: HateWorkingForOthers/1, WantToBeEntrepreneur/1, Working/1

- Gold-only predicates: Entrepreneur/1, HateWorkingFor/2


**Linguistic argument**: _to be filled by reviewer_

---

## P1339 (story 167, S3_universal_multi_restrictor)

**NL**: If you go somewhere by car and meet a traffic jam, you will lose time.

**SIV canonical**:
```
None
```

**FOLIO gold**:
```
∀x((GoByCar(x) ∧ Meet(x, trafficJam)) → LoseTime(x))
```

**Tentative category**: `extraction_failure`

**Auto-detected differences**:

- Predicate counts: SIV=0, gold=0


**Linguistic argument**: _to be filled by reviewer_

---

## P0983 (story 218, S5_relational)

**NL**: Maya would only play the violin if her fingers could never be injured.

**SIV canonical**:
```
(PlayViolin(maya) -> -FingersInjured(mayaFingers))
```

**FOLIO gold**:
```
Play(maya, violin) → ¬CanInjure(maya, fingers)
```

**Tentative category**: `vocabulary_only`

**Auto-detected differences**:

- Predicate counts: SIV=2, gold=2

- SIV-only predicates: FingersInjured/1, PlayViolin/1

- Gold-only predicates: CanInjure/2, Play/2

- SIV-only constants: mayaFingers

- Gold-only constants: fingers, violin


**Linguistic argument**: _to be filled by reviewer_

---

## P0841 (story 66, S5_relational)

**NL**: Atlanta is in Georgia.

**SIV canonical**:
```
In(atlanta, georgia)
```

**FOLIO gold**:
```
In(california, unitedStates)
```

**Tentative category**: `vocabulary_only`

**Auto-detected differences**:

- Predicate counts: SIV=1, gold=1

- SIV-only constants: atlanta, georgia

- Gold-only constants: california, unitedStates


**Linguistic argument**: _to be filled by reviewer_

---

## P0599 (story 344, S5_relational)

**NL**: If John is not a PhD student, then he is not a member of the university.

**SIV canonical**:
```
(-PhDStudent(john) -> -MemberOf(john, university))
```

**FOLIO gold**:
```
¬PhDStudent(john) → ¬MemberOf(john, university)
```

**Tentative category**: `vocabulary_only`

**Auto-detected differences**:

- Predicate counts: SIV=2, gold=2


**Linguistic argument**: _to be filled by reviewer_

---

## P0341 (story 407, S5_relational)

**NL**: Ryan is performing at New Haven Symphony Orchestra.

**SIV canonical**:
```
PerformAt(ryan, newHavenSymphonyOrchestra)
```

**FOLIO gold**:
```
PerformAt(ryan, newHavenSymphonyOrchestra)
```

**Tentative category**: `exact_match`

**Auto-detected differences**:

- Predicate counts: SIV=1, gold=1


**Linguistic argument**: _to be filled by reviewer_

---

## P0490 (story 238, S5_relational)

**NL**: Daniel studied bioengineering during his undergraduate at Rice University.

**SIV canonical**:
```
None
```

**FOLIO gold**:
```
Studied(daniel, bioengineering) ∧ UndergraduateAt(daniel, riceUniversity)
```

**Tentative category**: `extraction_failure`

**Auto-detected differences**:

- Predicate counts: SIV=0, gold=0


**Linguistic argument**: _to be filled by reviewer_

---

## P0839 (story 66, S5_relational)

**NL**: Los Angeles is a city in California.

**SIV canonical**:
```
(City(losAngeles) & In(losAngeles, california))
```

**FOLIO gold**:
```
In(losAngeles, california)
```

**Tentative category**: `restrictor_structure_diff`

**Auto-detected differences**:

- Predicate counts: SIV=2, gold=1

- SIV-only predicates: City/1


**Linguistic argument**: _to be filled by reviewer_

---

## P0239 (story 3, S5_relational)

**NL**: Fort Carillon was located in New France.

**SIV canonical**:
```
LocatedIn(fortCarillon, newFrance)
```

**FOLIO gold**:
```
LocatedIn(fortCarillon, newFrance)
```

**Tentative category**: `exact_match`

**Auto-detected differences**:

- Predicate counts: SIV=1, gold=1


**Linguistic argument**: _to be filled by reviewer_

---

## P0228 (story 73, S5_relational)

**NL**: Mongolia was where Ambiortus Dementjevi lived.

**SIV canonical**:
```
LivedIn(ambiortusDementjevi, mongolia)
```

**FOLIO gold**:
```
LiveIn(ambiortusDementjevi, mongolia)
```

**Tentative category**: `vocabulary_only`

**Auto-detected differences**:

- Predicate counts: SIV=1, gold=1

- SIV-only predicates: LivedIn/2

- Gold-only predicates: LiveIn/2


**Linguistic argument**: _to be filled by reviewer_

---

## P0899 (story 32, S5_relational)

**NL**: Hugh Vanstone is from the UK.

**SIV canonical**:
```
From(hughVanstone, uk)
```

**FOLIO gold**:
```
From(hughVanstone, unitedKingdom)
```

**Tentative category**: `vocabulary_only`

**Auto-detected differences**:

- Predicate counts: SIV=1, gold=1

- SIV-only constants: uk

- Gold-only constants: unitedKingdom


**Linguistic argument**: _to be filled by reviewer_

---

## P0236 (story 448, S5_relational)

**NL**: Jack is entitled to the right to life and liberty, has human rights, or knows about the first-in-first-out data structure.

**SIV canonical**:
```
(EntitledToRightToLifeAndLiberty(jack) | HasHumanRights(jack) | KnowsAboutFIFODataStructure(jack))
```

**FOLIO gold**:
```
(EntitledTo(jack, rightToLifeAndLiberty) ∨ Have(jack, humanRights) ∨ Know(jack, firstInFirstOutDataStructure))
```

**Tentative category**: `vocabulary_only`

**Auto-detected differences**:

- Predicate counts: SIV=3, gold=3

- SIV-only predicates: EntitledToRightToLifeAndLiberty/1, HasHumanRights/1, KnowsAboutFIFODataStructure/1

- Gold-only predicates: EntitledTo/2, Have/2, Know/2

- Gold-only constants: firstInFirstOutDataStructure, humanRights, rightToLifeAndLiberty


**Linguistic argument**: _to be filled by reviewer_

---

## P1086 (story 390, S6_negation)

**NL**: Lithium is either a non-rare earth element and essential for exploring future directions of electronics, or is not a non-rare earth element and is not essential for exploring future directions of electronics.

**SIV canonical**:
```
((NonRareEarthElement(lithium) & EssentialForExploringFutureDirectionsOfElectronics(lithium)) | (-NonRareEarthElement(lithium) & -EssentialForExploringFutureDirectionsOfElectronics(lithium)))
```

**FOLIO gold**:
```
¬(¬RareEarthElement(lithium) ⊕ EssentialFor(lithium, electronics))
```

**Tentative category**: `vocabulary_only`

**Auto-detected differences**:

- Predicate counts: SIV=2, gold=2

- SIV-only predicates: EssentialForExploringFutureDirectionsOfElectronics/1, NonRareEarthElement/1

- Gold-only predicates: EssentialFor/2, RareEarthElement/1

- Gold-only constants: electronics


**Linguistic argument**: _to be filled by reviewer_

---

## P1056 (story 5, S8_other)

**NL**: Peter Parker is either a superhero or a civilian.

**SIV canonical**:
```
(Superhero(peterParker) | Civilian(peterParker))
```

**FOLIO gold**:
```
Superhero(peterParker) ⊕ Civilian(peterParker)
```

**Tentative category**: `vocabulary_only`

**Auto-detected differences**:

- Predicate counts: SIV=2, gold=2


**Linguistic argument**: _to be filled by reviewer_

---

## P0792 (story 424, S6_negation)

**NL**: James is a customer who is not between the ages of 60 and 80.

**SIV canonical**:
```
(Customer(james) & -AgeBetween60And80(james))
```

**FOLIO gold**:
```
Customer(james) ∧ (¬∃y(Between(y, num60, num80) ∧ Age(james, y)))
```

**Tentative category**: `compound_vs_decomposed` + `const_vs_pred_asymmetry`, `quantifier_scope_diff`

**Auto-detected differences**:

- Predicate counts: SIV=2, gold=3

- SIV-only predicates: AgeBetween60And80/1

- Gold-only predicates: Age/2, Between/3

- Gold-only constants: num60, num80


**Linguistic argument**: _to be filled by reviewer_

---

## P0137 (story 378, unparseable)

**NL**: All people who attend weddings are getting married or know the people who are getting married.

**SIV canonical**:
```
all x.(exists y.((Person(x) & Attend(x, y) & Wedding(y))) -> (GettingMarried(x) | exists z.(GettingMarried(z) & Know(x, z))))
```

**FOLIO gold**:
```
∀x (Attend(x, wedding) → GettingMarried(x) ∨ (∃y (Know(x, y) ∧ GettingMarried(y)))
```

**Tentative category**: `const_vs_pred_asymmetry` + `quantifier_scope_diff`

**Auto-detected differences**:

- Predicate counts: SIV=5, gold=3

- SIV-only predicates: Person/1, Wedding/1

- Gold-only constants: wedding


**Linguistic argument**: _to be filled by reviewer_

---

## P1373 (story 325, unparseable)

**NL**: All professional centerbacks are professional soccer defenders.

**SIV canonical**:
```
all x.(ProfessionalCenterback(x) -> ProfessionalSoccerDefender(x))
```

**FOLIO gold**:
```
∀x ((Professional(x) ∧ CenterBack(x)) → (Professional(x) ∧ Defender(x))
```

**Tentative category**: `restrictor_structure_diff`

**Auto-detected differences**:

- Predicate counts: SIV=2, gold=3

- SIV-only predicates: ProfessionalCenterback/1, ProfessionalSoccerDefender/1

- Gold-only predicates: CenterBack/1, Defender/1, Professional/1


**Linguistic argument**: _to be filled by reviewer_

---
