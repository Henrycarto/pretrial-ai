# FHIR export guide

FHIR-Link converts a validated synthetic cohort into FHIR R4 resources a
hospital network or a clinical trial management system can ingest.

## The one thing that is not configurable

Every resource FHIR-Link emits carries this security label:

```json
{
  "meta": {
    "security": [{
      "system": "http://terminology.hl7.org/CodeSystem/v3-ActReason",
      "code": "HTEST",
      "display": "test health data"
    }]
  }
}
```

`HTEST` is the HL7 v3 ActReason code for test health data. It is the standard
signal that a resource is not a real patient record, and receiving systems
key their handling off it.

There is no flag to turn this off. A synthetic patient record landing in a
production data warehouse without it is the single worst outcome this product
can produce. The check is enforced in three places: the builder always
applies it, the browser preview re-verifies every resource independently
before an operator downloads anything, and `pushBundle` in
`@pretrial/fhir-client` refuses to transmit a bundle where any resource is
missing it.

Every resource also carries a `meta.tag` naming the cohort job that produced
it, so a resource found later can be traced back to the run and to the
validation report behind it.

## R4 and R4B

The `fhir.resources` library publishes R4B under `fhir.resources.R4B`, and
that is what this service builds against. R4B is the maintenance release of
R4, and for Patient, Observation, and Bundle the wire format is identical to
R4.0.1. A receiving system expecting R4 accepts these bundles unchanged.

Resources are constructed through the library rather than assembled as
dictionaries, so anything that leaves this service has passed the library's
structural validation. That is not theoretical: the first version of the id
scheme embedded the feature name in the resource id, which produced
`obs-systolic_bp-...`, and FHIR restricts `Resource.id` to
`[A-Za-z0-9\-.]{1,64}`. The library rejected it at construction time.
Hand rolled dictionaries would have shipped it.

## Mapping

### Patient

| source | FHIR element | notes |
| --- | --- | --- |
| `sex`, `gender` | `Patient.gender` | Mapped to the R4 value set. Unrecognised values become `other`, missing becomes `unknown` |
| `age` | `Patient.birthDate` | Derived at year precision |
| resource id | `Patient.identifier` | System `https://pretrial.ai/fhir/sid/synthetic-patient`, use `secondary` |
| always | `Patient.active` = `false` | A synthetic record is not an active patient in any care setting |

**Birth dates carry only a year.** The value is `YYYY-01-01`, computed from
the age and the export's reference date. Day and month are fixed rather than
randomised, because a randomised day looks like precision that is not there.
Pass `as_of` to make an export byte reproducible.

### Observation

One Observation per recorded feature, `status: final`, `subject` referencing
the Patient, `effectiveDateTime` set from the export reference date.

Numeric values become `valueQuantity` with a UCUM unit code. Booleans become
`valueBoolean`. Anything else becomes `valueString`. Null values produce no
Observation at all, rather than an Observation with a null value, and the
export report lists which features were skipped.

### Terminology

Features in the map get a LOINC code. The current map covers common
cardiometabolic and oncology feasibility fields:

| feature | LOINC | unit |
| --- | --- | --- |
| `age` | 30525-0 | a |
| `bmi` | 39156-5 | kg/m2 |
| `weight` | 29463-7 | kg |
| `height` | 8302-2 | cm |
| `systolic_bp` | 8480-6 | mm[Hg] |
| `diastolic_bp` | 8462-4 | mm[Hg] |
| `heart_rate` | 8867-4 | /min |
| `hba1c` | 4548-4 | % |
| `glucose` | 2345-7 | mg/dL |
| `creatinine` | 2160-0 | mg/dL |
| `egfr` | 62238-1 | mL/min/{1.73_m2} |
| `ldl` | 2089-1 | mg/dL |
| `hdl` | 2085-9 | mg/dL |
| `total_cholesterol` | 2093-3 | mg/dL |
| `triglycerides` | 2571-8 | mg/dL |
| `alt` | 1742-6 | U/L |
| `ast` | 1920-8 | U/L |
| `hemoglobin` | 718-7 | g/dL |
| `platelets` | 777-3 | 10*3/uL |
| `wbc` | 6690-2 | 10*3/uL |
| `ecog_status` | 89247-1 | |
| `smoking_status` | 72166-2 | |

The live map is served at `GET /terminology`, so an integration partner can
review it before ingesting anything.

**This map has not been through a formal terminology review.** Check it
against the receiving system's value sets before production ingestion. It is
a starter set, not a binding.

### Unmapped features

A feature with no LOINC entry is still exported, under
`https://pretrial.ai/fhir/CodeSystem/cohort-feature`. The export report names
every feature that took this path and the UI shows them.

Inventing a plausible looking LOINC code for an unmapped field would be the
worst available option: it passes validation and then means the wrong thing
in someone else's warehouse. An obviously local code system is honest and
fails loudly at the receiving end.

## Formats

`GET /formats` returns the live list. The export panel is driven from it.

| id | media type | when to use |
| --- | --- | --- |
| `fhir_r4_collection` | `application/fhir+json` | Review, handing to an analyst, import tools that read a whole file |
| `fhir_r4_transaction` | `application/fhir+json` | POST to a FHIR server root for ingestion in one call |
| `fhir_r4_ndjson` | `application/fhir+ndjson` | Above roughly 10,000 patients, where one bundle stops being practical to parse |
| `csv_flat` | `text/csv` | Statisticians who want the table and nothing else |

**CSV carries no synthetic data marker.** There is nowhere in a flat CSV to
put one. The export report says so explicitly on every CSV export. Only the
FHIR formats are self describing.

### Transaction bundles use PUT, not POST

Every entry in a transaction bundle carries
`request: { method: "PUT", url: "Patient/<id>" }`.

PUT against a known id rather than POST means re-sending a bundle after a
partial failure updates in place instead of creating a second copy of every
patient that already landed. Resource ids are deterministic, derived from a
SHA-256 of the cohort id and the row index, so a re-export produces byte
identical ids rather than a fresh set of UUIDs that break every reference
downstream.

The hash is taken over the raw cohort id rather than the sanitised one, so
two cohorts whose ids differ only in punctuation cannot collide.

## The fidelity gate

`POST /export` refuses a cohort scoring below 70 percent:

```
409 Conflict
{
  "data": null,
  "error": {
    "code": "fidelity_below_export_floor",
    "message": "Cohort fidelity is 41.2 percent, below the 70 percent export floor..."
  },
  "meta": { }
}
```

Re-send with `acknowledge_low_fidelity: true` to proceed. The
acknowledgement is recorded in the response metadata so it lands in the audit
log alongside the export.

Exporting a cohort that failed its own validation should be possible, because
sometimes it is the right call. It should never be accidental. The UI
surfaces the override as a second, separate action rather than a checkbox
that can be ticked in advance.

## Example

```bash
curl -X POST http://localhost:8003/export \
  -H 'Content-Type: application/json' \
  -d '{
    "rows": [{"age": 64, "sex": "female", "hba1c": 7.8, "egfr": 72.4}],
    "cohort_id": "coh_9f2b1c",
    "format": "fhir_r4_collection",
    "fidelity_score": 94.7,
    "as_of": "2026-01-01"
  }'
```

Returns the serialised bundle in `data.content`, with `data.bundle` reporting
patient and observation counts, which features were mapped, which fell back
to the local code system, and which were skipped as null.

`POST /export/download` runs the same conversion and returns the file body
with a `Content-Disposition` header, for streaming a large bundle straight to
disk.

## Pushing to a FHIR server

`pushBundle` in `@pretrial/fhir-client` posts a transaction bundle to a
server root with a SMART on FHIR bearer token. It throws before making the
request if any resource is missing the HTEST marker.

The SMART on FHIR authorisation flow that would supply that token is not
implemented. Obtaining the token is currently the caller's problem.

## Limitations

- Patient and Observation only. No Condition, MedicationStatement,
  Procedure, or Encounter resources.
- No `us-core` or any other implementation guide profile conformance.
- Booleans become Observations with `valueBoolean` rather than Conditions.
  Mapping `prior_cv_event` to a Condition would require inventing a SNOMED
  code, and a wrong SNOMED code is worse than an honest local one.
- Datetime source columns are unsupported upstream in SyntheCore, so there is
  nothing longitudinal to export.
- No bulk export async job. Above a few hundred thousand patients the NDJSON
  format is the right shape but the delivery mechanism is still a single
  HTTP response.
