# ============================================================
# Yuno Agent Platform — Monitoring API Router
# ============================================================
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.logger import get_logger
from app.models import Agent, Execution, Message, Workflow
from app.schemas import DashboardStats

router = APIRouter()
logger = get_logger(__name__)


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
) -> DashboardStats:
    """
    Dashboard statistics for the monitoring panel.
    Aggregates execution counts, token usage, and cost for today.
    """
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # Execution counts by status
    status_result = await db.execute(
        select(Execution.status, func.count(Execution.id))
        .group_by(Execution.status)
    )
    status_counts = {row[0]: row[1] for row in status_result.fetchall()}

    # Today's token/cost totals
    today_result = await db.execute(
        select(
            func.coalesce(func.sum(Execution.total_tokens), 0),
            func.coalesce(func.sum(Execution.estimated_cost), 0.0),
        ).where(Execution.created_at >= today_start)
    )
    today_row = today_result.fetchone()
    total_tokens_today = int(today_row[0]) if today_row else 0
    total_cost_today = float(today_row[1]) if today_row else 0.0

    # Agent and workflow counts
    agent_count_result = await db.execute(
        select(func.count(Agent.id)).where(Agent.is_active == True)
    )
    agent_count = agent_count_result.scalar() or 0

    workflow_count_result = await db.execute(
        select(func.count(Workflow.id)).where(Workflow.is_active == True)
    )
    workflow_count = workflow_count_result.scalar() or 0

    return DashboardStats(
        total_executions=sum(status_counts.values()),
        running_executions=status_counts.get("running", 0),
        completed_executions=status_counts.get("completed", 0),
        failed_executions=status_counts.get("failed", 0),
        waiting_human=status_counts.get("waiting_human", 0),
        total_agents=agent_count,
        total_workflows=workflow_count,
        total_tokens_today=total_tokens_today,
        total_cost_today=total_cost_today,
    )


@router.get("/messages/recent")
async def get_recent_messages(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """Get most recent agent messages across all executions."""
    result = await db.execute(
        select(Message)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    messages = result.scalars().all()
    return [m.to_dict() for m in reversed(messages)]
