import logging
from typing import Optional

from arq import Worker, cron
from arq.connections import RedisSettings
from arq.worker import create_worker
from pydantic.utils import import_string
from starlette.datastructures import CommaSeparatedStrings

import keep.api.logging
from keep.api.core.config import config
from keep.api.tasks.process_background_ai_task import process_background_ai_task
from keep.api.tasks.healthcheck_task import healthcheck_task
from keep.api.consts import (
    KEEP_ARQ_TASK_POOL,
    KEEP_ARQ_TASK_POOL_AI,
    KEEP_ARQ_TASK_POOL_ALL,
    KEEP_ARQ_TASK_POOL_BASIC_PROCESSING,
)

keep.api.logging.setup_logging()
logger = logging.getLogger(__name__)

# Current worker will pick up tasks only according to it's execution pool:
all_tasks_for_the_worker = ["keep.api.tasks.healthcheck_task.healthcheck_task"]

if KEEP_ARQ_TASK_POOL == KEEP_ARQ_TASK_POOL_ALL or \
        KEEP_ARQ_TASK_POOL == KEEP_ARQ_TASK_POOL_BASIC_PROCESSING:
    all_tasks_for_the_worker += [
        "keep.api.tasks.process_event_task.async_process_event",
        "keep.api.tasks.process_topology_task.async_process_topology",
    ]

if KEEP_ARQ_TASK_POOL == KEEP_ARQ_TASK_POOL_ALL or \
        KEEP_ARQ_TASK_POOL == KEEP_ARQ_TASK_POOL_AI:
    all_tasks_for_the_worker += [
        "keep.api.tasks.process_background_ai_task.process_background_ai_task",
        "keep.api.tasks.process_background_ai_task.process_correlation",
        "keep.api.tasks.process_background_ai_task.process_summary_generation",
    ]

ARQ_BACKGROUND_FUNCTIONS: Optional[CommaSeparatedStrings] = config(
    "ARQ_BACKGROUND_FUNCTIONS",
    cast=CommaSeparatedStrings,
    default=all_tasks_for_the_worker,
)

FUNCTIONS: list = (
    [
        import_string(background_function)
        for background_function in list(ARQ_BACKGROUND_FUNCTIONS)
    ]
    if ARQ_BACKGROUND_FUNCTIONS is not None
    else list()
)


async def startup(ctx):
    pass


async def shutdown(ctx):
    pass


def get_arq_worker() -> Worker:
    keep_result = config(
        "ARQ_KEEP_RESULT", cast=int, default=3600
    )  # duration to keep job results for
    expires = config(
        "ARQ_EXPIRES", cast=int, default=3600
    )  # the default length of time from when a job is expected to start after which the job expires, making it shorter to avoid clogging
    return create_worker(
        WorkerSettings, keep_result=keep_result, expires_extra_ms=expires
    )


def at_every_x_minutes(x: int, start: int = 0, end: int = 59):
    return {*list(range(start, end, x))}


class WorkerSettings:
    """
    Settings for the ARQ worker.
    """

    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings(
        host=config("REDIS_HOST", default="localhost"),
        port=config("REDIS_PORT", cast=int, default=6379),
        username=config("REDIS_USERNAME", default=None),
        password=config("REDIS_PASSWORD", default=None),
        conn_timeout=60,
        conn_retries=10,
        conn_retry_delay=10,
    )
    # Only if it's an AI-dedicated worker, we can set large timeout, otherwise keeping low to avoid clogging
    timeout = 60 * 15 if KEEP_ARQ_TASK_POOL == KEEP_ARQ_TASK_POOL_AI else 30
    functions: list = FUNCTIONS
    cron_jobs = [
        cron(
            healthcheck_task,
            minute=at_every_x_minutes(1),
            unique=True,
            timeout=30,
            max_tries=1,
            run_at_startup=True,
        ),
    ]
    if KEEP_ARQ_TASK_POOL == KEEP_ARQ_TASK_POOL_ALL or \
            KEEP_ARQ_TASK_POOL == KEEP_ARQ_TASK_POOL_AI:
        cron_jobs.append(
            cron(
                process_background_ai_task,
                minute=at_every_x_minutes(1),
                unique=True,
                timeout=30,
                max_tries=1,
                run_at_startup=True,
            )
        )
