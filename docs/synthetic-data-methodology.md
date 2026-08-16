# Synthetic data methodology

This document covers how a cohort is generated, how it is validated, and how
the fidelity score is constructed. The validation half is the part that
matters to a reviewer, and it is fully implemented in this repository. The
generation half ships as a placeholder here, which this document is explicit
about.

## Generation

### What the production engine does

The production engine trains an SDV CTGAN model on the parsed seed cohort:
conditional sampling by inclusion criteria, mode specific normalisation of
continuous lab values, a discriminator schedule tuned for the wide tabular
schemas clinical data arrives in, and the privacy accounting that makes the
output releasable.

That engine is not in this repository. It ships as a private package,
`pretrial_synthecore_private`, installed from a private index in the
deployment image.

### What the public build does instead

`services/synthecore/app/engine/ctgan_pipeline.py` resolves an engine at
runtime. If the private package is importable it is used. If not, the build
falls back to `BootstrapCohortGenerator`.

The fallback resamples rows from the seed cohort with replacement and adds
Gaussian jitter scaled to each column's own standard deviation. Booleans and
low cardinality codes are carried through untouched, because jittering an
ECOG status of 1 into 1.03 produces a record no clinician would accept.

**The fallback provides no privacy guarantee.** Every output row is a
lightly perturbed copy of a real row. It exists so that the pipeline, the
progress transport, the screening logic, the validation service, and the UI
can all be exercised end to end without the proprietary model. It must never
be pointed at real patient data outside a local development environment.

The service exposes which engine is running at `GET /engine`, and the UI
shows it in a banner on every page. A cohort produced by the stub and a
cohort produced by CTGAN are not interchangeable, and that difference should
never be buried in an environment variable. The deploy workflow fails the
release if a production deployment comes up running the stub.

### Why CTGAN rather than something simpler

Three alternatives were considered and rejected:

**Independent marginal sampling.** Fit a distribution per column, sample each
independently. Fast and trivially private. It also produces cohorts where
age and creatinine are uncorrelated, which makes any renal exclusion
criterion meaningless. The correlation check in FidelityCheck exists
specifically to catch this class of output, and it catches it every time.

**Gaussian copula.** Preserves a correlation structure and is far cheaper to
fit than a GAN. It assumes the dependency structure is captured by rank
correlation, which clinical data violates routinely: the relationship
between HbA1c and insulin use is a threshold effect, not a monotone one.
Copulas are a reasonable fallback for narrow schemas and this remains an
option for small seed cohorts where a GAN would overfit.

**Bayesian networks.** Interpretable, and the conditional structure is
attractive for criteria based sampling. They need a discretisation of every
continuous variable, and the discretisation is where the information about
lab value distributions is lost, which is exactly what feasibility work
depends on.

CTGAN handles mixed continuous and categorical tabular data natively, uses
mode specific normalisation for the multimodal continuous columns that lab
values actually are, and its training by sampling addresses the severe class
imbalance in comorbidity flags. The cost is that it is slow, needs a real
seed cohort to be worth anything, and is easy to overfit on a small one.
That cost is why generation is an async job and why the service warns when a
seed has fewer than 100 rows.

## Seed processing

Before anything is fitted:

1. Column names are normalised to snake case. Case is folded and punctuation
   collapses to underscores. Camel case is deliberately **not** split:
   clinical column names are full of mixed case abbreviations, and splitting
   them turns `HbA1c` into `hb_a1c` while `hba1c` stays `hba1c`, so the same
   lab value from two sponsors becomes two different features.
2. Direct identifiers are removed. The pattern list covers MRN, name, contact
   details, address, national identifiers, and date of birth.
3. Free text columns are removed. A tabular generator cannot model them, and
   they are the most likely place for an identifier to hide inside prose.
4. Numeric columns stored as text are coerced, and the count of values lost
   to coercion is reported.
5. Degenerate columns are dropped: over 95 percent null, single valued, or
   unique in every row.

Everything removed is reported back to the operator. A silent type coercion
on a lab value column surfaces three weeks later as an inexplicable fidelity
score.

## Screening and the attrition funnel

Criteria are applied to the generated cohort rather than folded into the
sampler, and the order is preserved from the protocol.

This is a deliberate choice with a cost. A conditional sampler that only
emits eligible patients is more efficient. It also cannot tell you that the
eGFR floor alone disqualifies 61 percent of the remaining population, and
that number is the actual product. The question a sponsor is asking is not
"can we build a cohort" but "which line of this protocol is making
recruitment impossible".

To hit a target eligible count, the service runs a probe sample, measures
the eligibility rate, and oversamples by `1.25 / rate`. The safety margin
absorbs sampling variance in the rate estimate; without it, a rate measured
on a small probe lands short about half the time and a second generation
pass costs minutes.

Patients with a missing value for a threshold criterion are treated as not
meeting it. An unscreenable patient is not an eligible one.

## Validation

Three tests, run per cohort, combined into one score.

### Marginal agreement: Kolmogorov-Smirnov and total variation distance

For continuous features, a two sample KS test. The statistic D is the largest
vertical gap between the two empirical CDFs, bounded in [0, 1] and
distribution free, so the same threshold means the same thing for an age
column and a creatinine column.

For categorical features, total variation distance: the natural discrete
analogue of D. Both are a supremum of absolute probability differences, both
are bounded in [0, 1], and both equal 0 only on an exact match.

**The score uses D, not the p-value.** This is the single most important
methodological decision in the validation pipeline and it needs stating
plainly. At the cohort sizes this product targets, 10k to 100k synthetic
rows, a KS test rejects the null for differences far too small to affect
trial feasibility. A p-value driven score would report near total failure on
cohorts that are clinically and visually indistinguishable from the
reference. The p-value is still returned, because reviewers expect to see it
and because it is the correct statistic to quote at small sample sizes.

Feature score: `1 - D`.

### Shape agreement: Jensen-Shannon divergence

KS reports the single worst point of the CDF, so it is blind to a
distribution that is close everywhere except in shape. A synthetic cohort
that fills the same range but flattens a bimodal HbA1c distribution into one
broad hump can post a low D. JS divergence integrates disagreement across the
whole support and catches exactly that.

Base 2 throughout, which bounds the divergence in [0, 1] bits: 0 on an exact
match, 1 when the supports do not overlap at all. That bound is what makes
the score comparable across features and mixable with the KS score.

Bin edges are computed once over the **pooled** sample. Binning each side
independently would compare probability vectors defined over different
intervals, which produces a number that looks like a divergence and is not
one. Freedman-Diaconis picks the bin count, clamped to between 5 and 64;
unclamped it produces thousands of bins on a large cohort, making every bin
sparse and inflating the divergence for reasons of sampling noise rather
than distributional difference.

Feature score: `1 - JSD`.

### Dependency structure: correlation matrix comparison

Per feature tests are marginal. A generator can reproduce the age
distribution perfectly and the creatinine distribution perfectly and still
produce a cohort where the two are uncorrelated, which for a renal exclusion
criterion makes the cohort useless.

Categorical features are one hot encoded first, dropping one level per
feature to avoid a perfectly collinear column. High cardinality fields are
excluded: one hot encoding a 400 level ICD-10 column swamps the matrix with
near empty indicators whose correlations are dominated by noise.

Only the strict upper triangle is compared. The diagonal is always 1 and
would drag any summary toward zero.

**The score is built from the RMS delta and the worst single delta, not the
mean.** The mean is the wrong summary here, and measurably so. One hot
encoding expands a handful of clinical features into dozens of matrix
entries, most near zero on both sides, so averaging across all pairs drowns
the few that matter. On a test cohort whose age to eGFR correlation had been
destroyed outright, moving from -0.599 to +0.017, the mean based score still
read 98.3 percent. That is precisely the failure the test exists to catch,
and it was reporting it as a pass. Rebuilt on RMS and max, the same cohort
scores 82.1 percent.

```
penalty = 0.5 * rms_delta + 0.5 * max_absolute_delta
score   = 1 - penalty / 2
```

The division by 2 is because Pearson r lives in [-1, 1], so a delta can
reach 2. It keeps the score on the same 0 to 1 footing as the other two.

### Aggregation

```
marginal agreement    weight 0.40
shape agreement       weight 0.35
dependency structure  weight 0.25

raw    = weighted mean, renormalised over whichever components were evaluated
overall = raw * schema_coverage
```

Marginals carry the most weight because inclusion and exclusion criteria are
written against them directly: an age band, a lab value ceiling, a prior
therapy flag. Shape agreement is close behind because a matched marginal
with the wrong internal structure passes screening and then fails at
analysis. Dependency structure carries the least because it is the noisiest
of the three at these cohort sizes, not because it matters least.

Renormalising over evaluated components means a single feature dataset still
returns a defensible score rather than a silently deflated one.

Schema coverage is a multiplier, not a component. A synthetic cohort that
reproduces six of twelve requested fields perfectly is not a 100 percent
faithful cohort. The report shows both `raw_fidelity` and `overall_fidelity`
so the penalty is visible rather than baked in silently.

### Grades

| score | grade | meaning |
| --- | --- | --- |
| 90 and above | pass | Usable for feasibility work |
| 70 to 89.9 | borderline | Directional only. Read the per feature table first |
| below 70 | fail | Do not use for feasibility decisions |

These thresholds are duplicated in `report_builder.py` and in
`packages/shared-types`, and both files carry a comment pointing at the
other. A green ring on a cohort the service graded as failing is the worst
bug the badge component can have.

FHIR-Link refuses to export below 70 without an explicit acknowledgement,
which is recorded in the response metadata.

## What the cohort is compared against

A delivered cohort has been screened. It is therefore compared against a seed
population screened by the **same criteria**, not against the raw seed.

This matters more than it sounds. Comparing a screened cohort against the
full seed measures the criteria rather than the generator. An HbA1c floor of
7.0 guarantees the two HbA1c distributions differ, so the score drops for a
generator that did nothing wrong. On the reference population that mistake
cost roughly five points of fidelity: the same cohort scored 93.61 against
the raw seed and 98.73 against the correctly screened one.

The basis used is reported on every job as `validation.comparison_basis`,
alongside `reference_rows`. If too few seed patients meet the criteria to
support a comparison, the service falls back to the full seed and says so in
that field rather than quietly returning a depressed score.

## Measured behaviour

Run against the built in reference population, 6000 rows, nine features,
using the bootstrap fallback generator:

| scenario | overall | marginal | shape | dependency |
| --- | --- | --- | --- | --- |
| Generator against its own seed | 99.21 | 98.93 | 99.65 | 99.06 |
| Marginals preserved, three columns shuffled | 94.97 | 98.93 | 99.65 | 82.09 |
| Unrelated cohort, same schema | 66.41 | fails | | |

The middle row is the one worth reading. Both marginal tests are unchanged
at 98.93 and 99.65, because shuffling a column within itself preserves its
distribution exactly. Only the dependency check moves, and it moves 17
points. That is the correlation test doing the job the other two structurally
cannot.

Reproduce these with the smoke test path described in the README.

## Known limitations

- The bootstrap fallback is not private and is not a model. Nothing about the
  fidelity figures above says anything about CTGAN output quality.
- Feature typing is heuristic. A numeric column with 10 or fewer distinct
  values is treated as categorical. This is right for ECOG status and trial
  arm and wrong for a lab value that happens to be coarsely rounded.
- Datetime columns are unsupported and skipped, which is reported in the
  warnings but means longitudinal data is out of scope entirely.
- The correlation check uses Pearson by default. Spearman is available per
  request. Neither captures a threshold relationship, which is common in
  clinical data.
- Validation runs on a sample capped at 20,000 rows per side. The KS
  statistic stabilises well below this, but the cap is a cap.
- No privacy metrics are computed. There is no membership inference test, no
  nearest neighbour distance ratio, and no differential privacy accounting in
  this repository. Statistical fidelity and privacy are different questions,
  and only the first is answered here.
