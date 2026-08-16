"""Cohort generation engine.

=============================================================================
 STUB. The CTGAN training pipeline is not in this repository.
=============================================================================

The production engine trains an SDV CTGAN model on the parsed seed cohort:
conditional sampling by inclusion criteria, mode specific normalisation of
continuous lab values, a discriminator schedule tuned for the wide tabular
schemas clinical data arrives in, and the privacy accounting that makes the
output releasable. That work is the product and it ships as a private
package, `pretrial_synthecore_private`, installed from a private index in the
deployment image.

`load_generator()` below imports that package when it is present and falls
back to `BootstrapCohortGenerator` when it is not. Everything downstream of
this module, which is the Celery job, the progress transport, the criteria
filter, FidelityCheck, and FHIR-Link, runs identically against either engine.
The public repository is therefore a complete, working system with a
placeholder where the model belongs, not a system with a hole in it.

Read `docs/synthetic-data-methodology.md` for what the real engine does and
how its output is validated.

WHAT THE FALLBACK ACTUALLY IS, STATED PLAINLY: it resamples rows from the
seed cohort with replacement and adds Gaussian jitter to continuous columns.
That reproduces marginals and most of the correlation structure, which is
what makes it useful for exercising the pipeline and the UI end to end. It
provides NO privacy guarantee whatsoever. Every output row is a lightly
perturbed copy of a real row. It must never be pointed at real patient data
outside a local development environment, and the service refuses to do so
unless PRETRIAL_ALLOW_BOOTSTRAP_ON_REAL_DATA is explicitly set.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, float | None], None]

# Jitter is scaled to each column's own spread so it perturbs a creatinine
# value and an age value by a comparable amount in distributional terms.
JITTER_SCALE = 0.04

# Columns with at most this many distinct values are codes, not measurements.
# An ECOG status of 1 jittered to 1.03 is not a plausible patient record, and
# adding noise to it only degrades the fidelity score.
DISCRETE_CARDINALITY_LIMIT = 10


@runtime_checkable
class CohortGenerator(Protocol):
    """The contract the private engine and the fallback both satisfy."""

    name: str
    is_stub: bool

    def fit(self, seed: pd.DataFrame, progress: ProgressCallback | None = None) -> None: ...

    def sample(self, n: int, progress: ProgressCallback | None = None) -> pd.DataFrame: ...

    def describe(self) -> dict[str, Any]: ...


@dataclass
class GeneratorInfo:
    name: str
    is_stub: bool
    detail: str


class BootstrapCohortGenerator:
    """Fallback generator. Demo fidelity, zero privacy guarantee."""

    name = "bootstrap-stub"
    is_stub = True

    def __init__(self, seed: int = 20260816, jitter: float = JITTER_SCALE) -> None:
        self._rng = np.random.default_rng(seed)
        self._jitter = jitter
        self._seed_frame: pd.DataFrame | None = None
        self._numeric_columns: list[str] = []
        self._column_std: dict[str, float] = {}
        self._integer_columns: list[str] = []

    def fit(self, seed: pd.DataFrame, progress: ProgressCallback | None = None) -> None:
        if seed.empty:
            raise ValueError("seed cohort is empty, nothing to fit")

        self._seed_frame = seed.reset_index(drop=True)
        # is_numeric_dtype reports True for bool, so a plain numeric filter
        # jitters on_insulin from True into 0.97 and turns a clean boolean
        # feature into the worst scoring column in the fidelity report.
        # Booleans and low cardinality codes are carried through untouched.
        self._numeric_columns = [
            c
            for c in seed.columns
            if pd.api.types.is_numeric_dtype(seed[c])
            and not pd.api.types.is_bool_dtype(seed[c])
            and seed[c].nunique(dropna=True) > DISCRETE_CARDINALITY_LIMIT
        ]
        # Integer columns are re-rounded after jitter. An age of 62.03 in an
        # export is an immediate credibility problem in front of a reviewer.
        self._integer_columns = [
            c for c in self._numeric_columns if pd.api.types.is_integer_dtype(seed[c])
        ]
        self._column_std = {
            c: float(seed[c].std(ddof=1)) if seed[c].notna().sum() > 1 else 0.0
            for c in self._numeric_columns
        }

        if progress:
            progress(
                f"Fitted fallback generator on {len(seed)} seed rows "
                f"across {len(seed.columns)} features",
                None,
            )

    def sample(self, n: int, progress: ProgressCallback | None = None) -> pd.DataFrame:
        if self._seed_frame is None:
            raise RuntimeError("sample() called before fit()")
        if n <= 0:
            raise ValueError("requested cohort size must be positive")

        indices = self._rng.integers(0, len(self._seed_frame), size=n)
        out = self._seed_frame.iloc[indices].reset_index(drop=True).copy()

        for column in self._numeric_columns:
            spread = self._column_std.get(column, 0.0)
            if spread <= 0:
                continue
            noise = self._rng.normal(0.0, spread * self._jitter, size=n)
            out[column] = out[column].astype(float) + noise
            if column in self._integer_columns:
                out[column] = np.rint(out[column]).astype("int64")

        if progress:
            progress(f"Sampled {n} rows from the fallback generator", None)

        return out

    def describe(self) -> dict[str, Any]:
        return {
            "engine": self.name,
            "is_stub": True,
            "method": "row bootstrap with per column Gaussian jitter",
            "jitter_scale": self._jitter,
            "privacy_guarantee": "none",
            "notice": (
                "Placeholder generator. Output rows are perturbed copies of seed "
                "rows. Not releasable. Install the private SyntheCore engine for "
                "CTGAN generation."
            ),
        }


def _load_private_engine() -> CohortGenerator | None:
    """Import the proprietary engine if the private package is installed."""
    try:
        # ------------------------------------------------------------------
        # PROPRIETARY HOOK. This package is absent from the public repository
        # and from the public Docker image. Present only in deployments built
        # against the private index.
        # ------------------------------------------------------------------
        from pretrial_synthecore_private import CTGANCohortGenerator  # type: ignore
    except ImportError:
        return None

    try:
        return CTGANCohortGenerator()
    except Exception:  # noqa: BLE001
        # A broken private engine must not silently downgrade a production
        # deployment to the bootstrap fallback, so this is loud.
        logger.exception("private SyntheCore engine failed to initialise")
        raise


def load_generator(engine: str | None = None) -> CohortGenerator:
    """Resolve the generation engine for this deployment.

    Resolution order is explicit request, then private package, then
    fallback. The explicit request exists so a developer can force the stub
    on a machine that does have the private package installed, and so CI can
    assert the fallback path still works.
    """
    requested = (engine or os.getenv("SYNTHECORE_ENGINE", "auto")).lower()

    if requested in {"stub", "bootstrap"}:
        return BootstrapCohortGenerator()

    private = _load_private_engine()
    if private is not None:
        logger.info("using private SyntheCore engine: %s", private.name)
        return private

    if requested == "ctgan":
        raise RuntimeError(
            "SYNTHECORE_ENGINE=ctgan was requested but pretrial_synthecore_private "
            "is not installed in this image."
        )

    logger.warning(
        "private SyntheCore engine not installed, falling back to the bootstrap stub"
    )
    return BootstrapCohortGenerator()


def generator_info(generator: CohortGenerator) -> GeneratorInfo:
    described = generator.describe()
    return GeneratorInfo(
        name=str(described.get("engine", generator.name)),
        is_stub=bool(described.get("is_stub", generator.is_stub)),
        detail=str(described.get("method", "")),
    )
