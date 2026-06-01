# ============================================================
# Yuno Agent Platform — RQ Worker Entry Point
#
# This process:
# 1. Connects to Redis queue
# 2. Waits for execution jobs
# 3. Processes jobs by running LangGraph
# 4. Publishes events to Redis Pub/Sub (→ WebSocket → UI)
#
# Start: python -m worker.main
# Start multiple workers: python -m worker.main --burst (process all then exit)
#
# RQ Design decision over Celery:
# - 5 lines to enqueue vs 50 lines Celery config
# - No broker/backend separation (Redis does both)
# - Dashboard via rq-dashboard (pip install rq-dashboard)
# - Sufficient for demo; can migrate to Celery if needed
# ============================================================
from __future__ import annotations

import asyncio
import logging
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rq import Worker, Queue
from redis import Redis

from app.config import settings
from app.logger import setup_logging, get_logger

# Setup logging for worker process
setup_logging(log_level=settings.log_level, json_logs=settings.is_production)
logger = get_logger(__name__)


def main():
    """Start the RQ worker process."""
    logger.info(
        "worker_starting",
        queue=settings.redis_queue_name,
        redis_url=settings.redis_url,
    )

    redis_conn = Redis.from_url(settings.redis_url, decode_responses=False)
    queues = [settings.redis_queue_name]

    worker = Worker(
        queues=queues,
        connection=redis_conn,
        log_job_description=True,
    )

    logger.info("worker_ready", queues=queues)

    try:
        worker.work(
            with_scheduler=True,  # Enable scheduled jobs
            burst=False,           # Run continuously (not just drain queue)
        )
    except KeyboardInterrupt:
        logger.info("worker_shutdown_requested")
    except Exception as e:
        logger.error("worker_crashed", error=str(e), exc_info=True)
        raise


if __name__ == "__main__":
    main()
