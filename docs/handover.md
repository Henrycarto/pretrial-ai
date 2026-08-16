# Handover

For the next developer on Pretrial.ai. Read the README first for what the
product is and what is built. This document covers what the README does not:
how to get it running, what has actually been verified, the decisions that
will look wrong until you know why, and what to pick up next.

Accurate as of 16 August 2026.

## Getting it running

The supported path is the Compose stack. It brings up Redis, Postgres, the
three services, and the Celery worker.

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up -d --build \
  redis postgres fidelitycheck fhirlink synthecore synthecore-worker
```

Then run the frontend as a dev server against those containers rather than
building the `web` image. You get hot reload with live service data, and the
browser facing URLs already default to `localhost:8001` through `8003`.

```bash
npm install
npm run dev --workspace=@pretrial/web
```

Frontend on 3000. SyntheCore 8001, FidelityCheck 8002, FHIR-Link 8003,
Postgres 5432, Redis 6379. All six are common ports. If another local stack
holds any of them, bring it down first or the containers will fail to bind.

For the Python tests you need an environment with the service requirements.
There is no single requirements file for the repository, because each service
is deployed as its own image.

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install \
  -r services/fidelitycheck/requirements.txt \
  -r services/synthecore/requirements.txt \
  -r services/fhirlink/requirements.txt
```

Run each suite from its own service directory, with `PYTHONPATH=.` rather
than an installed package. The services are applications, not libraries, and
each image copies `app/` in directly. Installing them would test a layout
that does not exist in the image.

```bash
cd services/fidelitycheck && PYTHONPATH=. SYNTHECORE_ENGINE=stub pytest -q
```

## Verified state

Everything below was run and observed, not assumed.

- 100 Python tests pass. 31 FidelityCheck, 43 SyntheCore, 26 FHIR-Link.
- All three services import cleanly via `python -c "import app.main"`.
- The frontend typechecks, lints with zero warnings, and builds 8 routes.
- CI is green end to end across all 11 jobs, including all four Docker image
  builds and the stack smoke test that generates a cohort through Celery and
  asserts a fidelity score plus HTEST labelling on the exported bundle.
- Run locally against the reference population: 5000 patients, 99.2 percent
  fidelity, 0.3 seconds on the stub generator.

The frontend has no component tests. That is the largest single gap in the
test story and it is stated in the README rather than hidden.

## Decisions that look wrong until you know why

**The fidelity score uses the KS statistic, not the p-value.** At ten
thousand to a hundred thousand rows a KS test rejects the null for
differences far too small to matter clinically. A p-value driven score fails
cohorts that are clinically indistinguishable from the reference. The p-value
is still reported because a biostatistician will look for it.

**The dependency score uses RMS and worst case deltas, not the mean.** One
hot encoding expands a few features into dozens of matrix entries. Averaging
hides the ones that broke. A cohort whose age to eGFR correlation had been
destroyed outright scored 98.3 percent on the mean and 82.1 on RMS.

**Validation compares against the seed screened by the same criteria.** A
screened cohort compared against the full seed measures the criteria, not the
generator. An HbA1c floor guarantees the two distributions differ. The basis
used is reported as `comparison_basis` on the result so a caller can discount
the score when it falls back.

**The screening funnel merges across batches.** Sampling runs more than once
when criteria are strict, and reporting only the final batch produced a
funnel whose eligible count contradicted the delivered cohort size. See
`_merge_screening` in `services/synthecore/app/tasks/generation_job.py` and
its tests.

**Progress is written to a Redis key and published on a channel.** Publish
and subscribe has no history, so a browser connecting mid job would see
nothing until the next stage boundary. The stream subscribes first, then
emits the stored snapshot as its opening frame, then follows the channel.

**HTEST is not configurable.** Every exported FHIR resource carries the HL7
test health data label. It is applied by the builder, verified again in the
browser before download, and checked once more by the push client.

## The stub boundary

`services/synthecore/app/engine/ctgan_pipeline.py` imports
`pretrial_synthecore_private` when available and falls back to
`BootstrapCohortGenerator` when it is not. The fallback resamples seed rows
with Gaussian jitter. It exercises the whole pipeline and carries no privacy
guarantee whatsoever.

Three things enforce the boundary. `GET /engine` reports the active engine
and the UI shows it in a banner on every page. The deploy workflow fails a
release if a production environment comes up on the fallback. A CI job fails
the build if the private package is ever committed or pinned here.

Everything downstream of the generator behaves identically against either
engine.

## Design rules, locked

Do not treat these as defaults to adjust per screen. Reference point is
Bloomberg Terminal meets clinical research software. Density over decoration.

Colours, as named tokens in `apps/web/tailwind.config.ts`. Shell `#080F1A`.
Panels `#0E1B2E`. Accent `#2563EB`. Pass `#10B981`. Warning `#F59E0B`. Fail
`#EF4444`. Never write a hex value into a class string.

JetBrains Mono for every number, score, and data value. Inter for labels and
prose. Mono on numbers is non negotiable: it signals computation.

The FidelityScore badge is the signature element. One percentage in mono at
48px with a colour coded ring, emerald above 90, amber 70 to 89, red below
70. The ring is a progress arc whose sweep is the score, not decoration.
Thresholds live in `packages/shared-types` and must move together with
`report_builder.py`.

Pipeline progress is a list of named stages. There is no spinner anywhere in
the application and none is to be added. Distribution charts are side by
side, real against synthetic, top five features, Recharts.

Forbidden: gradient hero text, three column feature card grids, warm or off
white backgrounds, pill buttons, SaaS template layouts, glowing orbs or mesh
gradients, logo strips, testimonial cards, floating drop shadow cards.
`borderRadius` tops out at 4px and `boxShadow` is deliberately empty, so
separation comes from 1px rules and background steps.

## House style

No em dashes and no en dashes, anywhere. CI enforces it over markdown,
TypeScript, Python, YAML, CSS, Terraform, and JSON. A violation fails the
`copy-rules` job.

## Traps

**Inline scripts inside a `run:` block must be indented.** A Python heredoc
starting at column 0 closes the YAML block scalar and makes the rest of the
workflow file unparseable. Every job then fails at startup with no logs, and
GitHub lists the run under the filename rather than the workflow name. Indent
to the block's own indentation. YAML strips it again before the shell sees it.

**Guards that grep for a string will match documentation.** The boundary job
failed on the comment in `services/synthecore/requirements.txt` that explains
why the private package is absent. The pattern is anchored with `^[^#]*` so a
comment cannot trip it.

**`fhir.resources` 7.1.0 reports its own `__version__` as `7.0.0`.** Trust
pip, not the attribute. The floor matters as much as the ceiling: 7.0.x is
built against pydantic v1 and raises ImportError at import time, which takes
the service down on startup rather than failing a request.

**Feature typing is heuristic.** A numeric column with 10 or fewer distinct
values is treated as categorical. Right for ECOG, wrong for a coarsely
rounded lab value.

## What to pick up next

Ordered by what unblocks the most.

1. **Authentication.** There is none. Every service is reachable without
   credentials and the SMART on FHIR flow is a UI shell with no token
   exchange and no sessions. This is what stops the system leaving a private
   network.
2. **Postgres.** Provisioned in Terraform and unused. Job records live in
   Redis under a TTL, which makes the job list endpoint a key scan. Correct
   at single deployment scale, wrong at multi tenant scale.
3. **Frontend component tests.** Eight routes with no test coverage.
4. **Privacy metrics.** No membership inference, no nearest neighbour
   distance ratio, no differential privacy accounting. Statistical fidelity
   and privacy are different questions and only the first is answered here.
5. **Terraform.** Describes the intended AWS topology and has never been
   applied to a live account. Assume it is wrong until it runs.
6. **Datetime columns.** Unsupported, so longitudinal data is out of scope.
