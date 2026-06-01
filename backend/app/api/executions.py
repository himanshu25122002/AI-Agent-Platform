# ============================================================
# Yuno Agent Platform — Executions API Router
# ============================================================
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.logger import get_logger
from app.models import Execution, Message
from app.schemas import (
    APIResponse,
    ExecutionApprovalRequest,
    ExecutionResponse,
    MessageResponse,
)

router = APIRouter()
logger = get_logger(__name__)


@router.get("", response_model=List[ExecutionResponse])
async def list_executions(
    status_filter: Optional[str] = None,
    workflow_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> List[ExecutionResponse]:
    """List executions with optional filtering."""
    query = select(Execution).offset(skip).limit(limit).order_by(desc(Execution.created_at))

    if status_filter:
        query = query.where(Execution.status == status_filter)
    if workflow_id:
        query = query.where(Execution.workflow_id == workflow_id)

    result = await db.execute(query)
    executions = result.scalars().all()
    return [ExecutionResponse.model_validate(e.to_dict()) for e in executions]


@router.get("/{execution_id}", response_model=ExecutionResponse)
async def get_execution(
    execution_id: str,
    db: AsyncSession = Depends(get_db),
) -> ExecutionResponse:
    """Get execution details and current status."""
    result = await db.execute(select(Execution).where(Execution.id == execution_id))
    execution = result.scalar_one_or_none()

    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution {execution_id} not found",
        )

    return ExecutionResponse.model_validate(execution.to_dict())


@router.get("/{execution_id}/messages", response_model=List[MessageResponse])
async def get_execution_messages(
    execution_id: str,
    db: AsyncSession = Depends(get_db),
) -> List[MessageResponse]:
    """
    Get all messages for an execution.
    Used by the monitoring panel to show agent-to-agent communication history.
    """
    result = await db.execute(select(Execution).where(Execution.id == execution_id))
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution {execution_id} not found",
        )

    msg_result = await db.execute(
        select(Message)
        .where(Message.execution_id == execution_id)
        .order_by(Message.created_at.asc())
    )
    messages = msg_result.scalars().all()
    return [MessageResponse.model_validate(m.to_dict()) for m in messages]


@router.post("/{execution_id}/approve", response_model=APIResponse)
async def approve_execution(
    execution_id: str,
    payload: ExecutionApprovalRequest,
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    """
    Human-in-the-loop approval endpoint.

    When a workflow contains a Human Approval node, execution pauses
    with status='waiting_human'. This endpoint resumes it.

    Flow:
    1. Verify execution is in waiting_human state
    2. Store approval in Redis (worker polls for it)
    3. Worker reads approval, resumes LangGraph with update_state()
    """
    result = await db.execute(select(Execution).where(Execution.id == execution_id))
    execution = result.scalar_one_or_none()

    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution {execution_id} not found",
        )

    if execution.status != "waiting_human":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Execution is not waiting for human approval (status: {execution.status})",
        )

    # Store approval signal in Redis for the worker to pick up
    from app.redis_client import cache_set
    await cache_set(
        f"approval:{execution_id}",
        {
            "approved": payload.approved,
            "feedback": payload.feedback,
        },
        ttl=300,  # 5 minute TTL
    )

    action = "approved" if payload.approved else "rejected"
    logger.info("human_approval_submitted", execution_id=execution_id, action=action)

    return APIResponse(
        success=True,
        message=f"Execution {action} successfully",
        data={"execution_id": execution_id, "action": action},
    )


@router.post("/{execution_id}/cancel", response_model=APIResponse)
async def cancel_execution(
    execution_id: str,
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    """Cancel a running execution."""
    from datetime import datetime, timezone

    result = await db.execute(select(Execution).where(Execution.id == execution_id))
    execution = result.scalar_one_or_none()

    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution {execution_id} not found",
        )

    if execution.status in ("completed", "failed", "cancelled"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel execution with status: {execution.status}",
        )

    execution.status = "cancelled"
    execution.completed_at = datetime.now(timezone.utc)
    await db.commit()

    # Signal worker to stop
    from app.redis_client import cache_set
    await cache_set(f"cancel:{execution_id}", True, ttl=300)

    # Publish cancellation event to WebSocket
    from app.redis_client import publish_event
    from datetime import datetime, timezone
    await publish_event(f"exec:{execution_id}", {
        "type": "execution_failed",
        "execution_id": execution_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {"error": "Cancelled by user"},
    })

    logger.info("execution_cancelled", execution_id=execution_id)
    return APIResponse(success=True, message="Execution cancelled")
