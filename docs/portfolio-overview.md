# Pretrial.ai

A case file on a clinical trial feasibility platform built on validated
synthetic patient cohorts.

## Product thesis

A pharmaceutical sponsor commits to a trial protocol before knowing whether
the protocol can recruit. Sites are contracted, budgets are approved, and
regulatory submissions are filed against inclusion and exclusion criteria
that nobody has tested against a real population, because the only way to
test them is to open sites and start screening. The answer arrives roughly
eighteen months later in the form of an enrolment curve that is flat, and by
then the sunk cost is the trial. The protocol is amended, the amendment goes
back through ethics review, and the clock restarts. This delay persists not
because sponsors are careless but because the feasibility question is
genuinely hard to answer in advance: the data that would answer it sits
inside hospital systems, is governed by patient privacy law, cannot be
pooled across institutions, and takes months to access through a data
sharing agreement even when the answer needed is a single aggregate
statistic. A synthetic cohort resolves the deadlock, because it reproduces
the distributions, comorbidity structure, and lab value correlations of a
real population without containing a real patient. It can be shared, queried,
and screened against a protocol in an afternoon. The catch, and the reason
most synthetic data efforts stall, is that a synthetic cohort is worthless
unless you can prove it matches. Pretrial.ai treats that proof as the
product, not as a footnote to it.

## Architecture

Three Python services and a Next.js frontend. The services share no database
and do not import each other's code. They communicate over HTTP and answer in
a single response envelope.

**SyntheCore** generates the cohort. It parses an uploaded seed extract,
strips direct identifiers before anything is modelled, fits a generative
model, samples patients, and screens them against the protocol's criteria in
the order the protocol states them. It exists as a separate service because
its runtime profile is unlike anything else in the system: a model fit runs
for minutes and needs a large memory allocation, so it needs a queue and a
worker fleet that scales on queue depth rather than on request rate.

**FidelityCheck** proves the cohort matches, or shows exactly where it does
not. It takes a reference dataset and a synthetic dataset and returns a per
feature statistical comparison plus one aggregate score. It is stateless by
design: data arrives in the request, the report goes back in the response,
nothing touches disk. A service that never writes cannot leak what it never
stored.

**FHIR-Link** turns a validated cohort into FHIR R4 Patient and Observation
resources that a hospital network or a clinical trial management system can
ingest directly. Also stateless. It is the smallest of the three and the one
with the most compliance surface.

The split is not architectural fashion. It is driven by three genuinely
different runtime profiles, and by the fact that one of the three contains
proprietary code and the other two do not. That boundary is cleaner when it
is a service boundary.

## Key engineering decisions

**CTGAN over simpler generative approaches.** Independent marginal sampling
is fast, trivially private, and useless: it produces cohorts where age and
creatinine are uncorrelated, which makes any renal exclusion criterion
meaningless. Gaussian copulas preserve rank correlation cheaply but assume
the dependency structure is monotone, and clinical relationships routinely
are not. The link between HbA1c and insulin use is a threshold effect.
Bayesian networks are interpretable and attractive for criteria based
conditional sampling, but they require discretising every continuous
variable, and the discretisation destroys exactly the lab value distribution
detail that feasibility work depends on. CTGAN handles mixed continuous and
categorical tabular data natively, uses mode specific normalisation for the
multimodal continuous columns that lab values actually are, and its training
by sampling addresses the severe class imbalance in comorbidity flags. The
cost is real: it is slow, it needs a substantial seed cohort, and it
overfits easily on a small one. That cost is why generation is an
asynchronous job rather than a request.

**Kolmogorov-Smirnov and Jensen-Shannon divergence as the validation
standard, with a correlation check alongside.** These two tests fail
differently, which is the reason for running both. KS reports the largest
gap between two empirical distribution functions, so it is sharp on location
and scale shifts and blind to a distribution that occupies the right range
with the wrong internal shape. JS divergence integrates disagreement across
the whole support and catches that case. Both are bounded, which makes their
scores comparable across features and mixable into an aggregate. One
decision inside the KS implementation is worth stating because it is
counterintuitive: the score is derived from the KS statistic, not the
p-value. At the cohort sizes this product targets, ten thousand to a hundred
thousand rows, a KS test rejects the null hypothesis for differences far too
small to affect a feasibility decision. A p-value driven score would report
near total failure on cohorts that are clinically indistinguishable from the
reference population. The p-value is still returned, because a
biostatistician will look for it and because it is the right statistic at
small sample sizes.

Both of those tests are marginal, and marginal tests share a blind spot. A
generator can reproduce every column's distribution perfectly and still
produce a cohort where the relationships between columns are gone. The
correlation matrix comparison is what closes that gap, and building it
correctly required a revision. The obvious summary statistic, mean absolute
delta across the matrix, turned out to be the wrong one: one hot encoding
expands a handful of clinical features into dozens of matrix entries, most
near zero on both sides, so the mean drowns the entries that broke. On a
test cohort whose age to eGFR correlation had been destroyed outright,
moving from -0.599 to +0.017, the mean based score still read 98.3 percent.
That is the precise failure the test exists to catch, reported as a pass.
Rebuilt on RMS and worst case deltas, the same cohort scores 82.1 percent.

**FHIR R4 bundle export for hospital network compatibility.** Feasibility
output that cannot enter the sponsor's existing systems is a slide, not a
tool. FHIR R4 is what hospital networks and modern CTMS platforms speak.
Resources are constructed through a validating library rather than assembled
as dictionaries, which is not a theoretical preference: the first version of
the resource id scheme embedded feature names, producing identifiers with
underscores, and FHIR restricts resource ids to a character set that excludes
them. The library rejected it at construction. Hand rolled dictionaries would
have shipped it and it would have failed at a customer's ingestion endpoint.
Every emitted resource carries the HL7 `HTEST` security label marking it as
test health data, and that is deliberately not configurable. A synthetic
patient record entering a production clinical data warehouse unmarked is the
worst thing this product could do, so the marker is applied by the builder,
re-verified independently in the browser before download, and checked once
more by the client that pushes to a remote FHIR server.

**Celery for generation jobs that run for minutes rather than milliseconds.**
No reverse proxy in a hospital network will hold an HTTP connection open for
a model fit. Generation therefore enqueues and returns a job id. What made
this more than boilerplate was the progress reporting. Each stage transition
writes full job state to a Redis key and publishes the same state on a
channel. The write exists because publish/subscribe has no history: a
browser connecting thirty seconds into a job would otherwise see nothing
until the next stage boundary, which during model training can be minutes of
blank screen. The stream subscribes first, then reads the stored snapshot and
emits it as the opening frame, then follows the channel, which closes the
window where a transition lands between the two operations and is lost.
Transport is Server Sent Events rather than WebSockets, because the traffic
is one directional and SSE passes through load balancers and corporate
proxies without special handling. A pharma network is not where you want to
discover that WebSocket upgrades are filtered. The frontend falls back to
polling if the stream drops, because a progress view that silently stops
updating is worse than none.

## What the FidelityScore signals

The score is a single percentage, displayed at 48px in monospace with a
colour coded ring, and it is the decision gate. A clinical operations
director looking at a cohort is answering one question: can I size a protocol
against this, or not. Above 90 the cohort reproduces the reference population
closely enough for feasibility work. Between 70 and 89 it is directional
only, worth using to compare two protocol variants against each other but not
to commit a recruitment forecast to. Below 70 it should not inform a decision
at all.

It works as a gate because of what sits behind it. It is a weighted
composition of marginal agreement at 0.40, distributional shape agreement at
0.35, and dependency structure at 0.25, multiplied by schema coverage. The
weights are published in the product and in the documentation rather than
buried, because the number has to survive a biostatistician who did not build
it asking how it was derived. Marginals carry the most weight because
inclusion and exclusion criteria are written directly against them: an age
band, a lab value ceiling, a prior therapy flag. Schema coverage is a
multiplier rather than a component because a cohort reproducing six of twelve
requested fields perfectly is not a fully faithful cohort, and the report
shows the score both before and after that penalty so it is visible rather
than silently applied.

The composition is also what makes the score honest under adversarial
conditions. Run against the built in reference population at six thousand
rows and nine features, a generator scored against its own seed returns 99.21
percent. Take the same output and shuffle three columns within themselves,
which preserves every marginal distribution exactly while destroying the
relationships between them, and the two marginal components do not move at
all, staying at 98.93 and 99.65. The dependency component drops to 82.09 and
the overall score falls to 94.97. An unrelated cohort on the same schema
scores 66.41 and fails. A score built only on marginal agreement would have
passed the shuffled cohort at 99 percent, and a director would have sized a
protocol against a population whose renal function had no relationship to
patient age.

## Public and private split

FidelityCheck and FHIR-Link are fully open. Every statistical test is real,
implemented against scipy and pandas, and covered by tests that assert
mathematical properties rather than snapshot outputs. The FHIR mapping,
terminology table, bundle construction, and compliance markers are all
present and inspectable.

That is a deliberate commercial choice, not an oversight. The validation
methodology is the thing a pharma buyer needs to audit before trusting any
output, and a validation pipeline nobody can read is not evidence. Publishing
it converts the hardest part of the sales conversation, which is establishing
that the numbers mean something, into something the buyer's own
biostatistician can verify in an afternoon. The same applies to the export
gateway: compliance behaviour that cannot be inspected is compliance
behaviour nobody should accept.

The SyntheCore CTGAN training pipeline is proprietary and is stubbed in the
public repository. The conditional sampling by inclusion criteria, mode
specific normalisation, discriminator schedule tuned for wide clinical
schemas, and privacy accounting are the differentiated engineering, and they
ship as a private package installed from a private index at image build time.
The public repository resolves the engine at runtime and falls back to a
bootstrap resampler when the private package is absent.

The fallback is documented as what it is, in the code, in the README, and in
the running product. It resamples seed rows with jitter, which is enough to
exercise the full pipeline and the interface end to end, and it carries no
privacy guarantee whatsoever. The active engine is exposed on an endpoint and
displayed in a banner on every page of the application, so stub output cannot
be screenshotted and presented as production output. The deployment pipeline
fails a release if a production environment comes up running the fallback.
Everything downstream of the generator behaves identically against either
engine, which means the public repository is a complete working system with a
placeholder where the model belongs, rather than a system with a hole in it.

## Build status

**Production ready.** The FidelityCheck statistical engine and its API, the
FHIR-Link bundle builder and all four export formats, SyntheCore's seed
processing and identifier stripping, the criteria screening engine with its
attrition funnel, and the Celery job pipeline with Redis backed progress
streaming. One hundred tests across the three services, all passing. No
mocked statistics anywhere in the validation path. Continuous integration
stands up the full stack in containers, generates a cohort end to end, and
asserts that a fidelity score comes back, which is the check that catches
the wiring failures no unit test sees.

**Demo ready.** The frontend builds, typechecks, lints clean, and renders
live service data across eight routes. It has no component test suite and has
not been checked against a browser matrix. The Docker Compose stack brings up
the entire system locally and is the supported way to run it.

**Requires real seed data and IRB clearance to go live.** The CTGAN engine
needs a real seed cohort to produce anything meaningful, and obtaining one
requires an institutional data sharing agreement and ethics approval. Until
then the system runs against a built in reference population that is a demo
fixture derived from published population level summary statistics, not from
patient records, and the product labels it as such.

**Not built, and stated rather than implied.** Authentication is not
implemented. The SMART on FHIR flow is a user interface shell with no token
exchange and no sessions, so the service tier runs behind network controls
rather than being exposed directly. The Postgres schema is not
written; job records live in Redis under a time to live, which makes the job
list endpoint a key scan that is correct at single deployment scale and wrong
at multi tenant scale. The Terraform describes the intended AWS topology and
has never been applied to a live account. No privacy metrics are computed:
there is no membership inference test, no nearest neighbour distance ratio,
and no differential privacy accounting in the open repository. Statistical
fidelity and privacy are different questions, and only the first is answered
by what is published here.
