"""Synthetic cohort rows to FHIR R4 Patient bundles.

One row becomes one Patient resource plus one Observation per recorded
feature. Resources are constructed through `fhir.resources` rather than
assembled as dictionaries, so a bundle that leaves this service has been
through the library's own structural validation and will not fail at the
receiving end on a shape error.

On the R4B import path: `fhir.resources` publishes R4B under
`fhir.resources.R4B`. R4B is the maintenance release of R4, and for Patient,
Observation, and Bundle the wire format is identical to R4.0.1. A receiving
system expecting R4 accepts these bundles unchanged.

Two things every bundle carries, without an option to turn them off:

  meta.security = HTEST   The HL7 v3 ActReason code for test health data.
                          This is the standard signal that a resource is not
                          a real patient record. A synthetic cohort landing
                          in a hospital data warehouse without it is a
                          serious problem, so it is not configurable.

  meta.tag                Names the cohort job that produced the row, so a
                          resource found later can be traced to the run and
                          the validation report behind it.

Identifiers are derived from the cohort job id and the row index, which makes
the export reproducible: re-running it produces byte identical resource ids
rather than a fresh set of UUIDs that break every downstream reference.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from fhir.resources.R4B.bundle import Bundle, BundleEntry, BundleEntryRequest
from fhir.resources.R4B.codeableconcept import CodeableConcept
from fhir.resources.R4B.coding import Coding
from fhir.resources.R4B.identifier import Identifier
from fhir.resources.R4B.meta import Meta
from fhir.resources.R4B.observation import Observation
from fhir.resources.R4B.patient import Patient
from fhir.resources.R4B.quantity import Quantity
from fhir.resources.R4B.reference import Reference

logger = logging.getLogger(__name__)

LOINC_SYSTEM = "http://loinc.org"
UCUM_SYSTEM = "http://unitsofmeasure.org"
SECURITY_SYSTEM = "http://terminology.hl7.org/CodeSystem/v3-ActReason"
OBSERVATION_CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/observation-category"

# Features with no LOINC equivalent are still exported, under a code system
# that is obviously local. Inventing a plausible looking LOINC code for an
# unmapped field is the worst available option: it survives validation and
# then means the wrong thing in someone else's warehouse.
LOCAL_SYSTEM = "https://pretrial.ai/fhir/CodeSystem/cohort-feature"
PATIENT_IDENTIFIER_SYSTEM = "https://pretrial.ai/fhir/sid/synthetic-patient"


@dataclass(frozen=True)
class FeatureSpec:
    code: str
    display: str
    system: str = LOINC_SYSTEM
    unit: str | None = None
    ucum: str | None = None
    category: str = "laboratory"


# Starter terminology map. It covers the features that show up in most
# cardiometabolic and oncology feasibility work. It is not a complete
# terminology binding and it has not been through a terminology review, which
# is stated here and in docs/fhir-export-guide.md so nobody discovers it
# during an integration.
FEATURE_MAP: dict[str, FeatureSpec] = {
    "age": FeatureSpec("30525-0", "Age", unit="years", ucum="a", category="survey"),
    "bmi": FeatureSpec("39156-5", "Body mass index", unit="kg/m2", ucum="kg/m2", category="vital-signs"),
    "weight": FeatureSpec("29463-7", "Body weight", unit="kg", ucum="kg", category="vital-signs"),
    "height": FeatureSpec("8302-2", "Body height", unit="cm", ucum="cm", category="vital-signs"),
    "systolic_bp": FeatureSpec("8480-6", "Systolic blood pressure", unit="mmHg", ucum="mm[Hg]", category="vital-signs"),
    "diastolic_bp": FeatureSpec("8462-4", "Diastolic blood pressure", unit="mmHg", ucum="mm[Hg]", category="vital-signs"),
    "heart_rate": FeatureSpec("8867-4", "Heart rate", unit="/min", ucum="/min", category="vital-signs"),
    "hba1c": FeatureSpec("4548-4", "Hemoglobin A1c in blood", unit="%", ucum="%"),
    "glucose": FeatureSpec("2345-7", "Glucose in serum or plasma", unit="mg/dL", ucum="mg/dL"),
    "creatinine": FeatureSpec("2160-0", "Creatinine in serum or plasma", unit="mg/dL", ucum="mg/dL"),
    "egfr": FeatureSpec("62238-1", "Glomerular filtration rate predicted by CKD-EPI", unit="mL/min/1.73m2", ucum="mL/min/{1.73_m2}"),
    "ldl": FeatureSpec("2089-1", "LDL cholesterol in serum or plasma", unit="mg/dL", ucum="mg/dL"),
    "hdl": FeatureSpec("2085-9", "HDL cholesterol in serum or plasma", unit="mg/dL", ucum="mg/dL"),
    "total_cholesterol": FeatureSpec("2093-3", "Total cholesterol in serum or plasma", unit="mg/dL", ucum="mg/dL"),
    "triglycerides": FeatureSpec("2571-8", "Triglycerides in serum or plasma", unit="mg/dL", ucum="mg/dL"),
    "alt": FeatureSpec("1742-6", "Alanine aminotransferase in serum or plasma", unit="U/L", ucum="U/L"),
    "ast": FeatureSpec("1920-8", "Aspartate aminotransferase in serum or plasma", unit="U/L", ucum="U/L"),
    "hemoglobin": FeatureSpec("718-7", "Hemoglobin in blood", unit="g/dL", ucum="g/dL"),
    "platelets": FeatureSpec("777-3", "Platelets in blood", unit="10*3/uL", ucum="10*3/uL"),
    "wbc": FeatureSpec("6690-2", "Leukocytes in blood", unit="10*3/uL", ucum="10*3/uL"),
    "ecog_status": FeatureSpec("89247-1", "ECOG performance status score", category="survey"),
    "smoking_status": FeatureSpec("72166-2", "Tobacco smoking status", category="social-history"),
}

# Column names that carry demographic meaning rather than an observation.
SEX_COLUMNS = {"sex", "gender", "administrative_gender"}
AGE_COLUMNS = {"age", "age_years", "age_at_screening"}

GENDER_VALUES = {
    "f": "female", "female": "female", "w": "female", "2": "female",
    "m": "male", "male": "male", "1": "male",
    "o": "other", "other": "other", "nonbinary": "other", "non_binary": "other",
    "u": "unknown", "unknown": "unknown", "": "unknown",
}


@dataclass
class BundleReport:
    """What the export actually produced, for the caller and the audit log."""

    patients: int
    observations: int
    mapped_features: list[str] = field(default_factory=list)
    unmapped_features: list[str] = field(default_factory=list)
    skipped_features: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "patients": self.patients,
            "observations": self.observations,
            "mapped_features": self.mapped_features,
            "unmapped_features": self.unmapped_features,
            "skipped_features": self.skipped_features,
            "warnings": self.warnings,
        }


# FHIR constrains Resource.id to [A-Za-z0-9-.]{1,64}. Underscores are not
# permitted, and clinical feature names are full of them, so anything used to
# build an id goes through this first.
_ID_ILLEGAL = re.compile(r"[^A-Za-z0-9\-.]+")
FHIR_ID_MAX_LENGTH = 64


def sanitise_id_part(value: str) -> str:
    """Make a fragment safe to embed in a FHIR resource id."""
    cleaned = _ID_ILLEGAL.sub("-", str(value)).strip("-")
    return cleaned or "x"


def synthetic_id(cohort_id: str, index: int, prefix: str = "pt") -> str:
    """Stable, opaque resource id.

    Hashed rather than sequential so a resource id cannot be used to infer
    the row's position in the cohort, and deterministic so re-exporting the
    same cohort does not renumber every patient.

    The hash is taken over the raw cohort id, not the sanitised one, so two
    cohorts whose ids differ only in punctuation cannot collide.
    """
    digest = hashlib.sha256(f"{cohort_id}:{index}".encode()).hexdigest()[:16]
    safe_prefix = sanitise_id_part(prefix)[: FHIR_ID_MAX_LENGTH - len(digest) - 1]
    return f"{safe_prefix}-{digest}"


def _meta(cohort_id: str) -> Meta:
    return Meta(
        security=[
            Coding(
                system=SECURITY_SYSTEM,
                code="HTEST",
                display="test health data",
            )
        ],
        tag=[
            Coding(
                system="https://pretrial.ai/fhir/CodeSystem/cohort",
                code=cohort_id,
                display="Pretrial.ai synthetic cohort",
            )
        ],
    )


def _normalise_gender(value: Any) -> str:
    if value is None:
        return "unknown"
    return GENDER_VALUES.get(str(value).strip().lower(), "other")


def _birth_date_from_age(age: Any, as_of: date) -> date | None:
    """Year precision birth date derived from age.

    Only the year carries information. Day and month are fixed to 1 January
    rather than randomised, because a randomised day looks like real
    precision that is not there.
    """
    try:
        years = int(round(float(age)))
    except (TypeError, ValueError):
        return None
    if not 0 <= years <= 120:
        return None
    return date(as_of.year - years, 1, 1)


def _category(spec: FeatureSpec) -> CodeableConcept:
    return CodeableConcept(
        coding=[Coding(system=OBSERVATION_CATEGORY_SYSTEM, code=spec.category)]
    )


def _observation(
    cohort_id: str,
    row_index: int,
    feature: str,
    value: Any,
    patient_id: str,
    spec: FeatureSpec | None,
    effective: date,
) -> Observation | None:
    """One Observation, or None when the value is not exportable."""
    if value is None or (isinstance(value, float) and value != value):
        return None

    resolved = spec or FeatureSpec(
        code=feature, display=feature.replace("_", " "), system=LOCAL_SYSTEM, category="survey"
    )

    observation = Observation(
        id=synthetic_id(cohort_id, row_index, prefix=f"obs-{feature}"),
        meta=_meta(cohort_id),
        status="final",
        category=[_category(resolved)],
        code=CodeableConcept(
            coding=[
                Coding(
                    system=resolved.system,
                    code=resolved.code,
                    display=resolved.display,
                )
            ],
            text=feature,
        ),
        subject=Reference(reference=f"Patient/{patient_id}"),
        effectiveDateTime=f"{effective.isoformat()}T00:00:00+00:00",
    )

    if isinstance(value, bool):
        observation.valueBoolean = value
        return observation

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        observation.valueString = str(value)
        return observation

    if numeric != numeric:  # NaN that survived the float() call
        return None

    observation.valueQuantity = Quantity(
        value=round(numeric, 6),
        unit=resolved.unit,
        system=UCUM_SYSTEM if resolved.ucum else None,
        code=resolved.ucum,
    )
    return observation


def build_patient(
    row: dict[str, Any],
    row_index: int,
    cohort_id: str,
    as_of: date,
) -> tuple[Patient, list[str]]:
    """One Patient resource, plus the feature names it consumed."""
    patient_id = synthetic_id(cohort_id, row_index)
    consumed: list[str] = []

    patient = Patient(
        id=patient_id,
        meta=_meta(cohort_id),
        identifier=[
            Identifier(
                system=PATIENT_IDENTIFIER_SYSTEM,
                value=patient_id,
                use="secondary",
            )
        ],
        # Explicitly false. A synthetic record is not an active patient in
        # any care setting, and leaving this unset invites a receiving system
        # to default it to true.
        active=False,
    )

    for column in row:
        if column.lower() in SEX_COLUMNS:
            patient.gender = _normalise_gender(row[column])
            consumed.append(column)
            break

    for column in row:
        if column.lower() in AGE_COLUMNS:
            birth = _birth_date_from_age(row[column], as_of)
            if birth is not None:
                patient.birthDate = birth
                consumed.append(column)
            break

    return patient, consumed


def build_bundle(
    rows: list[dict[str, Any]],
    cohort_id: str,
    bundle_type: str = "collection",
    as_of: date | None = None,
    include_observations: bool = True,
) -> tuple[Bundle, BundleReport]:
    """Build one FHIR bundle from a synthetic cohort.

    `bundle_type` of "transaction" adds a request element per entry so the
    bundle can be POSTed to a FHIR server root and ingested in one call.
    "collection" omits it, which is the right choice for a file handed to an
    analyst rather than to a server.
    """
    effective = as_of or date.today()
    entries: list[BundleEntry] = []
    observation_count = 0

    mapped: set[str] = set()
    unmapped: set[str] = set()
    skipped: set[str] = set()
    warnings: list[str] = []

    for index, row in enumerate(rows):
        patient, consumed = build_patient(row, index, cohort_id, effective)
        entries.append(_entry(patient, bundle_type))

        if not include_observations:
            continue

        for column, value in row.items():
            if column in consumed:
                continue

            spec = FEATURE_MAP.get(column.lower())
            observation = _observation(
                cohort_id, index, column, value, patient.id, spec, effective
            )
            if observation is None:
                skipped.add(column)
                continue

            if spec is None:
                unmapped.add(column)
            else:
                mapped.add(column)

            entries.append(_entry(observation, bundle_type))
            observation_count += 1

    if unmapped:
        warnings.append(
            "Features exported under the Pretrial.ai local code system because no "
            f"LOINC mapping is configured: {', '.join(sorted(unmapped))}. A receiving "
            "system will not recognise these codes without a mapping."
        )
    if skipped:
        warnings.append(
            f"Values omitted where the source was null: {', '.join(sorted(skipped))}"
        )

    bundle = Bundle(
        id=sanitise_id_part(f"cohort-{cohort_id}")[:FHIR_ID_MAX_LENGTH],
        meta=_meta(cohort_id),
        type=bundle_type,
        timestamp=f"{effective.isoformat()}T00:00:00+00:00",
        total=len(entries) if bundle_type in {"searchset", "history"} else None,
        entry=entries,
    )

    report = BundleReport(
        patients=len(rows),
        observations=observation_count,
        mapped_features=sorted(mapped),
        unmapped_features=sorted(unmapped),
        skipped_features=sorted(skipped),
        warnings=warnings,
    )

    return bundle, report


def _entry(resource: Any, bundle_type: str) -> BundleEntry:
    full_url = f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, resource.id)}"
    entry = BundleEntry(fullUrl=full_url, resource=resource)
    if bundle_type in {"transaction", "batch"}:
        # PUT against a known id rather than POST. Re-sending a bundle after a
        # partial failure then updates in place instead of creating a second
        # copy of every patient that already landed.
        entry.request = BundleEntryRequest(
            method="PUT",
            url=f"{resource.resource_type}/{resource.id}",
        )
    return entry


def bundle_to_dict(bundle: Bundle) -> dict[str, Any]:
    """FHIR JSON as plain Python types.

    Round trips through the library's own JSON writer because a direct dict
    export leaves date objects and enum members in the payload, which the API
    layer then cannot serialise.
    """
    import json

    return json.loads(bundle.json(exclude_none=True))


def bundle_to_ndjson(bundle: Bundle) -> str:
    """One resource per line, the FHIR Bulk Data export shape.

    Hospital ingestion pipelines built on the Bulk Data spec stream this
    rather than parsing one large bundle into memory, which matters at
    100k patients.
    """
    import json

    lines = []
    for entry in bundle.entry or []:
        if entry.resource is None:
            continue
        lines.append(json.dumps(json.loads(entry.resource.json(exclude_none=True))))
    return "\n".join(lines)
