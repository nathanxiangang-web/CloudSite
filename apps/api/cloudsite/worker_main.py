"""Standalone Worker entry point.

Runs the platform Task Worker as an independent process, decoupled from
the FastAPI API server.  The worker leases tasks from the DB-backed queue
and executes registered handlers.

Usage::

    python -m cloudsite.worker_main

Configuration via environment variables (CLOUDSITE_ prefix):

    CLOUDSITE_WORKER_QUEUE          queue name to poll (default "default")
    CLOUDSITE_WORKER_POLL_INTERVAL  seconds between polls (default 2.0)
    CLOUDSITE_WORKER_MAX_CONCURRENT max concurrent tasks (default 4)

The worker shares the same data volume as the API process, so both must
use the same CLOUDSITE_DATA_DIR.  Task handlers are registered by plugins
loaded via PluginRegistry, so the worker imports the same plugin set.
"""
from __future__ import annotations

import asyncio
import logging
import sys

from .config import settings
from .database import init_databases, validate_database_files
from .plugins import PluginRegistry
from .platform.tasks import Worker, get_registry

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    level = logging.DEBUG if settings.allow_insecure_dev_key else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )


async def _run_worker() -> None:
    logger.info("initializing databases (data_dir=%s)", settings.data_dir)
    await init_databases()
    validate_database_files()
    logger.info("databases ready")

    registry = PluginRegistry()
    registry.load_enabled()
    task_registry = get_registry()
    logger.info("task handlers registered: %s", sorted(task_registry.registered_types))

    if not task_registry.count:
        logger.warning("no task handlers registered; worker will idle")

    worker = Worker(
        queue=settings.worker_queue,
        registry=task_registry,
        poll_interval=settings.worker_poll_interval,
        max_concurrent=settings.worker_max_concurrent,
    )
    logger.info(
        "starting worker queue=%s poll=%.1fs concurrent=%d",
        worker.queue,
        settings.worker_poll_interval,
        settings.worker_max_concurrent,
    )
    await worker.start()


def main() -> None:
    _configure_logging()
    logger.info("CloudSite Worker starting (pid=%s)", __import__("os").getpid())
    try:
        asyncio.run(_run_worker())
    except KeyboardInterrupt:
        logger.info("worker interrupted by user")
    except Exception:
        logger.exception("worker crashed")
        sys.exit(1)
    logger.info("worker exited cleanly")


if __name__ == "__main__":
    main()