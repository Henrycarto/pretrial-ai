# Pretrial.ai

Clinical trial recruitment takes 18 months on average. Pretrial.ai compresses
feasibility to 48 hours.

A sponsor cannot know whether a protocol recruits until sites have screened
real patients against it. That answer arrives months into a study, after the
sites are contracted and the budget is committed. Pretrial.ai answers the
same question against a statistically validated synthetic cohort, before the
first site opens.

The product is three services:

- **SyntheCore** generates a synthetic patient cohort from seed data and
  screens it against the protocol's inclusion and exclusion criteria.
- **FidelityCheck** proves the cohort matches the reference population, or
  shows exactly where it does not.
- **FHIR-Link** emits the validated cohort as FHIR R4 bundles a hospital
  network or CTMS can ingest.

## Build status

This section is the first thing to read. The three labels below are used
precisely and nothing is claimed beyond them.

**Production ready** means implemented, tested, and correct as far as the
tests go. **Demo ready** means it works end to end and is honest about what
it is, but something behind it is a placeholder. **Not built** means not
built.

| Component | Status | Detail |
| --- | --- | --- |
| FidelityCheck statistical engine | Production ready | KS, total variation, Jensen-Shannon, correlation comparison. 31 tests. No mocks anywhere in this path |
| FidelityCheck `/validate` API | Production ready | Full report, per feature results, chart payloads, consistent envelope |
| FHIR-Link bundle builder | Production ready | R4 Patient and Observation via `fhir.resources`, HTEST tagged, deterministic ids. 26 tests |
| FHIR-Link export formats | Production ready | Collection, transaction, NDJSON, flat CSV |
| SyntheCore seed processing | Production ready | Parsing, normalisation, identifier stripping, type coercion, profiling |
| SyntheCore criteria screening | Production ready | Ordered criteria, cumulative attrition funnel, oversampling. 43 tests |
| SyntheCore job pipeline | Production ready | Celery, four stage progress over Redis pub/sub, SSE to the browser |
| **SyntheCore CTGAN generation** | **Stubbed** | **The training pipeline is proprietary and absent from this repository. See below** |
| Frontend | Demo ready | Builds, typechecks, renders real service data. Not tested against a browser matrix |
| Docker Compose stack | Demo ready | Brings up the full system locally |
| Terraform | Not applied | Describes the intended AWS topology. Never run against a live account |
| Postgres schema | Not built | Provisioned in Terraform, unused. Job records live in Redis with a TTL |
| SMART on FHIR auth | Not built | UI shell only. No token exchange, no sessions. Every service is unauthenticated |
| Privacy metrics | Not built | No membership inference, no nearest neighbour ratio, no differential privacy accounting |

### The stub, stated plainly

The CTGAN training pipeline is the product and it is not in this repository.
`services/synthecore/app/engine/ctgan_pipeline.py` imports
`pretrial_synthecore_private` when it is available and falls back to
`BootstrapCohortGenerator` when it is not.

The fallback resamples rows from the seed with replacement and adds Gaussian
jitter. It reproduces marginals and most of the correlation structure, which
is enough to exercise the whole pipeline and the UI. **It provides no privacy
guarantee.** Every output row is a lightly perturbed copy of a real row.

The running engine is exposed at `GET /engine` and shown in a banner on every
page of the UI, so stub output cannot be screenshotted and mistaken for
production output. The deploy workflow fails the release if a production
deployment comes up on the fallback.

Everything downstream of the generator, which is the job pipeline, the
progress transport, the criteria filter, FidelityCheck, and FHIR-Link, runs
identically against either engine.

## Quick start

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up --build
```

| service | URL |
| --- | --- |
| Frontend | http://localhost:3000 |
| SyntheCore | http://localhost:8001/docs |
| FidelityCheck | http://localhost:8002/docs |
| FHIR-Link | http://localhost:8003/docs |

Open http://localhost:3000/cohorts/new and generate a cohort. With no seed
file uploaded it runs against a built in reference population, which is a
demo fixture and is not derived from any patient record.

### Without Docker

```bash
# FidelityCheck
cd services/fidelitycheck
pip install -r requirements.txt
PYTHONPATH=. uvicorn app.main:app --port 8002

# Frontend
npm install
npm run dev --workspace=@pretrial/web
```

SyntheCore needs Redis for the job queue and the progress channel.

## Tests

```bash
for svc in fidelitycheck synthecore fhirlink; do
  (cd services/$svc && PYTHONPATH=. pytest -q)
done

npm run typecheck && npm run lint && npm run build
```

100 Python tests across the three services. The frontend has a typecheck, a
lint, and a production build; it has no component tests, which is a real gap.

CI additionally stands up the Compose stack, generates a cohort end to end,
waits for the worker, and asserts a fidelity score came back. That job is
what catches the wiring bugs no unit test sees.

## How the fidelity score works

One number decides whether a cohort is usable. It is built from three
components with published weights:

```
marginal agreement    0.40   KS statistic, total variation distance
shape agreement       0.35   Jensen-Shannon divergence, base 2
dependency structure  0.25   correlation matrix delta

overall = weighted mean * schema coverage
```

| score | grade |
| --- | --- |
| 90 and above | pass |
| 70 to 89.9 | borderline |
| below 70 | fail |

Two decisions in there are worth knowing before you trust the number.

**The score uses the KS statistic, not the p-value.** At 10k to 100k rows a
KS test rejects the null for differences far too small to matter clinically.
A p-value driven score would fail cohorts that are indistinguishable from the
reference. The p-value is still reported.

**The dependency score uses RMS and worst case deltas, not the mean.** One
hot encoding expands a few clinical features into dozens of matrix entries,
and averaging across all of them hides the ones that broke. On a test cohort
whose age to eGFR correlation had been destroyed outright, from -0.599 to
+0.017, the mean based score read 98.3 percent. Rebuilt on RMS and max, the
same cohort scores 82.1.

Measured on the reference population, 6000 rows, nine features:

| scenario | overall | marginal | shape | dependency |
| --- | --- | --- | --- | --- |
| Generator against its own seed | 99.21 | 98.93 | 99.65 | 99.06 |
| Marginals kept, three columns shuffled | 94.97 | 98.93 | 99.65 | 82.09 |
| Unrelated cohort, same schema | 66.41 | | | |

The middle row is the point. Both marginal tests are unchanged, because
shuffling a column within itself preserves its distribution exactly. Only the
dependency check moves. That is the test doing the job the other two
structurally cannot.

Full method in [docs/synthetic-data-methodology.md](docs/synthetic-data-methodology.md).

## Repository layout

```
apps/web              Next.js 14 frontend
packages/shared-types Types mirroring the service schemas
packages/fhir-client  Read side FHIR helpers and the push guard
services/synthecore   Generation, screening, job pipeline
services/fidelitycheck Statistical validation
services/fhirlink     FHIR R4 export gateway
infra/                docker-compose and Terraform
docs/                 Architecture, methodology, export guide
```

## API

Every response from every service is the same envelope:

```json
{ "data": {}, "error": null, "meta": { "service": "...", "request_id": "..." } }
```

`data` is null on failure, `error` is null on success.

| service | endpoints |
| --- | --- |
| SyntheCore | `POST /generate`, `GET /jobs`, `GET /jobs/{id}`, `GET /jobs/{id}/stream`, `GET /jobs/{id}/cohort`, `POST /seed/upload`, `GET /engine` |
| FidelityCheck | `POST /validate`, `POST /validate/preview` |
| FHIR-Link | `POST /export`, `POST /export/download`, `POST /export/preview`, `GET /formats`, `GET /terminology` |

## Data handling

- Direct identifiers are stripped during seed parsing, before the generator
  sees the frame. The pattern list includes date of birth. Columns unique in
  every row are dropped as structural identifiers.
- Seed rows never return to the browser. Upload responds with an object key
  and a profile.
- FidelityCheck and FHIR-Link are stateless. Nothing they receive is written
  to disk.
- Every exported FHIR resource carries the HL7 `HTEST` security label. It is
  not configurable, and it is verified again in the browser before download.
- `*.csv`, `*.parquet`, and `seed_data/` are gitignored, and CI fails if any
  are committed.

## Known gaps

- No authentication anywhere. Do not deploy outside a private network.
- The job list endpoint is a Redis key scan. Correct at single deployment
  scale, wrong at multi tenant scale. Postgres is the replacement.
- Feature typing is heuristic: a numeric column with 10 or fewer distinct
  values is treated as categorical. Right for ECOG, wrong for a coarsely
  rounded lab value.
- Datetime columns are unsupported, so longitudinal data is out of scope.
- Validation samples at 20,000 rows per side.
- No component tests on the frontend.
- Terraform is unproven.

## Licence and status

Not licensed for production clinical use. Synthetic cohorts generated here
are decision support for feasibility work. They are not patient records and
they are not a substitute for a real recruitment assessment.
