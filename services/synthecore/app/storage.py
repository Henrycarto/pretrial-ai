"""Where seed uploads and generated cohorts live.

Two backends behind one interface. S3 is the deployed path: cohorts are large,
they outlive the job, and the bucket is where the retention policy and the
object lock live. Redis is the local path so `docker compose up` gives a
working system without an AWS account or a MinIO bucket policy.

The backend is chosen by COHORT_STORAGE. Nothing above this module knows
which one is active.
"""

from __future__ import annotations

import io
import json
import logging
import os
from typing import Any, Protocol

import pandas as pd
import redis

logger = logging.getLogger(__name__)

STORAGE_BACKEND = os.getenv("COHORT_STORAGE", "redis").lower()
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
EXPORT_BUCKET = os.getenv("S3_BUCKET_EXPORT", "pretrial-exports")
SEED_BUCKET = os.getenv("S3_BUCKET_SEED", "pretrial-seed-data")

# Cohorts in Redis are a development convenience, not a store of record.
# A week is long enough to finish a demo and short enough that a laptop
# does not accumulate cohorts indefinitely.
COHORT_TTL_SECONDS = int(os.getenv("COHORT_TTL_SECONDS", str(60 * 60 * 24 * 7)))


class CohortStore(Protocol):
    backend: str

    def put_cohort(self, job_id: str, frame: pd.DataFrame) -> str: ...

    def get_cohort(self, job_id: str) -> pd.DataFrame | None: ...

    def get_seed(self, key: str) -> bytes: ...


class RedisCohortStore:
    backend = "redis"

    def __init__(self, url: str = REDIS_URL) -> None:
        self.client = redis.Redis.from_url(url, decode_responses=False)

    def _key(self, job_id: str) -> str:
        return f"cohort:data:{job_id}"

    def put_cohort(self, job_id: str, frame: pd.DataFrame) -> str:
        # Parquet rather than JSON. A 50k row cohort is roughly an order of
        # magnitude smaller this way and it survives the round trip with its
        # dtypes intact, which JSON does not.
        buffer = io.BytesIO()
        frame.to_parquet(buffer, index=False)
        self.client.set(self._key(job_id), buffer.getvalue(), ex=COHORT_TTL_SECONDS)
        return f"redis://{self._key(job_id)}"

    def get_cohort(self, job_id: str) -> pd.DataFrame | None:
        raw = self.client.get(self._key(job_id))
        if raw is None:
            return None
        return pd.read_parquet(io.BytesIO(raw))

    def get_seed(self, key: str) -> bytes:
        raw = self.client.get(f"seed:{key}")
        if raw is None:
            raise FileNotFoundError(f"seed object '{key}' not found in local storage")
        return raw

    def put_seed(self, key: str, content: bytes) -> str:
        self.client.set(f"seed:{key}", content, ex=COHORT_TTL_SECONDS)
        return f"redis://seed:{key}"


class S3CohortStore:
    backend = "s3"

    def __init__(self) -> None:
        import boto3

        self.client = boto3.client(
            "s3",
            endpoint_url=os.getenv("S3_ENDPOINT_URL") or None,
            region_name=os.getenv("AWS_REGION", "eu-central-1"),
        )

    def _key(self, job_id: str) -> str:
        return f"cohorts/{job_id}/cohort.parquet"

    def put_cohort(self, job_id: str, frame: pd.DataFrame) -> str:
        buffer = io.BytesIO()
        frame.to_parquet(buffer, index=False)
        buffer.seek(0)
        self.client.put_object(
            Bucket=EXPORT_BUCKET,
            Key=self._key(job_id),
            Body=buffer.getvalue(),
            ContentType="application/octet-stream",
            # Server side encryption is not optional for this bucket even
            # though the contents are synthetic. The seed lineage makes them
            # sensitive by association.
            ServerSideEncryption="AES256",
        )
        return f"s3://{EXPORT_BUCKET}/{self._key(job_id)}"

    def get_cohort(self, job_id: str) -> pd.DataFrame | None:
        try:
            response = self.client.get_object(Bucket=EXPORT_BUCKET, Key=self._key(job_id))
        except self.client.exceptions.NoSuchKey:
            return None
        return pd.read_parquet(io.BytesIO(response["Body"].read()))

    def get_seed(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=SEED_BUCKET, Key=key)
        return response["Body"].read()

    def put_seed(self, key: str, content: bytes) -> str:
        self.client.put_object(
            Bucket=SEED_BUCKET,
            Key=key,
            Body=content,
            ServerSideEncryption="AES256",
        )
        return f"s3://{SEED_BUCKET}/{key}"


_store: CohortStore | None = None


def get_store() -> CohortStore:
    global _store
    if _store is None:
        if STORAGE_BACKEND == "s3":
            _store = S3CohortStore()
        else:
            _store = RedisCohortStore()
        logger.info("cohort storage backend: %s", _store.backend)
    return _store


def frame_to_rows(frame: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
    """JSON safe row dicts for API responses.

    Goes through pandas' own JSON writer because a raw `to_dict` leaves numpy
    scalars and NaT in the payload, which the response serialiser rejects.
    """
    subset = frame.head(limit) if limit is not None else frame
    return json.loads(subset.to_json(orient="records", date_format="iso"))
