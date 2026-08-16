"""The Celery task that produces a cohort.

Four stages, in the order the UI renders them:

    parse_seed      normalise the seed cohort and strip identifiers
    train_model     fit the generator (CTGAN in production, stub otherwise)
    sample_cohort   sample, screen against the criteria, trim to target
    validate        hand real and synthetic to FidelityCheck for scoring

Every transition is published to Redis, so the pipeline is observable from
the browser whether the fit takes four seconds against the stub or eleven
minutes against CTGAN. The stage list does not change between the two, which
is the point: swapping the engine does not change the contract the frontend
was built against.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx
import pandas as pd

from app.celery_app import celery_app
from app.engine.criteria_filter import (
    apply_criteria,
    criteria_from_payload,
    estimate_oversample_factor,
)
from app.engine.ctgan_pipeline import generator_info, load_generator
from app.engine.seed_processor import process_seed, reference_cohort
from app.progress import ProgressWriter, Stage
from app.storage import frame_to_rows, get_store

logger = logging.getLogger(__name__)

FIDELITYCHECK_URL = os.getenv("FIDELITYCHECK_URL", "http://fidelitycheck:8002")
VALIDATION_TIMEOUT = float(os.getenv("VALIDATION_TIMEOUT_SECONDS", "300"))

# Validation runs on a sample rather than the full cohort. The KS statistic
# stabilises well below this and the request body stays a sane size.
VALIDATION_SAMPLE_CAP = int(os.getenv("VALIDATION_SAMPLE_CAP", "20000"))

PREVIEW_ROWS = 25

# Screening can only reject, so hitting a target eligible count means
# generating more than the target and trimming. Two attempts is enough for
# any realistic eligibility rate; past that the criteria are the problem.
MAX_SAMPLING_ATTEMPTS = 2


@celery_app.task(bind=True, name="synthecore.generate_cohort")
def generate_cohort(self, job_id: str, request: dict[str, Any]) -> dict[str, Any]:
    progress = ProgressWriter(job_id)
    started = time.time()

    try:
        seed_frame, seed_profile = _stage_parse_seed(progress, request)
        generator, engine = _stage_train_model(progress, seed_frame)
        cohort, screening = _stage_sample_cohort(progress, generator, request)
        validation = _stage_validate(
            progress, seed_frame, cohort, job_id, request, criteria_from_payload(request.get("criteria") or [])
        )

        store = get_store()
        location = store.put_cohort(job_id, cohort)

        result = {
            "job_id": job_id,
            "cohort_size": int(len(cohort)),
            "requested_size": int(request.get("cohort_size", len(cohort))),
            "features": list(cohort.columns),
            "engine": {
                "name": engine.name,
                "is_stub": engine.is_stub,
                "detail": engine.detail,
            },
            "seed_profile": seed_profile,
            "screening": screening,
            "validation": validation,
            "storage": {"backend": store.backend, "location": location},
            "preview": frame_to_rows(cohort, PREVIEW_ROWS),
            "duration_seconds": round(time.time() - started, 2),
        }

        progress.succeed(result, message=f"Cohort ready, {len(cohort)} patients")
        return result

    except Exception as exc:  # noqa: BLE001
        logger.exception("generation job %s failed", job_id)
        progress.failure(
            code="generation_failed",
            message=str(exc) or "Cohort generation failed.",
            details={"exception": type(exc).__name__},
        )
        raise


def _stage_parse_seed(
    progress: ProgressWriter, request: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    progress.start_stage(Stage.PARSE_SEED)

    seed_rows = request.get("seed_rows")
    seed_key = request.get("seed_object_key")

    if seed_rows:
        frame, profile = process_seed(rows=seed_rows)
        source = f"inline upload, {len(seed_rows)} rows"
    elif seed_key:
        progress.update_stage(f"Reading seed object {seed_key}")
        content = get_store().get_seed(seed_key)
        frame, profile = process_seed(content=content, filename=seed_key)
        source = seed_key
    else:
        # No seed means demo mode. The reference cohort is a fixture, and the
        # job result says so, so a screenshot of this run cannot be mistaken
        # for a run against sponsor data.
        size = int(request.get("reference_cohort_size", 5000))
        frame = reference_cohort(n=size)
        _, profile = process_seed(rows=frame.to_dict(orient="records"))
        source = "built in reference population (demo fixture, not patient derived)"

    payload = profile.as_dict()
    payload["source"] = source

    progress.update_stage(
        f"Parsed {payload['rows']} seed rows across {payload['columns']} features"
    )
    progress.finish_stage(
        Stage.PARSE_SEED,
        detail=f"{payload['rows']} rows, {payload['columns']} features",
    )
    return frame, payload


def _stage_train_model(progress: ProgressWriter, seed_frame: pd.DataFrame):
    progress.start_stage(Stage.TRAIN_MODEL)

    generator = load_generator()
    engine = generator_info(generator)

    if engine.is_stub:
        progress.update_stage(
            "Private CTGAN engine not installed. Running the bootstrap fallback."
        )
    else:
        progress.update_stage(f"Fitting {engine.name}")

    generator.fit(seed_frame, progress=lambda message, pct: progress.update_stage(message, pct))

    progress.finish_stage(Stage.TRAIN_MODEL, detail=engine.name)
    return generator, engine


def _stage_sample_cohort(
    progress: ProgressWriter, generator, request: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    progress.start_stage(Stage.SAMPLE_COHORT)

    target = int(request.get("cohort_size", 1000))
    criteria = criteria_from_payload(request.get("criteria") or [])

    if not criteria:
        cohort = generator.sample(
            target, progress=lambda m, p: progress.update_stage(m, p)
        )
        progress.finish_stage(Stage.SAMPLE_COHORT, detail=f"{len(cohort)} patients")
        return cohort, {
            "candidates_screened": int(len(cohort)),
            "eligible": int(len(cohort)),
            "eligibility_rate": 1.0,
            "funnel": [],
            "warnings": [],
            "attempts": 1,
        }

    # A probe run measures the eligibility rate before committing to a full
    # sample. Guessing the oversample factor from the criteria alone is not
    # possible once criteria interact.
    probe_size = min(max(target, 500), 5000)
    progress.update_stage(f"Screening probe sample of {probe_size} candidates")
    probe = generator.sample(probe_size)
    probe_result = apply_criteria(probe, criteria)
    rate = probe_result.eligibility_rate

    if rate <= 0:
        progress.finish_stage(Stage.SAMPLE_COHORT, detail="No eligible patients")
        return probe_result.frame, {
            **probe_result.as_dict(),
            "attempts": 1,
            "note": (
                "No candidate in the probe sample met every criterion. The protocol "
                "as written does not recruit from this population."
            ),
        }

    factor = estimate_oversample_factor(rate)
    cohort = probe_result.frame
    # Funnels accumulate across every batch. Reporting only the final batch
    # produced a funnel whose eligible count contradicted the delivered cohort
    # size, which is the kind of inconsistency that costs all trust in the
    # rest of the report.
    results: list = [probe_result]
    attempts = 1

    while len(cohort) < target and attempts < MAX_SAMPLING_ATTEMPTS + 1:
        needed = int(min((target - len(cohort)) * factor, 2_000_000))
        progress.update_stage(
            f"Eligibility {rate * 100:.1f} percent. Sampling {needed} more candidates "
            f"to reach {target} eligible patients"
        )
        batch = generator.sample(needed)
        batch_result = apply_criteria(batch, criteria)
        results.append(batch_result)
        cohort = pd.concat([cohort, batch_result.frame], ignore_index=True)
        attempts += 1

    trimmed = cohort.head(target).reset_index(drop=True)

    summary = _merge_screening(results)
    summary["attempts"] = attempts
    summary["delivered"] = int(len(trimmed))
    if len(trimmed) < target:
        summary["warnings"] = summary.get("warnings", []) + [
            f"Requested {target} eligible patients, produced {len(trimmed)}. "
            f"Measured eligibility rate is {rate * 100:.2f} percent."
        ]

    progress.finish_stage(
        Stage.SAMPLE_COHORT,
        detail=f"{len(trimmed)} eligible of {summary['candidates_screened']} screened",
    )
    return trimmed, summary


def _stage_validate(
    progress: ProgressWriter,
    seed_frame: pd.DataFrame,
    cohort: pd.DataFrame,
    job_id: str,
    request: dict[str, Any],
    criteria: list | None = None,
) -> dict[str, Any]:
    progress.start_stage(Stage.VALIDATE)

    if len(cohort) < 8:
        progress.finish_stage(Stage.VALIDATE, detail="Skipped, cohort too small")
        return {
            "status": "skipped",
            "reason": "Cohort has too few rows for a meaningful comparison.",
        }

    # The delivered cohort has been screened, so it must be compared against a
    # seed population screened by the same criteria. Comparing a screened
    # cohort against the full seed measures the criteria, not the generator:
    # an HbA1c floor of 7.0 guarantees the two HbA1c distributions differ, and
    # the score would drop for a generator that did nothing wrong. On the
    # reference population that mistake cost roughly six points of fidelity.
    comparison_basis = "full_seed"
    reference = seed_frame

    if criteria:
        screened_seed = apply_criteria(seed_frame, criteria).frame
        if len(screened_seed) >= 8:
            reference = screened_seed
            comparison_basis = "seed_screened_by_the_same_criteria"
        else:
            # Too few eligible seed patients to compare against. Falling back
            # to the full seed is wrong in the way described above, so the
            # basis is reported and the caller can discount the score.
            comparison_basis = "full_seed_fallback_too_few_eligible_seed_rows"

    real_sample = _cap(reference, VALIDATION_SAMPLE_CAP)
    synthetic_sample = _cap(cohort, VALIDATION_SAMPLE_CAP)

    progress.update_stage(
        f"Comparing {len(synthetic_sample)} synthetic against "
        f"{len(real_sample)} reference patients"
    )

    payload = {
        "real": frame_to_rows(real_sample),
        "synthetic": frame_to_rows(synthetic_sample),
        "cohort_id": job_id,
        "preview_features": int(request.get("preview_features", 5)),
    }

    try:
        with httpx.Client(timeout=VALIDATION_TIMEOUT) as client:
            response = client.post(f"{FIDELITYCHECK_URL}/validate", json=payload)
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        # A validation failure does not invalidate the cohort itself, so the
        # job completes and the report is marked unavailable. Reporting the
        # cohort as failed here would throw away minutes of generation over a
        # transient network error.
        logger.warning("validation call failed for job %s: %s", job_id, exc)
        progress.finish_stage(Stage.VALIDATE, detail="Validation unavailable")
        return {
            "status": "unavailable",
            "reason": f"FidelityCheck could not be reached: {exc}",
        }

    report = body.get("data") or {}
    fidelity = report.get("overall_fidelity")
    grade = report.get("grade")

    progress.finish_stage(
        Stage.VALIDATE,
        detail=f"Fidelity {fidelity} percent ({grade})" if fidelity is not None else "Complete",
    )

    return {
        "status": "complete",
        "overall_fidelity": fidelity,
        "grade": grade,
        "verdict": report.get("verdict"),
        "components": report.get("components"),
        "comparison_basis": comparison_basis,
        "reference_rows": int(len(real_sample)),
        "report": report,
    }


def _merge_screening(results: list) -> dict[str, Any]:
    """Combine per batch screening results into one cumulative funnel.

    Criteria are applied in the same order to every batch, so step i of one
    batch and step i of another are the same criterion and their counts add.
    A criterion that emptied one batch early leaves that batch with a shorter
    funnel, so the merge is driven by the longest one.
    """
    if not results:
        return {
            "candidates_screened": 0,
            "eligible": 0,
            "eligibility_rate": 0.0,
            "funnel": [],
            "warnings": [],
        }

    longest = max(results, key=lambda r: len(r.funnel))
    merged: list[dict[str, Any]] = []

    for index, template in enumerate(longest.funnel):
        candidates_in = sum(
            r.funnel[index].candidates_in for r in results if index < len(r.funnel)
        )
        removed = sum(r.funnel[index].removed for r in results if index < len(r.funnel))
        candidates_out = sum(
            r.funnel[index].candidates_out for r in results if index < len(r.funnel)
        )
        notes = [
            r.funnel[index].note
            for r in results
            if index < len(r.funnel) and r.funnel[index].note
        ]
        merged.append(
            {
                "criterion": template.criterion,
                "feature": template.feature,
                "kind": template.kind,
                "candidates_in": candidates_in,
                "removed": removed,
                "candidates_out": candidates_out,
                "removal_rate": round(removed / candidates_in, 6) if candidates_in else 0.0,
                "note": notes[0] if notes else None,
            }
        )

    screened = sum(r.candidates_screened for r in results)
    eligible = sum(r.eligible for r in results)
    warnings: list[str] = []
    for result in results:
        for warning in result.warnings:
            if warning not in warnings:
                warnings.append(warning)

    return {
        "candidates_screened": screened,
        "eligible": eligible,
        "eligibility_rate": round(eligible / screened, 6) if screened else 0.0,
        "funnel": merged,
        "warnings": warnings,
    }


def _cap(frame: pd.DataFrame, cap: int) -> pd.DataFrame:
    if len(frame) <= cap:
        return frame
    # Fixed seed so a re-run of the same job produces the same score. A
    # fidelity number that moves between runs is not defensible in review.
    return frame.sample(n=cap, random_state=20260816).reset_index(drop=True)
