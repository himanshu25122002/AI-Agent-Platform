# ============================================================
# Yuno Agent Platform — Pydantic Request/Response Schemas
#
# Separation from ORM models is intentional:
# - API contracts are stable even if DB schema changes
# - Input validation separate from DB constraints
# - Clean serialization without SQLAlchemy internals
# ============================================================
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ============================================================
# AGENT SCHEMAS
# ============================================================

class AgentBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Agent display name")
    role: str = Field(..., min_length=1, max_length=100, description="Agent's role/persona")
    system_prompt: str = Field(..., min_length=10, description="System prompt defining agent behavior")
    model: str = Field(default="gpt-4o-mini", description="LLM model identifier")
    tools: List[str] = Field(default_factory=list, description="List of tool names available to agent")
    memory_settings: Dict[str, Any] = Field(
        default_factory=lambda: {"type": "buffer", "window": 10},
        description="Memory configuration",
    )
    channels: List[str] = Field(
        default_factory=lambda: ["web"],
        description="Channels this agent is active on",
    )
    guardrails: Dict[str, Any] = Field(
        default_factory=lambda: {"max_iterations": 5, "timeout_seconds": 60},
        description="Execution limits and safety controls",
    )

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        allowed = [
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
            "gpt-3.5-turbo",
            "o1-mini",
        ]
        if v not in allowed:
            raise ValueError(f"Model must be one of: {', '.join(allowed)}")
        return v

    @field_validator("tools")
    @classmethod
    def validate_tools(cls, v: List[str]) -> List[str]:
        available = ["web_search", "calculator", "datetime", "memory_read", "memory_write"]
        for tool in v:
            if tool not in available:
                raise ValueError(f"Unknown tool: {tool}. Available: {available}")
        return v


class AgentCreate(AgentBase):
    """Schema for creating a new agent."""
    pass


class AgentUpdate(BaseModel):
    """Schema for updating an agent — all fields optional."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    role: Optional[str] = Field(None, min_length=1, max_length=100)
    system_prompt: Optional[str] = Field(None, min_length=10)
    model: Optional[str] = None
    tools: Optional[List[str]] = None
    memory_settings: Optional[Dict[str, Any]] = None
    channels: Optional[List[str]] = None
    guardrails: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class AgentResponse(AgentBase):
    """Schema for agent API responses."""
    id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AgentTestRequest(BaseModel):
    """Schema for testing an agent with a prompt."""
    prompt: str = Field(..., min_length=1, description="Test prompt for the agent")
    stream: bool = Field(default=False, description="Stream response tokens")


# ============================================================
# WORKFLOW SCHEMAS
# ============================================================

class WorkflowNodeData(BaseModel):
    """Data payload for a React Flow workflow node."""
    label: str
    node_type: str  # 'agent', 'decision', 'human_approval', 'delay', 'trigger'
    agent_id: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)


class WorkflowNode(BaseModel):
    """A React Flow node in the workflow graph."""
    id: str
    type: str  # React Flow node type component name
    position: Dict[str, float]  # {x: float, y: float}
    data: WorkflowNodeData


class WorkflowEdge(BaseModel):
    """A React Flow edge connecting two nodes."""
    id: str
    source: str
    target: str
    label: Optional[str] = None
    data: Optional[Dict[str, Any]] = None  # {condition: "state.confidence > 0.7"}


class WorkflowBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    edges: List[Dict[str, Any]] = Field(default_factory=list)


class WorkflowCreate(WorkflowBase):
    """Schema for creating a new workflow."""
    pass


class WorkflowUpdate(BaseModel):
    """Schema for updating a workflow — all fields optional."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    nodes: Optional[List[Dict[str, Any]]] = None
    edges: Optional[List[Dict[str, Any]]] = None


class WorkflowResponse(WorkflowBase):
    """Schema for workflow API responses."""
    id: str
    is_template: bool
    template_type: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkflowValidationResult(BaseModel):
    """Result of workflow graph validation."""
    is_valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    node_count: int = 0
    edge_count: int = 0
    has_start: bool = False
    has_end: bool = False


class WorkflowExecuteRequest(BaseModel):
    """Schema for triggering workflow execution."""
    input_message: str = Field(..., min_length=1, description="Initial user message")
    trigger_type: str = Field(default="manual")
    trigger_data: Optional[Dict[str, Any]] = None


# ============================================================
# EXECUTION SCHEMAS
# ============================================================

class ExecutionResponse(BaseModel):
    """Schema for execution API responses."""
    id: str
    workflow_id: Optional[str]
    status: str
    trigger_type: str
    trigger_data: Optional[Dict[str, Any]]
    input_message: str
    output_message: Optional[str]
    current_node: Optional[str]
    error_message: Optional[str]
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    estimated_cost: float
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class ExecutionApprovalRequest(BaseModel):
    """Schema for human-in-the-loop approval."""
    approved: bool = Field(..., description="Whether to approve or reject")
    feedback: Optional[str] = Field(None, description="Optional feedback message")


# ============================================================
# MESSAGE SCHEMAS
# ============================================================

class MessageResponse(BaseModel):
    """Schema for message API responses."""
    id: str
    execution_id: str
    agent_id: Optional[str]
    sender_name: str
    sender_type: str
    message_type: str
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = {"from_attributes": True}


# ============================================================
# MONITORING SCHEMAS
# ============================================================

class DashboardStats(BaseModel):
    """Real-time dashboard statistics."""
    total_executions: int
    running_executions: int
    completed_executions: int
    failed_executions: int
    waiting_human: int
    total_agents: int
    total_workflows: int
    total_tokens_today: int
    total_cost_today: float


class WebSocketEvent(BaseModel):
    """Schema for WebSocket events broadcast to clients."""
    type: str  # See event types below
    execution_id: Optional[str] = None
    timestamp: datetime
    data: Dict[str, Any] = Field(default_factory=dict)

    # Event types:
    # execution_started    — New execution began
    # node_started         — A workflow node is now active
    # node_completed       — A workflow node finished
    # agent_message        — Agent produced a message
    # token_chunk          — Streaming token from LLM
    # tool_call            — Agent called a tool
    # tool_result          — Tool returned result
    # human_approval_needed — Waiting for human input
    # execution_completed  — Workflow finished successfully
    # execution_failed     — Workflow failed with error
    # cost_update          — Token/cost counters updated


# ============================================================
# HEALTH CHECK SCHEMAS
# ============================================================

class HealthCheck(BaseModel):
    """Health check response schema."""
    status: str  # 'healthy' | 'degraded' | 'unhealthy'
    version: str
    services: Dict[str, bool]  # {database: true, redis: true}
    timestamp: datetime


class APIResponse(BaseModel):
    """Generic API response wrapper."""
    success: bool
    message: str
    data: Optional[Any] = None
