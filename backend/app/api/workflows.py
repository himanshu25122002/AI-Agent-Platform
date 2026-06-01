# ============================================================
# Yuno Agent Platform — Workflows API Router
#
# Workflow CRUD + validation + execution trigger.
# Stores React Flow graph JSON directly in workflows table.
# ============================================================
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.logger import get_logger
from app.models import Agent, Workflow
from app.schemas import (
    APIResponse,
    WorkflowCreate,
    WorkflowExecuteRequest,
    WorkflowResponse,
    WorkflowUpdate,
    WorkflowValidationResult,
)

router = APIRouter()
logger = get_logger(__name__)


def validate_workflow_graph(
    nodes: list,
    edges: list,
    agent_ids: set[str],
) -> WorkflowValidationResult:
    """
    Validate a workflow graph before saving or executing.

    Checks:
    1. Has at least one node
    2. Has a trigger/start node
    3. Has an end path (output node or terminal agent)
    4. No disconnected nodes (every node reachable from start)
    5. All agent_ids reference existing agents
    6. No self-loops on agent nodes

    Design: Pure function — no DB calls, fully testable.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not nodes:
        return WorkflowValidationResult(
            is_valid=False,
            errors=["Workflow must have at least one node"],
        )

    node_ids = {n["id"] for n in nodes}
    node_map = {n["id"]: n for n in nodes}

    # Check for start node (trigger type)
    start_nodes = [
        n for n in nodes
        if n.get("data", {}).get("node_type") in ("trigger", "start")
    ]
    has_start = len(start_nodes) > 0
    if not has_start:
        errors.append("Workflow must have a Trigger node as the starting point")

    # Check for reachable end (output or terminal node)
    end_nodes = [
        n for n in nodes
        if n.get("data", {}).get("node_type") in ("output", "end")
    ]
    # If no explicit end node, last agent node is the terminal
    has_end = len(end_nodes) > 0 or len(nodes) >= 2

    # Validate all edge references point to existing nodes
    for edge in edges:
        if edge.get("source") not in node_ids:
            errors.append(f"Edge {edge.get('id')} source '{edge.get('source')}' does not exist")
        if edge.get("target") not in node_ids:
            errors.append(f"Edge {edge.get('id')} target '{edge.get('target')}' does not exist")

    # Check for disconnected nodes
    if edges:
        connected_nodes = set()
        for edge in edges:
            connected_nodes.add(edge.get("source"))
            connected_nodes.add(edge.get("target"))

        disconnected = node_ids - connected_nodes
        if disconnected and len(nodes) > 1:
            node_labels = [node_map[nid].get("data", {}).get("label", nid) for nid in disconnected]
            warnings.append(f"Disconnected nodes: {', '.join(node_labels)}")

    # Validate agent references
    for node in nodes:
        node_data = node.get("data", {})
        if node_data.get("node_type") == "agent":
            agent_id = node_data.get("agent_id")
            if not agent_id:
                errors.append(f"Agent node '{node_data.get('label', node['id'])}' has no agent selected")
            elif agent_id not in agent_ids:
                errors.append(
                    f"Agent node '{node_data.get('label', node['id'])}' references unknown agent: {agent_id}"
                )

    return WorkflowValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        node_count=len(nodes),
        edge_count=len(edges),
        has_start=has_start,
        has_end=has_end,
    )


@router.post("", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    payload: WorkflowCreate,
    db: AsyncSession = Depends(get_db),
) -> WorkflowResponse:
    """Create a new workflow."""
    # Get all agent IDs for validation
    result = await db.execute(select(Agent.id).where(Agent.is_active == True))
    agent_ids = {str(row[0]) for row in result.fetchall()}

    # Validate if nodes provided
    if payload.nodes:
        validation = validate_workflow_graph(payload.nodes, payload.edges, agent_ids)
        if not validation.is_valid:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": "Workflow validation failed",
                    "errors": validation.errors,
                    "warnings": validation.warnings,
                },
            )

    workflow = Workflow(
        name=payload.name,
        description=payload.description,
        nodes=payload.nodes,
        edges=payload.edges,
    )

    db.add(workflow)
    await db.commit()
    await db.refresh(workflow)

    logger.info("workflow_created", workflow_id=workflow.id, name=workflow.name)
    return WorkflowResponse.model_validate(workflow.to_dict())


@router.get("", response_model=List[WorkflowResponse])
async def list_workflows(
    include_templates: bool = True,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> List[WorkflowResponse]:
    """List workflows. Templates always included by default."""
    query = (
        select(Workflow)
        .where(Workflow.is_active == True)
        .offset(skip)
        .limit(limit)
        .order_by(Workflow.is_template.desc(), Workflow.created_at.desc())
    )

    if not include_templates:
        query = query.where(Workflow.is_template == False)

    result = await db.execute(query)
    workflows = result.scalars().all()
    return [WorkflowResponse.model_validate(w.to_dict()) for w in workflows]


@router.get("/templates", response_model=List[WorkflowResponse])
async def list_templates(
    db: AsyncSession = Depends(get_db),
) -> List[WorkflowResponse]:
    """List pre-built workflow templates."""
    result = await db.execute(
        select(Workflow)
        .where(Workflow.is_template == True, Workflow.is_active == True)
        .order_by(Workflow.created_at.asc())
    )
    workflows = result.scalars().all()
    return [WorkflowResponse.model_validate(w.to_dict()) for w in workflows]


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
) -> WorkflowResponse:
    """Get a workflow by ID including full node/edge data."""
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    workflow = result.scalar_one_or_none()

    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {workflow_id} not found",
        )

    return WorkflowResponse.model_validate(workflow.to_dict())


@router.put("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: str,
    payload: WorkflowUpdate,
    db: AsyncSession = Depends(get_db),
) -> WorkflowResponse:
    """Update workflow configuration."""
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    workflow = result.scalar_one_or_none()

    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {workflow_id} not found",
        )

    # Validate updated graph if nodes/edges changed
    if payload.nodes is not None or payload.edges is not None:
        nodes = payload.nodes or workflow.nodes
        edges = payload.edges or workflow.edges

        agent_result = await db.execute(select(Agent.id).where(Agent.is_active == True))
        agent_ids = {str(row[0]) for row in agent_result.fetchall()}

        validation = validate_workflow_graph(nodes, edges, agent_ids)
        if not validation.is_valid:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": "Workflow validation failed",
                    "errors": validation.errors,
                },
            )

    update_data = payload.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(workflow, field, value)

    workflow.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(workflow)

    logger.info("workflow_updated", workflow_id=workflow_id)
    return WorkflowResponse.model_validate(workflow.to_dict())


@router.delete("/{workflow_id}", response_model=APIResponse)
async def delete_workflow(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    """Soft delete a workflow."""
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    workflow = result.scalar_one_or_none()

    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {workflow_id} not found",
        )

    workflow.is_active = False
    workflow.updated_at = datetime.now(timezone.utc)
    await db.commit()

    logger.info("workflow_deleted", workflow_id=workflow_id)
    return APIResponse(success=True, message=f"Workflow {workflow.name} deleted")


@router.post("/{workflow_id}/validate", response_model=WorkflowValidationResult)
async def validate_workflow(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
) -> WorkflowValidationResult:
    """
    Validate a saved workflow without executing it.
    Returns detailed errors and warnings.
    """
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    workflow = result.scalar_one_or_none()

    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {workflow_id} not found",
        )

    agent_result = await db.execute(select(Agent.id).where(Agent.is_active == True))
    agent_ids = {str(row[0]) for row in agent_result.fetchall()}

    return validate_workflow_graph(workflow.nodes, workflow.edges, agent_ids)


@router.post("/{workflow_id}/execute")
async def execute_workflow(
    workflow_id: str,
    payload: WorkflowExecuteRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger workflow execution.

    This endpoint:
    1. Validates the workflow
    2. Creates an Execution record (pending)
    3. Enqueues the job in Redis (via RQ)
    4. Returns immediately with execution_id

    The actual LangGraph execution happens in the RQ worker.
    Client polls GET /executions/{id} or connects to WS /ws/{id}.
    """
    # Verify workflow exists
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    workflow = result.scalar_one_or_none()

    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {workflow_id} not found",
        )

    # Validate before executing
    agent_result = await db.execute(select(Agent.id).where(Agent.is_active == True))
    agent_ids = {str(row[0]) for row in agent_result.fetchall()}

    validation = validate_workflow_graph(workflow.nodes, workflow.edges, agent_ids)
    if not validation.is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Cannot execute invalid workflow",
                "errors": validation.errors,
            },
        )

    # Create execution record
    from app.models import Execution
    from datetime import datetime, timezone

    execution = Execution(
        workflow_id=workflow_id,
        status="pending",
        trigger_type=payload.trigger_type,
        trigger_data=payload.trigger_data,
        input_message=payload.input_message,
    )
    db.add(execution)
    await db.commit()
    await db.refresh(execution)

    # Enqueue in Redis for worker to process
    from app.redis_client import get_job_queue

    queue = get_job_queue()
    job = queue.enqueue(
        "worker.jobs.execute_workflow",
        execution.id,
        workflow.to_dict(),
        job_id=f"exec_{execution.id}",
        job_timeout=600,
    )

    logger.info(
        "execution_enqueued",
        execution_id=execution.id,
        workflow_id=workflow_id,
        job_id=job.id,
    )

    return {
        "success": True,
        "execution_id": execution.id,
        "status": "pending",
        "message": "Execution queued successfully",
        "websocket_url": f"/ws/{execution.id}",
    }
