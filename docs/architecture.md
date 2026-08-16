# Architecture

## Shape of the system

Three Python services and one Next.js frontend. The services do not share a
database and do not import each other's code. They talk over HTTP and they
each answer in the same response envelope.

```
                          browser
                             |
                        Next.js (3000)
                             |
        +--------------------+--------------------+
        |                    |                    |
  SyntheCore (8001)   FidelityCheck (8002)   FHIR-Link (8003)
        |                    ^                    
        |                    |                    
   enqueue job          validate cohort           
        |                    |                    
        v                    |                    
   Redis broker              |                    
        |                    |                    
        v                    |                    
  Celery worker -------------+                    
        |
        +--> Postgres (job records, audit log)
        +--> S3 (seed uploads, cohort exports)
```

## Why three services and not one

Not for the usual reason. The three have genuinely different runtime
profiles, and that is the whole argument:

**SyntheCore** runs jobs that take minutes and need a lot of memory. A CTGAN
fit on a wide clinical schema is the heaviest thing here. It needs a queue,
a worker fleet that scales on queue depth, and a task size nothing else
needs.

**FidelityCheck** is CPU bound in short bursts. A validation on a 100k row
cohort is seconds of scipy, not minutes. It scales on request rate and it
holds no state at all.

**FHIR-Link** is close to free. It is a mapping function with a validating
serialiser behind it.

Running these in one process means sizing one container for the worst case
of all three and paying for it constantly. It also means a memory hungry
CTGAN fit can take down the endpoint that answers validation requests.

The second reason is the public and private split. SyntheCore is the service
with proprietary code in it. FidelityCheck and FHIR-Link are fully open. That
boundary is cleaner when it is a service boundary.

## The stateless rule

FidelityCheck and FHIR-Link keep nothing. Datasets arrive in the request
body, results go back in the response, nothing touches disk.

This is a deliberate constraint rather than an accident of being small. Both
services handle data derived from real patient records. A service that never
writes cannot leak what it never stored, cannot accumulate a retention
obligation, and does not need its own encryption, backup, or deletion
policy. Persistence is SyntheCore's job, in one place, where the audit log
already lives.

The cost is that large payloads move over the wire more than once. At the
sizes involved, that is cheaper than the alternative.

## Async generation

Generation cannot run inside a request. A real CTGAN fit runs for minutes,
and no reverse proxy in a hospital network will hold a connection open that
long.

The flow:

1. `POST /generate` writes an initial job record to Redis, enqueues a Celery
   task, and returns a job id immediately.
2. The worker runs the four stages, publishing state on each transition.
3. The browser holds `GET /jobs/{id}/stream`, a Server Sent Events feed, and
   renders each stage as it happens.

### Why the progress transport is built the way it is

Every stage transition does two things: it writes the full job state to a
Redis key, and it publishes that same state on a channel.

The write exists because pub/sub has no history. A browser connecting thirty
seconds into a job would otherwise see nothing until the next stage
boundary, and on the training stage that can be minutes of blank screen. The
stream subscribes first, then reads the stored snapshot and emits it as the
opening frame, then follows the channel. Subscribing before reading closes
the window where a transition lands between the two operations and is never
seen.

SSE rather than WebSockets because the traffic only goes one way and SSE
survives an ALB and a corporate proxy without special handling. A pharma
network is not the place to discover that WebSocket upgrades are filtered.
The frontend falls back to polling if the stream drops, because a progress
view that silently stops updating is worse than no progress view.

### Stages

The four stages are fixed and the frontend renders whatever the service
sends:

| stage | what happens |
| --- | --- |
| `parse_seed` | Parse the upload, normalise column names, strip direct identifiers, drop unmodellable columns |
| `train_model` | Fit the generator, CTGAN in production or the bootstrap fallback in the public build |
| `sample_cohort` | Sample, screen against the criteria, record the attrition funnel, trim to target |
| `validate` | Call FidelityCheck with the seed and the generated cohort |

Stage names and order live in `services/synthecore/app/progress.py`. They do
not change when the generation engine changes, which is the point: swapping
the stub for CTGAN does not alter the contract the frontend was built
against.

## Storage

| what | where | why |
| --- | --- | --- |
| Job progress and state | Redis, 7 day TTL | Fast, disposable, already the broker |
| Job records, validation reports, audit log | Postgres | Has to survive a cache eviction and be queryable a year later |
| Seed uploads | S3, 30 day lifecycle | The most sensitive thing in the system. Only needed for the fit |
| Generated cohorts | S3 (Redis in local dev) | Large, outlive the job, need a retention policy |

Cohorts are written as Parquet, not JSON. A 50k row cohort is roughly an
order of magnitude smaller and survives the round trip with its dtypes
intact, which JSON does not.

Local development uses Redis for cohorts so that `docker compose up` gives a
working system without an AWS account. The backend is chosen by
`COHORT_STORAGE` and nothing above `storage.py` knows which is active.

## Response envelope

Every response from every service, success or failure:

```json
{
  "data": { },
  "error": { "code": "...", "message": "...", "details": null },
  "meta": { "service": "...", "version": "...", "request_id": "...", "duration_ms": 12.4 }
}
```

`data` is null on failure, `error` is null on success. The frontend unwraps
this once in `lib/api.ts` and callers deal in plain values or a thrown
`ApiRequestError`.

The envelope is duplicated in each service rather than shared through a
package. Each service builds an independent Docker image, and a shared
Python package would force a common build context for the sake of forty
lines.

One thing worth knowing about the implementation: `fail()` runs its payload
through `jsonable_encoder` rather than handing it straight to
`JSONResponse`. Pydantic validation errors carry the original exception
object inside their `ctx`, and plain `json.dumps` raises on it, which turns
a clean 422 into an unhandled 500 and hides the real problem from the
caller. That was a live bug, caught by the end to end smoke test rather than
by any unit test.

## Data protection decisions

**Identifiers are stripped before modelling, not after.** `seed_processor.py`
removes direct identifiers as part of parsing. A generator that never sees an
MRN cannot memorise one. The pattern list is deliberately broad, including
date of birth, because a false positive costs one feature and a false
negative puts an identifier in a released cohort.

**Structural identifiers are dropped too.** A column with a unique value in
every row is an identifier by structure even when its name gives nothing
away.

**Seed rows never return to the browser.** The upload endpoint responds with
the object key and a profile of what was parsed, which is everything the
cohort builder needs and none of the patient data.

**Every exported FHIR resource is tagged HTEST.** This is not configurable.
See `fhir-export-guide.md`.

## What is not built

Stated here rather than left to be discovered:

- **Authentication.** The SMART on FHIR flow is a UI shell. There is no token
  exchange and no session. Every service is reachable without credentials.
  Do not deploy this outside a private network.
- **Postgres is provisioned but unused.** The schema is not written. Job
  records live in Redis with a TTL, so the job list endpoint is a Redis key
  scan, which is correct at single deployment scale and wrong at multi tenant
  scale.
- **The Terraform has never been applied.** It describes the intended
  topology and is reviewed, not proven.
- **No rate limiting, no quotas, no multi tenancy.**

## Local development

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up --build
```

Frontend on 3000, SyntheCore on 8001, FidelityCheck on 8002, FHIR-Link on
8003. Each service serves its own OpenAPI documentation at `/docs`.

The worker runs the same image as the SyntheCore API with the command
overridden, so the code the API validates against and the code the worker
executes cannot drift apart.
