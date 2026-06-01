# ============================================================
# Yuno Agent Platform — Agents API Router
#
# Agent CRUD + test endpoint.
# No repository pattern — SQLAlchemy used directly in handlers.
# ============================================================
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.logger import get_logger
from app.models import Agent, Execution
from app.schemas import (
    AgentCreate,
    AgentResponse,
    AgentTestRequest,
    AgentUpdate,
    APIResponse,
)

router = APIRouter()
logger = get_logger(__name__)


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentCreate,
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    """
    Create a new agent.

    Validates:
    - Model name is supported
    - Tools are available
    - System prompt meets minimum length
    """
    agent = Agent(
        name=payload.name,
        role=payload.role,
        system_prompt=payload.system_prompt,
        model=payload.model,
        tools=payload.tools,
        memory_settings=payload.memory_settings,
        channels=payload.channels,
        guardrails=payload.guardrails,
    )

    db.add(agent)
    await db.commit()
    await db.refresh(agent)

    logger.info("agent_created", agent_id=agent.id, name=agent.name)
    return AgentResponse.model_validate(agent.to_dict())


@router.get("", response_model=List[AgentResponse])
async def list_agents(
    skip: int = 0,
    limit: int = 50,
    active_only: bool = False,
    db: AsyncSession = Depends(get_db),
) -> List[AgentResponse]:
    """List all agents with pagination."""
    query = select(Agent).offset(skip).limit(limit).order_by(Agent.created_at.desc())

    if active_only:
        query = query.where(Agent.is_active == True)

    result = await db.execute(query)
    agents = result.scalars().all()
    return [AgentResponse.model_validate(a.to_dict()) for a in agents]


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    """Get a single agent by ID."""
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )

    return AgentResponse.model_validate(agent.to_dict())


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    payload: AgentUpdate,
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    """Update an agent's configuration."""
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )

    # Apply updates — only fields that were provided
    update_data = payload.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(agent, field, value)

    agent.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(agent)

    logger.info("agent_updated", agent_id=agent.id, updated_fields=list(update_data.keys()))
    return AgentResponse.model_validate(agent.to_dict())


@router.delete("/{agent_id}", response_model=APIResponse)
async def delete_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    """
    Delete an agent.

    Soft delete: sets is_active=False rather than removing the row.
    This preserves message history and execution references.
    """
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )

    agent.is_active = False
    agent.updated_at = datetime.now(timezone.utc)
    await db.commit()

    logger.info("agent_deleted", agent_id=agent_id)
    return APIResponse(success=True, message=f"Agent {agent.name} deactivated")


@router.post("/{agent_id}/test", response_model=APIResponse)
async def test_agent(
    agent_id: str,
    payload: AgentTestRequest,
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    """
    Test an agent with a single prompt.

    Creates a temporary single-agent execution without persisting
    to the full execution pipeline. Useful for validating prompts
    and configuration before adding to a workflow.
    """
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )

    from app.config import settings

    if not settings.has_openai:
        return APIResponse(
            success=False,
            message="OpenAI API key not configured",
            data={"error": "Set OPENAI_API_KEY in environment"},
        )

    try:
        from langchain_openai import ChatOpenAI
        from langchain.schema import HumanMessage, SystemMessage

        llm = ChatOpenAI(
            model=agent.model,
            api_key=settings.openai_api_key,
            temperature=0.7,
        )

        messages = [
            SystemMessage(content=agent.system_prompt),
            HumanMessage(content=payload.prompt),
        ]

        response = await llm.ainvoke(messages)

        return APIResponse(
            success=True,
            message="Agent test completed",
            data={
                "agent_name": agent.name,
                "response": response.content,
                "tokens": response.usage_metadata.get("total_tokens", 0) if response.usage_metadata else 0,
                "model": agent.model,
            },
        )

    except Exception as e:
        logger.error("agent_test_failed", agent_id=agent_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent test failed: {str(e)}",
        )
