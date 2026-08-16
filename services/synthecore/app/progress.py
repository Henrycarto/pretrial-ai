"""Job progress transport over Redis.

Generation runs for minutes, so the frontend cannot poll a request open. Two
things happen on every stage transition:

1. The full job state is written to a Redis hash under `cohort:job:{id}`.
2. The same state is published on `cohort:progress:{id}`.

The hash exists because pub/sub has no history. A browser that connects
thirty seconds into a job would otherwise see nothing until the next stage
boundary, which on the training stage can be minutes. The subscriber reads
the hash first, emits it as the opening frame, then follows the channel.

Both the Celery worker (synchronous) and the FastAPI process (async) need
this, so there are two clients over one key layout rather than one client
forced into the wrong concurrency model.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, AsyncIterator

import redis
import redis.asyncio as aioredis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Job state outlives the job so a director can reopen a cohort the next
# morning and still see how it was produced.
JOB_TTL_SECONDS = int(os.getenv("JOB_TTL_SECONDS", str(60 * 60 * 24 * 7)))


class Stage(str, Enum):
    """The four pipeline stages the UI renders as a step list.

    Ordering is meaningful. The frontend derives "done", "active" and
    "pending" from the index of the current stage, so stages must not be
    reordered without updating GenerationProgress.tsx.
    """

    PARSE_SEED = "parse_seed"
    TRAIN_MODEL = "train_model"
    SAMPLE_COHORT = "sample_cohort"
    VALIDATE = "validate"


STAGE_ORDER: list[Stage] = [
    Stage.PARSE_SEED,
    Stage.TRAIN_MODEL,
    Stage.SAMPLE_COHORT,
    Stage.VALIDATE,
]

STAGE_LABELS: dict[Stage, str] = {
    Stage.PARSE_SEED: "Parsing seed data",
    Stage.TRAIN_MODEL: "Training model",
    Stage.SAMPLE_COHORT: "Sampling cohort",
    Stage.VALIDATE: "Running validation",
}


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class JobState:
    job_id: str
    status: str = JobStatus.QUEUED.value
    stage: str | None = None
    stage_label: str | None = None
    stage_index: int = -1
    stage_count: int = len(STAGE_ORDER)
    percent: float = 0.0
    message: str = "Queued"
    created_at: float = 0.0
    updated_at: float = 0.0
    stages: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def job_key(job_id: str) -> str:
    return f"cohort:job:{job_id}"


def channel_for(job_id: str) -> str:
    return f"cohort:progress:{job_id}"


def _blank_stages() -> list[dict[str, Any]]:
    return [
        {
            "key": stage.value,
            "label": STAGE_LABELS[stage],
            "status": "pending",
            "started_at": None,
            "finished_at": None,
            "detail": None,
        }
        for stage in STAGE_ORDER
    ]


class ProgressWriter:
    """Synchronous writer used inside the Celery worker."""

    def __init__(self, job_id: str, url: str = REDIS_URL) -> None:
        self.job_id = job_id
        self.client = redis.Redis.from_url(url, decode_responses=True)

    def _persist(self, state: JobState) -> None:
        state.updated_at = time.time()
        payload = json.dumps(state.as_dict())
        pipe = self.client.pipeline()
        pipe.set(job_key(self.job_id), payload, ex=JOB_TTL_SECONDS)
        pipe.publish(channel_for(self.job_id), payload)
        pipe.execute()

    def load(self) -> JobState:
        raw = self.client.get(job_key(self.job_id))
        if not raw:
            return JobState(
                job_id=self.job_id,
                created_at=time.time(),
                stages=_blank_stages(),
            )
        return JobState(**json.loads(raw))

    def create(self, message: str = "Queued") -> JobState:
        state = JobState(
            job_id=self.job_id,
            status=JobStatus.QUEUED.value,
            message=message,
            created_at=time.time(),
            stages=_blank_stages(),
        )
        self._persist(state)
        return state

    def start_stage(self, stage: Stage, message: str | None = None) -> JobState:
        state = self.load()
        index = STAGE_ORDER.index(stage)
        state.status = JobStatus.RUNNING.value
        state.stage = stage.value
        state.stage_label = STAGE_LABELS[stage]
        state.stage_index = index
        state.message = message or STAGE_LABELS[stage]
        # Percent tracks completed stages, so the bar advances on stage exit
        # rather than pretending to know progress inside a stage.
        state.percent = round(index / len(STAGE_ORDER) * 100, 2)
        for i, entry in enumerate(state.stages):
            if i < index and entry["status"] == "pending":
                entry["status"] = "done"
            if i == index:
                entry["status"] = "running"
                entry["started_at"] = time.time()
        self._persist(state)
        return state

    def update_stage(self, detail: str, percent: float | None = None) -> JobState:
        """Emit sub-stage detail without moving to the next stage."""
        state = self.load()
        state.message = detail
        if state.stage_index >= 0 and state.stage_index < len(state.stages):
            state.stages[state.stage_index]["detail"] = detail
        if percent is not None:
            state.percent = round(max(state.percent, min(percent, 100.0)), 2)
        self._persist(state)
        return state

    def finish_stage(self, stage: Stage, detail: str | None = None) -> JobState:
        state = self.load()
        index = STAGE_ORDER.index(stage)
        entry = state.stages[index]
        entry["status"] = "done"
        entry["finished_at"] = time.time()
        if detail:
            entry["detail"] = detail
        state.percent = round((index + 1) / len(STAGE_ORDER) * 100, 2)
        self._persist(state)
        return state

    def succeed(self, result: dict[str, Any], message: str = "Cohort ready") -> JobState:
        state = self.load()
        state.status = JobStatus.SUCCEEDED.value
        state.percent = 100.0
        state.message = message
        state.result = result
        for entry in state.stages:
            if entry["status"] in {"pending", "running"}:
                entry["status"] = "done"
                entry["finished_at"] = entry["finished_at"] or time.time()
        self._persist(state)
        return state

    def failure(self, code: str, message: str, details: Any = None) -> JobState:
        state = self.load()
        state.status = JobStatus.FAILED.value
        state.message = message
        state.error = {"code": code, "message": message, "details": details}
        if 0 <= state.stage_index < len(state.stages):
            state.stages[state.stage_index]["status"] = "failed"
            state.stages[state.stage_index]["finished_at"] = time.time()
        self._persist(state)
        return state


class ProgressReader:
    """Async reader used by the FastAPI process to serve status and SSE."""

    def __init__(self, url: str = REDIS_URL) -> None:
        self.client = aioredis.Redis.from_url(url, decode_responses=True)

    async def get(self, job_id: str) -> dict[str, Any] | None:
        raw = await self.client.get(job_key(job_id))
        return json.loads(raw) if raw else None

    async def stream(self, job_id: str) -> AsyncIterator[dict[str, Any]]:
        """Current state first, then every subsequent publish.

        Subscribing before reading the snapshot avoids the gap where a stage
        transition lands between the two operations and is never seen.
        """
        pubsub = self.client.pubsub()
        await pubsub.subscribe(channel_for(job_id))
        try:
            snapshot = await self.get(job_id)
            if snapshot:
                yield snapshot
                if snapshot.get("status") in {
                    JobStatus.SUCCEEDED.value,
                    JobStatus.FAILED.value,
                    JobStatus.CANCELLED.value,
                }:
                    return

            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                state = json.loads(message["data"])
                yield state
                if state.get("status") in {
                    JobStatus.SUCCEEDED.value,
                    JobStatus.FAILED.value,
                    JobStatus.CANCELLED.value,
                }:
                    return
        finally:
            await pubsub.unsubscribe(channel_for(job_id))
            await pubsub.close()
