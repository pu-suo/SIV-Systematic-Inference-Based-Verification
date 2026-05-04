# Hand-authored corrections for Experiment 3

Author: Tom (project lead)
Date: 2026-05-01
Total: 30 premises

For each premise: c_correct_fol is a faithful translation of the NL using FOL
syntax compatible with siv.fol_utils.parse_fol (ASCII operators: all, exists,
->, &, |, <->, -). Rationales are one sentence. Introduced predicates are
listed where the gold's vocabulary did not provide a needed name; in most
cases gold's predicates are reused.

---

## P1332

NL: "In some families, Odell is spelled O'Dell in a mistaken Irish adaptation."

Gold FOL (broken): MistakenSpellingOf(nameO'Dell, nameODell) ∧ (∃x∃y(Family(x) ∧ Named(x, nameO'Dell) ∧ (¬(x=y)) ∧ Family(y) ∧ Named(y, nameO'Dell))

Broken reason: syntax_error
Broken evidence: apostrophe in constant name nameO'Dell, unbalanced parens, redundant inequality

### Your correction:
c_correct_fol: MistakenSpellingOf(nameOdell, nameOdellOriginal) & exists x.(Family(x) & UsesName(x, nameOdell))
rationale: Removes apostrophe-bearing identifiers, drops the spurious second-witness existential, and keeps the two NL claims (the spelling relation and the existence of at least one such family).
introduced_predicates: UsesName/2 (gold used Named/2; renamed for clarity, equivalent)

---

## P1326

NL: "Some Whigs speak French."

Gold FOL (broken): ∃x ∃y (Whig(x) ∧ SpeakFrench(x)) ∧ (¬(x=y)) ∧ (Whig(y) ∧ SpeakFrench(y))

Broken reason: free_variable
Broken evidence: free individual variables x, y because conjunction scopes leak outside the existential body

### Your correction:
c_correct_fol: exists x.(Whig(x) & SpeakFrench(x))
rationale: NL says "some" (at least one), not "at least two distinct"; gold over-specifies and then leaks variables; the simple existential is the faithful reading.
introduced_predicates: none

---

## P1414

NL: "Some singles of Imagine Dragons have been on Billboard Hot 100."

Gold FOL (broken): ∃x ∃y (PopularSingle(imagineDragon, x) ∧ BillboardHot100(x)) ∧ (¬(x=y)) ∧ (PopularSingle(imagineDragon, y) ∧ BillboardHot100(y))

Broken reason: free_variable
Broken evidence: free x, y from existential-scope leakage; same pattern as P1326

### Your correction:
c_correct_fol: exists x.(PopularSingle(imagineDragons, x) & BillboardHot100(x))
rationale: "Some" maps to at-least-one; gold's two-witness encoding is unjustified and structurally broken.
introduced_predicates: none

---

## P1542

NL: "Quincy McDuffie can catch some footballs easily."

Gold FOL (broken): ∃x ∃y (Football(x) ∧ CanCatch(quincymcduffie, x)) ∧ (¬(x=y) ∧ (Football(y) ∧ CanCatch(quincymcduffie, y))

Broken reason: syntax_error
Broken evidence: unbalanced parens, two-witness pattern same as P1326/P1414, "easily" not represented

### Your correction:
c_correct_fol: exists x.(Football(x) & CanCatchEasily(quincymcduffie, x))
rationale: "Some footballs easily" is a single existential with the manner adverb folded into the predicate; preserves NL's commitment that there exists at least one such football.
introduced_predicates: CanCatchEasily/2 (gold's CanCatch lost the "easily" modifier)

---

## P1223

NL: "Shafaq-Asiman is a large complex of offshore geological structures in the Caspian Sea."

Gold FOL (broken): LargeComplex(shafaq-asiman) ∧ LargeComplex(shafaq-asiman) ∧ Offshore(shafaq-asiman) ∧ GeologicalStructures(shafaq-asiman) ∧ In(shafaq-asiman, caspiansea)

Broken reason: syntax_error
Broken evidence: hyphen in constant shafaq-asiman; duplicate LargeComplex conjunct

### Your correction:
c_correct_fol: LargeComplex(shafaqAsiman) & Offshore(shafaqAsiman) & GeologicalStructures(shafaqAsiman) & In(shafaqAsiman, caspianSea)
rationale: Removes the hyphen, drops the duplicate, and keeps the four NL claims (complex-ness, offshore, structures, location).
introduced_predicates: none

---

## P1134

NL: "Palstaves are found in northern, western, and southwestern Europe and are cast in molds."

Gold FOL (broken): FoundIn(palstave, northernEurope) ∨ FoundIn(palstave, westernEurope) ∨ FoundIn(palstave, southWesternEurope)) ∧ CastIn(palstave, molds)

Broken reason: syntax_error
Broken evidence: unbalanced parens; also semantically wrong — gold uses disjunction where NL coordinates with "and"

### Your correction:
c_correct_fol: FoundIn(palstave, northernEurope) & FoundIn(palstave, westernEurope) & FoundIn(palstave, southwesternEurope) & CastIn(palstave, molds)
rationale: NL says found in all three regions ("northern, western, and southwestern"), not in one of them; conjunction is the faithful reading.
introduced_predicates: none

---

## P0017

NL: "The Emmet Building is a five-story building in Portland, Oregon."

Gold FOL (broken): Building(emmetBuilding) ∧ Five-Story(emmetBuilding) ∧ LocatedIn(emmetBuilding, portland) ∧ LocatedIn(portland, oregon))

Broken reason: syntax_error
Broken evidence: hyphen in predicate Five-Story; trailing unbalanced paren

### Your correction:
c_correct_fol: Building(emmetBuilding) & FiveStory(emmetBuilding) & LocatedIn(emmetBuilding, portland) & LocatedIn(portland, oregon)
rationale: Removes the hyphenated predicate (FiveStory in CamelCase) and the stray paren; same four claims as gold intended.
introduced_predicates: none

---

## P1638

NL: "TS Leda was a good passenger and cargo vessel."

Gold FOL (broken): ∀x (TSLeda(x) → ((Passenger(x) ∧ Vessel(x)) ∧ (Cargo(x) ∧ Vessel(x)))

Broken reason: syntax_error
Broken evidence: unbalanced parens; treating TSLeda as a unary predicate over x is also a misformalization (it's a specific ship)

### Your correction:
c_correct_fol: PassengerVessel(tsLeda) & CargoVessel(tsLeda) & Good(tsLeda)
rationale: TS Leda is a named ship (constant), not a kind; NL asserts three properties (passenger-vessel, cargo-vessel, good).
introduced_predicates: PassengerVessel/1, CargoVessel/1, Good/1 (gold's unary-on-x scheme was unrecoverable)

---

## P0437

NL: "Boney M. had several German #1 singles."

Gold FOL (broken): ∃x (Song(x) ∧ By(x, boneym,) ∧ Number1GermanSingle(x))

Broken reason: syntax_error
Broken evidence: trailing comma in By(x, boneym,)

### Your correction:
c_correct_fol: exists x.(Song(x) & By(x, boneyM) & Number1GermanSingle(x))
rationale: Removes the trailing comma and uses CamelCase constant; preserves the existential reading of "several" as at-least-one.
introduced_predicates: none

---

## P0671

NL: "Mr. Smith has been to two cities in California."

Gold FOL (broken): ∃x ∃y ∀z (¬(x=z) ∧ ¬(y=z) ∧ ¬(x=y) ∧ City(x) ∧ City(y) ∧ City(z) ∧ California(x) ∧ California(y) ∧ California(z) → Visit(mr.smith, x) ∧ Visit(mr.smith, y) ∧ ¬Visit(mr.smith, z))

Broken reason: syntax_error
Broken evidence: dot in mr.smith; the only-two semantics (the ∀z clause) is a tortured encoding of "exactly two" that NL does not assert

### Your correction:
c_correct_fol: exists x.exists y.(City(x) & InCalifornia(x) & City(y) & InCalifornia(y) & -(x=y) & Visit(mrSmith, x) & Visit(mrSmith, y))
rationale: NL says "has been to two cities" — at least two distinct California cities visited; "exactly two" is a stronger reading than NL warrants and gold's universal-z encoding is structurally broken anyway.
introduced_predicates: InCalifornia/1 (gold used California/1; renamed to make the relational reading explicit)

---

## P0766

NL: "There are five grades in English class: A+, A, B+, B, and C."

Gold FOL (broken): GradeIn(aPlus, englishClass) ∨ GradeIn(a, englishClass) ∨ GradeIn(bPlus, englishClass) ∨ GradeIn(b, englishClass) ∨ GradeIn(c, englishClass) ∧ ... [long mutual-exclusion chain]

Broken reason: free_variable
Broken evidence: free a, b, c — they look like variable names but are intended as grade constants; the disjunction-then-mutual-exclusion structure also misrepresents NL's plain enumeration

### Your correction:
c_correct_fol: GradeIn(gradeAplus, englishClass) & GradeIn(gradeA, englishClass) & GradeIn(gradeBplus, englishClass) & GradeIn(gradeB, englishClass) & GradeIn(gradeC, englishClass)
rationale: NL says all five grades exist in English class (a conjunctive enumeration), not a disjunction; renaming a, b, c to gradeA, gradeB, gradeC eliminates the free-variable bug.
introduced_predicates: none (renamed constants)

---

## P0768

NL: "If a student gets an A in English class, then his score is greater than 90 but lower than 95."

Gold FOL (broken): ∀x ∀y (Student(x) ∧ GetGradeIn(x, a, englishClass) → EnglishClassScore(x, y) ∧ GreaterThan90(y) ∧ LowerThan95(y))

Broken reason: free_variable
Broken evidence: free a — intended as grade constant gradeA but written as a bare lowercase letter

### Your correction:
c_correct_fol: all x.all y.((Student(x) & GetGradeIn(x, gradeA, englishClass) & EnglishClassScore(x, y)) -> (GreaterThan90(y) & LowerThan95(y)))
rationale: Renames the grade constant to gradeA (matching P0766/P0769) and moves EnglishClassScore into the antecedent so the consequent is the score-bound claim NL actually makes.
introduced_predicates: none

---

## P0769

NL: "Zhang got an A in English class."

Gold FOL (broken): Student(zhang) ∧ GetGradeIn(zhang, a, englishClass)

Broken reason: free_variable
Broken evidence: free a; intended as grade constant gradeA

### Your correction:
c_correct_fol: Student(zhang) & GetGradeIn(zhang, gradeA, englishClass)
rationale: Same fix as P0768 — rename the grade letter to a constant gradeA. The Student(zhang) conjunct is retained because P0768 makes student-hood a precondition for the score rule.
introduced_predicates: none

---

## P0190

NL: "Oliver plays a different musical instrument from Peter in the concert."

Gold FOL (broken): ∀x (PlayIn(oliver, x, concert) → ¬PlayIn(peter, y, concert))

Broken reason: free_variable
Broken evidence: free y; gold also misformalizes — the universal-implies-negation reading says Peter plays nothing in the concert, which is wrong

### Your correction:
c_correct_fol: exists x.exists y.(MusicalInstrument(x) & MusicalInstrument(y) & -(x=y) & PlayIn(oliver, x, concert) & PlayIn(peter, y, concert))
rationale: NL asserts both Oliver and Peter play, on different instruments; the existential-with-inequality is the standard "different X" pattern.
introduced_predicates: MusicalInstrument/1 (gold did not name the instrument-hood property explicitly)

---

## P1477

NL: "If a soccer player receives one red card in one game, this player will be ejected from the rest of the game."

Gold FOL (broken): ∀x (SoccerPlayer(x) ∧ Receive(x, oneRedCard)) → EjectFromRestOfGame(x))

Broken reason: syntax_error
Broken evidence: paren grouping wrong — the implication arrow lands outside the universal's body

### Your correction:
c_correct_fol: all x.((SoccerPlayer(x) & Receive(x, oneRedCard)) -> EjectedFromRestOfGame(x))
rationale: Re-balances parens so the implication is the body of the universal. EjectedFromRestOfGame in past participle to match the NL ("will be ejected") and to use a single CamelCase predicate.
introduced_predicates: none (renamed predicate spelling for consistency)

---

## P1479

NL: "In one game, Henry receives one yellow card and one red card."

Gold FOL (broken): Receive(henry, oneYellowCard) ∧ Receive(x, oneRedCard)

Broken reason: free_variable
Broken evidence: free x in second conjunct; clear typo for henry

### Your correction:
c_correct_fol: Receive(henry, oneYellowCard) & Receive(henry, oneRedCard)
rationale: The free x is plainly a typo for henry; both clauses describe Henry's actions in the same game.
introduced_predicates: none

---

## P1505

NL: "The SAT test is wholly owned and developed by the College Board."

Gold FOL (broken): OwnedBy(sAT, collegeBoard) ∧ DevelopedBy(sAT, collegeBoard) ∧ ¬(∃y (¬(y=collegeBoard) ∧ (OwnedBy(sAT, y) ∨ DevelopedBy(sAT, y)))

Broken reason: syntax_error
Broken evidence: unbalanced parens

### Your correction:
c_correct_fol: OwnedBy(sat, collegeBoard) & DevelopedBy(sat, collegeBoard) & -exists y.(-(y=collegeBoard) & (OwnedBy(sat, y) | DevelopedBy(sat, y)))
rationale: "Wholly owned and developed" is the conjunction-plus-uniqueness reading gold attempted; this version closes the parens correctly and lowercases the constant.
introduced_predicates: none

---

## P0519

NL: "A game is played with three stages: red stage, yellow stage, and green stage."

Gold FOL (broken): ∃x ∃y ∃y ∃w (Game(x) ∧ StageNumber(x,3) ∧ Stage(y) ∧ Stage(z) ∧ Stage(w) ∧ ¬(y=z) ∧ ¬(z=w) ∧ ¬(y=w) ∧ Red(y) ∧ Yellow(z) ∧ Green(w))

Broken reason: free_variable
Broken evidence: ∃y ∃y duplicates; z is bound nowhere

### Your correction:
c_correct_fol: exists x.exists y.exists z.exists w.(Game(x) & StageNumber(x, three) & Stage(y) & Stage(z) & Stage(w) & -(y=z) & -(z=w) & -(y=w) & Red(y) & Yellow(z) & Green(w))
rationale: Replaces the duplicate ∃y with ∃z so all four variables are bound; numeric literal 3 becomes the constant three to keep parser-clean.
introduced_predicates: none

---

## P1053

NL: "Over 400,000 copies of \"1901\" have been sold."

Gold FOL (broken): SoldOver(l1901, 400,000)

Broken reason: free_variable
Broken evidence: 400,000 with comma is parsed as multiple tokens / free var; the NL constant for the song is also unconventional

### Your correction:
c_correct_fol: SoldOver(song1901, n400000)
rationale: Renames the comma-bearing numeric to a clean constant n400000, and the song to song1901; the relational claim is the same.
introduced_predicates: none

---

## P0913

NL: "Carrozzeria Colli made car bodies."

Gold FOL (broken): ∃(CarBody(x) ∧ Made(x, carrozzeriaColli))

Broken reason: syntax_error
Broken evidence: ∃ with no variable name

### Your correction:
c_correct_fol: exists x.(CarBody(x) & Made(x, carrozzeriaColli))
rationale: Adds the missing existential variable; otherwise faithful to NL's "made car bodies" (existence of at least one such car body produced).
introduced_predicates: none

---

## P0518

NL: "Only relay swimmers who participated in the final event at the 1972 Summer Olympics received medals."

Gold FOL (broken): ∀x ((ParticipatedIn(x, 1972SummerOlympics) ∧ RelaySwimmer(x) ∧ ¬ParticipatedIn(x, finalHeatFreestyleRelay)) ↔ ¬Recieved(x, medal)))

Broken reason: syntax_error
Broken evidence: digit-leading constant 1972SummerOlympics; "Recieved" misspelling; biconditional with negation gives the wrong logical content; unbalanced paren

### Your correction:
c_correct_fol: all x.(ReceivedMedal(x) -> (RelaySwimmer(x) & ParticipatedIn(x, finalEvent1972Olympics)))
rationale: "Only X did Y" maps to "Y -> X", not a biconditional with negations. The corrected form says: receiving-a-medal implies being a relay swimmer who participated in the final event.
introduced_predicates: ReceivedMedal/1 (replaces misspelled Recieved/2)

---

## P1615

NL: "Zaha Hadid is a British-Iraqi architect, artist, and designer."

Gold FOL (broken): British-Iraqi(zahaHadid) ∧ Architect(zahaHadid) ∧ Artist(zahaHadid) ∧ Designer(zahaHadid)

Broken reason: syntax_error
Broken evidence: hyphen in predicate British-Iraqi

### Your correction:
c_correct_fol: BritishIraqi(zahaHadid) & Architect(zahaHadid) & Artist(zahaHadid) & Designer(zahaHadid)
rationale: Removes the hyphen via CamelCase; same four conjuncts as gold.
introduced_predicates: none

---

## P0446

NL: "Luke can make cookies, scrambled eggs, and muffins, but not pasta."

Gold FOL (broken): CanMake(luke, cookies) ∧ (CanMake(luke, scrambledEggs) ∧ CanMake(luke, muffins) ∧ ¬CanMake(luke, pasta)

Broken reason: syntax_error
Broken evidence: unbalanced parens

### Your correction:
c_correct_fol: CanMake(luke, cookies) & CanMake(luke, scrambledEggs) & CanMake(luke, muffins) & -CanMake(luke, pasta)
rationale: Re-balances parens; the four conjuncts are exactly what NL asserts.
introduced_predicates: none

---

## P0179

NL: "All people who went to Clay's school that do not have regular 9-5 jobs, work in the entertainment industry as high-profile celebrities."

Gold FOL (broken): ∀x (GoTo(x, claysSchool) ∧ ¬(Have(x, y) ∧ Regular(y) ∧ NineToFiveJob(y)) → WorkInAs(x, entertainmentIndustry, highProfileCelebrity))

Broken reason: free_variable
Broken evidence: free y in the antecedent's negated existential pattern; the negation should be "there is no y such that..."

### Your correction:
c_correct_fol: all x.((GoTo(x, claysSchool) & -exists y.(Have(x, y) & Regular(y) & NineToFiveJob(y))) -> WorkInAs(x, entertainmentIndustry, highProfileCelebrity))
rationale: The intended reading is "no regular 9-5 job" — a negated existential, not a negated open formula; binds y properly.
introduced_predicates: none

---

## P0053

NL: "Some monitors made by LG have a type-c port."

Gold FOL (broken): ∃x (Monitor(x) ∧ ProducedBy(x, lG) ∧ Have(x, typeCPort) ∧ (¬(x=y)) ∧ Monitor(y) ∧ ProducedBy(y, lG) ∧ Have(y, typeCPort))

Broken reason: free_variable
Broken evidence: free y from existential-scope leakage; same pattern as P1326

### Your correction:
c_correct_fol: exists x.(Monitor(x) & ProducedBy(x, lg) & Have(x, typeCPort))
rationale: "Some" maps to at-least-one; the two-witness structure is unjustified by NL.
introduced_predicates: none

---

## P0865

NL: "All monitors cheaper than 800 dollars are with a resolution lower than 1080p."

Gold FOL (broken): ∀x ((Monitor(x) ∧ CheaperThan(x, dollars800)) → ResolutionLessThan(x, p1080))

Broken reason: free_variable
Broken evidence: p1080 starts with letter but the parser flagged it as free; treating as constant by renaming

### Your correction:
c_correct_fol: all x.((Monitor(x) & CheaperThan(x, dollars800)) -> ResolutionLessThan(x, res1080p))
rationale: Renames p1080 to res1080p so the resolution bound is plainly a constant; same structural claim as gold.
introduced_predicates: none

---

## P0035

NL: "Lily is in James' family; she watches TV series in cinemas."

Gold FOL (broken): Customer(lily) ∧ In(lily, jameSFamily ∧ WatchIn(lily, tV, cinema)

Broken reason: syntax_error
Broken evidence: unbalanced parens; Customer(lily) appears to be a story-context predicate not in the NL

### Your correction:
c_correct_fol: In(lily, jamesFamily) & WatchIn(lily, tvSeries, cinema)
rationale: Drops the spurious Customer(lily) (NL doesn't assert Lily is a customer); fixes the constant spelling (jamesFamily) and uses tvSeries as the watched-thing constant per NL.
introduced_predicates: none

---

## P1630

NL: "Everyone provided with delicious meals is happy to communicate with each other during the dinner."

Gold FOL (broken): ∀x (ProvidedWith(x, deliciousMeal) ∧ ProvidedWith(y, deliciousMeal)  → ∃y ∃z (¬(y=x) ∧ ¬(z=x) ∧ ¬(y=z) ∧ HappyToCommunicateWithDuringTheDinner(x, y) ∧ HappyToCommunicateWithDuringTheDinner(x, z)))

Broken reason: free_variable
Broken evidence: free y in the antecedent; gold also encodes "two distinct others" which NL does not require (NL only says pairwise communication is happy)

### Your correction:
c_correct_fol: all x.all y.((ProvidedWith(x, deliciousMeal) & ProvidedWith(y, deliciousMeal) & -(x=y)) -> HappyToCommunicateDuringDinner(x, y))
rationale: "Each other" maps to a universal pair-quantification; gold's two-distinct-others encoding overspecifies.
introduced_predicates: HappyToCommunicateDuringDinner/2 (gold's HappyToCommunicateWithDuringTheDinner renamed for length)

---

## P1270

NL: "Burger is used in the lab computer, and it is written with code and a new version of MacOS."

Gold FOL (broken): UsedIn(burger, labComputer) ∧ WrittenWithCode(burger) ∧ MacOS(burger))

Broken reason: syntax_error
Broken evidence: trailing extra paren; "new version of MacOS" reduced to a unary predicate that loses content

### Your correction:
c_correct_fol: UsedIn(burger, labComputer) & WrittenWith(burger, code) & WrittenWith(burger, newMacOsVersion)
rationale: Reformulates "written with code AND a new version of MacOS" as two relational claims using a binary WrittenWith, matching the NL's coordination; closes the stray paren.
introduced_predicates: WrittenWith/2 (replaces unary WrittenWithCode/1 and MacOS/1 to capture both objects)

---

## P0286

NL: "Hulu is a multicellular creature that is autotrophic or digests food internally."

Gold FOL (broken): (MulticellularCreature(hulu) ∧ (Autotrophic(hulu) ∨ DigestFoodInternally (hulu))

Broken reason: syntax_error
Broken evidence: unbalanced parens; space before (hulu) in DigestFoodInternally (hulu)

### Your correction:
c_correct_fol: MulticellularCreature(hulu) & (Autotrophic(hulu) | DigestFoodInternally(hulu))
rationale: Closes parens correctly; preserves the genuine disjunction in NL ("autotrophic OR digests internally") which is the faithful reading.
introduced_predicates: none

---
