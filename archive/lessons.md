# Experiment Lessons

Accumulated lessons from running the SIV paper experiments. Each section
records design mistakes, diagnostic findings, and methodological notes that
inform subsequent experiments.

## Exp 1 lessons

- Including gold in the candidate set as both candidate-row-0 and the
  reference-for-other-metrics produces trivial AUC=1.0 on reference-based
  metrics. The fix is to evaluate metrics on perturbations only and report
  absolute scores or detection-vs-threshold rates, not gold-vs-perturbation
  discrimination AUC.

- BLEU on FOL strings has higher detection than expected because
  perturbations to short FOL strings change multiple bigrams. To see
  BLEU's logical-blindness clearly, the candidate has to be lexically
  close to gold over a longer string — i.e., a real translation, not a
  surgical perturbation. This is a Exp 2 / appendix concern.

- SIV's recall does not detect overweak perturbations that preserve
  sub-entailments. This is by design: positives test underspecification,
  contrastives test overspecification, the overweak-but-direction-preserving
  case is in the gap. Exp 2 addresses this with consequent-level granularity.

- Smoke tests work. The 67%-on-untightened-subset smoke caught the
  alignment-failure issue before scoring. Keep this discipline.
