"""Tests for FHIR bundle construction.

The assertions that matter here are the compliance ones: every resource
carries the HTEST security label, ids are deterministic, and unmapped
features never quietly acquire a LOINC code.
"""

from __future__ import annotations

import json
import re
from datetime import date

import pytest

from app.engine.bundle_builder import (
    FEATURE_MAP,
    LOCAL_SYSTEM,
    LOINC_SYSTEM,
    SECURITY_SYSTEM,
    build_bundle,
    build_patient,
    bundle_to_dict,
    bundle_to_ndjson,
    synthetic_id,
)
from app.engine.format_registry import get_format, list_formats, render_bundle, render_csv

AS_OF = date(2026, 1, 1)

ROWS = [
    {
        "age": 64,
        "sex": "female",
        "hba1c": 7.8,
        "egfr": 72.4,
        "systolic_bp": 138,
        "on_insulin": True,
        "trial_site_region": "nordics",
    },
    {
        "age": 71,
        "sex": "male",
        "hba1c": 8.9,
        "egfr": 55.1,
        "systolic_bp": 149,
        "on_insulin": False,
        "trial_site_region": "iberia",
    },
]


class TestPatientResource:
    def test_gender_is_mapped_to_the_fhir_value_set(self):
        for raw, expected in [
            ("female", "female"), ("F", "female"), ("M", "male"),
            ("male", "male"), ("unknown", "unknown"), (None, "unknown"),
        ]:
            patient, _ = build_patient({"sex": raw}, 0, "c1", AS_OF)
            assert patient.gender == expected

    def test_unrecognised_gender_becomes_other_not_a_crash(self):
        patient, _ = build_patient({"sex": "intersex-variant"}, 0, "c1", AS_OF)
        assert patient.gender == "other"

    def test_birth_date_is_derived_at_year_precision(self):
        patient, consumed = build_patient({"age": 64}, 0, "c1", AS_OF)
        assert patient.birthDate == date(1962, 1, 1)
        assert "age" in consumed

    def test_impossible_age_produces_no_birth_date(self):
        patient, consumed = build_patient({"age": 480}, 0, "c1", AS_OF)
        assert patient.birthDate is None
        assert consumed == []

    def test_patient_is_marked_inactive(self):
        patient, _ = build_patient(ROWS[0], 0, "c1", AS_OF)
        assert patient.active is False

    def test_ids_are_deterministic_across_runs(self):
        assert synthetic_id("cohort-a", 5) == synthetic_id("cohort-a", 5)
        assert synthetic_id("cohort-a", 5) != synthetic_id("cohort-b", 5)
        assert synthetic_id("cohort-a", 5) != synthetic_id("cohort-a", 6)

    def test_ids_do_not_leak_the_row_index(self):
        assert "5" not in synthetic_id("cohort-a", 5).split("-")[0]
        assert not synthetic_id("cohort-a", 5).endswith("-5")

    def test_ids_satisfy_the_fhir_id_constraint(self):
        # FHIR restricts Resource.id to [A-Za-z0-9-.]{1,64}. Feature names
        # carry underscores, so ids built from them have to be sanitised or
        # the resource fails validation on construction.
        pattern = re.compile(r"^[A-Za-z0-9\-.]{1,64}$")
        for feature in ("systolic_bp", "prior_cv_event", "hba1c", "trial site (EU)"):
            generated = synthetic_id("coh_9f2b", 3, prefix=f"obs-{feature}")
            assert pattern.match(generated), generated

    def test_cohort_ids_differing_only_in_punctuation_do_not_collide(self):
        assert synthetic_id("coh_1", 0) != synthetic_id("coh-1", 0)


class TestBundle:
    def test_every_resource_carries_the_synthetic_data_label(self):
        bundle, _ = build_bundle(ROWS, "c1", as_of=AS_OF)
        payload = bundle_to_dict(bundle)

        assert payload["meta"]["security"][0]["code"] == "HTEST"
        assert payload["meta"]["security"][0]["system"] == SECURITY_SYSTEM

        for entry in payload["entry"]:
            security = entry["resource"]["meta"]["security"]
            assert security[0]["code"] == "HTEST", entry["resource"]["resourceType"]

    def test_bundle_holds_one_patient_per_row(self):
        bundle, report = build_bundle(ROWS, "c1", as_of=AS_OF)
        payload = bundle_to_dict(bundle)
        patients = [e for e in payload["entry"] if e["resource"]["resourceType"] == "Patient"]
        assert len(patients) == 2
        assert report.patients == 2

    def test_observations_reference_their_patient(self):
        bundle, _ = build_bundle(ROWS, "c1", as_of=AS_OF)
        payload = bundle_to_dict(bundle)
        patient_ids = {
            e["resource"]["id"]
            for e in payload["entry"]
            if e["resource"]["resourceType"] == "Patient"
        }
        observations = [
            e["resource"] for e in payload["entry"]
            if e["resource"]["resourceType"] == "Observation"
        ]
        assert observations
        for observation in observations:
            referenced = observation["subject"]["reference"].split("/", 1)[1]
            assert referenced in patient_ids

    def test_mapped_features_get_loinc_codes(self):
        bundle, report = build_bundle(ROWS, "c1", as_of=AS_OF)
        payload = bundle_to_dict(bundle)
        hba1c = next(
            e["resource"] for e in payload["entry"]
            if e["resource"]["resourceType"] == "Observation"
            and e["resource"]["code"]["text"] == "hba1c"
        )
        coding = hba1c["code"]["coding"][0]
        assert coding["system"] == LOINC_SYSTEM
        assert coding["code"] == FEATURE_MAP["hba1c"].code
        assert hba1c["valueQuantity"]["code"] == "%"
        assert "hba1c" in report.mapped_features

    def test_unmapped_features_use_the_local_system_and_are_reported(self):
        bundle, report = build_bundle(ROWS, "c1", as_of=AS_OF)
        payload = bundle_to_dict(bundle)
        region = next(
            e["resource"] for e in payload["entry"]
            if e["resource"]["resourceType"] == "Observation"
            and e["resource"]["code"]["text"] == "trial_site_region"
        )
        # The important half of this assertion is the negative one. An
        # unmapped feature must never come out wearing a LOINC code.
        assert region["code"]["coding"][0]["system"] == LOCAL_SYSTEM
        assert region["code"]["coding"][0]["system"] != LOINC_SYSTEM
        assert "trial_site_region" in report.unmapped_features
        assert any("local code system" in w for w in report.warnings)

    def test_booleans_become_value_boolean(self):
        bundle, _ = build_bundle(ROWS, "c1", as_of=AS_OF)
        payload = bundle_to_dict(bundle)
        insulin = [
            e["resource"] for e in payload["entry"]
            if e["resource"]["resourceType"] == "Observation"
            and e["resource"]["code"]["text"] == "on_insulin"
        ]
        assert {o["valueBoolean"] for o in insulin} == {True, False}

    def test_null_values_are_skipped_not_exported_as_null(self):
        rows = [{"age": 60, "sex": "male", "hba1c": None}]
        bundle, report = build_bundle(rows, "c1", as_of=AS_OF)
        payload = bundle_to_dict(bundle)
        codes = [
            e["resource"]["code"]["text"]
            for e in payload["entry"]
            if e["resource"]["resourceType"] == "Observation"
        ]
        assert "hba1c" not in codes
        assert "hba1c" in report.skipped_features

    def test_transaction_bundle_carries_idempotent_put_requests(self):
        bundle, _ = build_bundle(ROWS, "c1", bundle_type="transaction", as_of=AS_OF)
        payload = bundle_to_dict(bundle)
        assert payload["type"] == "transaction"
        for entry in payload["entry"]:
            assert entry["request"]["method"] == "PUT"
            assert entry["request"]["url"].startswith(
                (f"{entry['resource']['resourceType']}/",)
            )

    def test_collection_bundle_has_no_request_elements(self):
        bundle, _ = build_bundle(ROWS, "c1", bundle_type="collection", as_of=AS_OF)
        payload = bundle_to_dict(bundle)
        assert all("request" not in e for e in payload["entry"])

    def test_patient_only_export_omits_observations(self):
        bundle, report = build_bundle(
            ROWS, "c1", as_of=AS_OF, include_observations=False
        )
        payload = bundle_to_dict(bundle)
        assert report.observations == 0
        assert all(e["resource"]["resourceType"] == "Patient" for e in payload["entry"])

    def test_export_is_reproducible_for_a_fixed_reference_date(self):
        first = bundle_to_dict(build_bundle(ROWS, "c1", as_of=AS_OF)[0])
        second = bundle_to_dict(build_bundle(ROWS, "c1", as_of=AS_OF)[0])
        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    def test_ndjson_emits_one_resource_per_line(self):
        bundle, _ = build_bundle(ROWS, "c1", as_of=AS_OF)
        lines = bundle_to_ndjson(bundle).splitlines()
        assert len(lines) == len(bundle.entry)
        for line in lines:
            parsed = json.loads(line)
            assert "resourceType" in parsed
            assert parsed["meta"]["security"][0]["code"] == "HTEST"


class TestFormatRegistry:
    def test_every_format_is_described(self):
        for fmt in list_formats():
            assert fmt["id"] and fmt["label"] and fmt["media_type"] and fmt["description"]

    def test_unknown_format_is_rejected(self):
        with pytest.raises(ValueError, match="unknown export format"):
            get_format("xml_hl7v2")

    def test_fhir_formats_declare_the_fhir_media_type(self):
        for name in ("fhir_r4_collection", "fhir_r4_transaction", "fhir_r4_ndjson"):
            assert get_format(name).media_type.startswith("application/fhir+")

    def test_rendered_collection_bundle_is_valid_json(self):
        bundle, _ = build_bundle(ROWS, "c1", as_of=AS_OF)
        parsed = json.loads(render_bundle(bundle, get_format("fhir_r4_collection")))
        assert parsed["resourceType"] == "Bundle"

    def test_csv_export_is_flat_and_has_a_header(self):
        content = render_csv(ROWS)
        header = content.splitlines()[0]
        assert header.split(",")[:2] == ["age", "sex"]
        assert len(content.splitlines()) == len(ROWS) + 1
