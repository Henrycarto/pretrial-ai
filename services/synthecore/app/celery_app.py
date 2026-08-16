"""Celery application for SyntheCore generation jobs.

Generation takes minutes on a real CTGAN fit, so it cannot run inside a
request. The API enqueues and returns a job id immediately; the worker owns
the run and reports through the Redis progress channel.
"""

from __future__ import annotations

import os

from celery import Celery

BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

celery_app = Celery("synthecore", broker=BROKER_URL, backend=RESULT_BACKEND)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # A generation job is not idempotent and not cheap. Acknowledging late
    # means a worker killed mid fit hands the job to another worker instead
    # of losing it silently.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # One long job per worker process at a time. Prefetching a second job
    # behind a fifteen minute CTGAN fit leaves it stranded while other
    # workers sit idle.
    worker_prefetch_multiplier=1,
    task_time_limit=int(os.getenv("CELERY_TASK_TIME_LIMIT", "3600")),
    task_soft_time_limit=int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "3300")),
    result_expires=int(os.getenv("CELERY_RESULT_EXPIRES", str(60 * 60 * 24))),
    broker_connection_retry_on_startup=True,
)

celery_app.autodiscover_tasks(["app.tasks"])

# Imported for the side effect of registering the task with this app
# instance. The worker is started against `app.celery_app:celery_app`, so
# without this the task is unknown at dispatch time.
from app.tasks import generation_job  # noqa: E402,F401
