# ============================================================
# Yuno Agent Platform — RQ Job Functions
#
# execute_workflow() is the core job that RQ workers run.
# It is synchronous (RQ is sync) but calls async LangGraph via
# asyncio.run() — creating a fresh event loop per job.
#
# This is the CORRECT pattern for sync RQ + async LangGraph.
# Do not use asyncio.get_event_loop() — it's deprecated.
# ============================================================
from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

# Ensure app package is importable in worker context
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings
from app.logger import get_logger

logger = get_logger(__name__)


def execute_workflow(
    execution_id: str,
    workflow_data: dict[str, Any],
    **kwargs,
) -> dict[str, Any]:
    """
    RQ job entry point for workflow execution.

    This function is called by the RQ worker process.
    It bridges sync RQ → async LangGraph via asyncio.run().

    Args:
        execution_id: UUID of the Execution record in DB
        workflow_data: Full workflow dict (name, nodes, edges)

    Returns:
        Result dict with status, output, token counts
    """
    logger.info("job_started", execution_id=execution_id, workflow=workflow_data.get("name"))
    start_time = time.time()

    try:
        # asyncio.run() creates a new event loop and runs the coroutine
        # This is safe because each RQ job runs in its own call
        result = asyncio.run(
            _execute_workflow_async(execution_id, workflow_data)
        )
        duration = time.time() - start_time
        logger.info(
            "job_completed",
            execution_id=execution_id,
            duration_seconds=round(duration, 2),
            status=result.get("status"),
        )
        return result

    except Exception as e:
        duration = time.time() - start_time
        logger.error(
            "job_failed",
            execution_id=execution_id,
            error=str(e),
            duration_seconds=round(duration, 2),
            exc_info=True,
        )
        # Best-effort: mark execution as failed in DB
        try:
            asyncio.run(_mark_execution_failed(execution_id, str(e)))
        except Exception:
            pass
        raise


async def _execute_workflow_async(
    execution_id: str,
    workflow_data: dict[str, Any],
) -> dict[str, Any]:
    """
    Async implementation of workflow execution.
    Runs inside asyncio.run() from the sync job function.
    """
    from app.database import AsyncSessionFactory
    from app.models import Execution
    from sqlalchemy import select

    # ---- Mark execution as running ------------------------------
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Execution).where(Execution.id == execution_id)
        )
        execution = result.scalar_one_or_none()

        if not execution:
            raise ValueError(f"Execution {execution_id} not found")

        execution.status = "running"
        execution.started_at = datetime.now(timezone.utc)
        await session.commit()

    # ---- Publish execution_started event -----------------------
    await _publish_event(execution_id, {
        "type": "execution_started",
        "execution_id": execution_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {
            "workflow_name": workflow_data.get("name"),
            "input_message": execution.input_message if execution else "",
        },
    })

    # ---- Build and run LangGraph --------------------------------
    from runtime.graph_factory import build_and_run_graph

    try:
        output = await build_and_run_graph(
            execution_id=execution_id,
            workflow_data=workflow_data,
            input_message=execution.input_message,
        )

        # ---- Mark completed ------------------------------------
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Execution).where(Execution.id == execution_id)
            )
            execution = result.scalar_one_or_none()
            if execution:
                execution.status = "completed"
                execution.output_message = output.get("final_output", "")
                execution.completed_at = datetime.now(timezone.utc)
                execution.total_tokens = output.get("total_tokens", 0)
                execution.prompt_tokens = output.get("prompt_tokens", 0)
                execution.completion_tokens = output.get("completion_tokens", 0)
                execution.estimated_cost = output.get("estimated_cost", 0.0)
                await session.commit()

        # ---- Publish completed event ---------------------------
        await _publish_event(execution_id, {
            "type": "execution_completed",
            "execution_id": execution_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "output": output.get("final_output", ""),
                "total_tokens": output.get("total_tokens", 0),
                "estimated_cost": output.get("estimated_cost", 0.0),
            },
        })

        # ---- Send Telegram response if triggered from Telegram -
        await _maybe_send_telegram_response(execution_id, output.get("final_output", ""))

        return {
            "status": "completed",
            "execution_id": execution_id,
            **output,
        }

    except Exception as e:
        await _mark_execution_failed(execution_id, str(e))
        raise


async def _mark_execution_failed(execution_id: str, error: str) -> None:
    """Mark an execution as failed in DB and publish failure event."""
    try:
        from app.database import AsyncSessionFactory
        from app.models import Execution
        from sqlalchemy import select

        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Execution).where(Execution.id == execution_id)
            )
            execution = result.scalar_one_or_none()
            if execution:
                execution.status = "failed"
                execution.error_message = error[:2000]  # Truncate long errors
                execution.completed_at = datetime.now(timezone.utc)
                await session.commit()

        await _publish_event(execution_id, {
            "type": "execution_failed",
            "execution_id": execution_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {"error": error},
        })
    except Exception as publish_err:
        logger.error(
            "failed_to_mark_execution_failed",
            execution_id=execution_id,
            error=str(publish_err),
        )


async def _publish_event(execution_id: str, event: dict[str, Any]) -> None:
    """Publish event to Redis Pub/Sub channels."""
    try:
        from app.redis_client import publish_event
        await publish_event(f"exec:{execution_id}", event)
        await publish_event("broadcast", event)
    except Exception as e:
        logger.error("event_publish_failed", execution_id=execution_id, error=str(e))


async def _maybe_send_telegram_response(execution_id: str, output: str) -> None:
    """
    If this execution was triggered by Telegram, send the response back.
    """
    try:
        from app.database import AsyncSessionFactory
        from app.models import Execution
        from sqlalchemy import select

        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Execution).where(Execution.id == execution_id)
            )
            execution = result.scalar_one_or_none()

            if not execution or execution.trigger_type != "telegram":
                return

            trigger_data = execution.trigger_data or {}
            chat_id = trigger_data.get("chat_id")

            if not chat_id:
                return

        # Send response to Telegram
        from app.api.telegram import send_telegram_message
        formatted_output = f"✅ *Research Complete*\n\n{output[:4000]}"  # Telegram 4096 char limit
        await send_telegram_message(chat_id, formatted_output)
        logger.info("telegram_response_sent", execution_id=execution_id, chat_id=chat_id)

    except Exception as e:
        logger.error("telegram_response_failed", execution_id=execution_id, error=str(e))
