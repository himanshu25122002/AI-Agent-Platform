# ============================================================
# Yuno Agent Platform — SQLAlchemy ORM Models
#
# Simplified schema: 4 tables only (per architecture review).
# No repository pattern — services use models directly.
#
# Tables:
# 1. agents      — Agent configuration (name, prompt, tools, etc.)
# 2. workflows   — Workflow graph (nodes + edges stored as JSON)
# 3. executions  — Each run (status, cost, output)
# 4. messages    — All agent messages within executions
# ============================================================
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database import Base


def utcnow() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    """Generate a new UUID4 string."""
    return str(uuid.uuid4())


class Agent(Base):
    """
    Agent configuration table.

    Stores everything needed to instantiate and run a LangChain agent.
    Tools, memory settings, and guardrails stored as JSONB for flexibility
    — these fields evolve frequently and don't need relational integrity.

    Design decision: JSONB for tools/memory vs normalized tables:
    - Tools list is small, never queried individually
    - Memory settings are config, not data
    - Guardrails vary per agent type
    - JSONB gives schema flexibility without migrations
    """
    __tablename__ = "agents"

    id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        default=new_uuid,
        nullable=False,
    )
    name = Column(String(100), nullable=False, index=True)
    role = Column(String(100), nullable=False)
    system_prompt = Column(Text, nullable=False)
    model = Column(String(50), nullable=False, default="gpt-4o-mini")
    tools = Column(JSONB, nullable=False, default=list)  # ["web_search", "calculator"]
    memory_settings = Column(
        JSONB,
        nullable=False,
        default=lambda: {"type": "buffer", "window": 10},
    )
    channels = Column(
        JSONB,
        nullable=False,
        default=lambda: ["web"],  # ["telegram", "web"]
    )
    guardrails = Column(
        JSONB,
        nullable=False,
        default=lambda: {"max_iterations": 5, "timeout_seconds": 60},
    )
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    # Relationships
    messages = relationship("Message", back_populates="agent", lazy="noload")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "system_prompt": self.system_prompt,
            "model": self.model,
            "tools": self.tools,
            "memory_settings": self.memory_settings,
            "channels": self.channels,
            "guardrails": self.guardrails,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<Agent id={self.id} name={self.name!r} model={self.model!r}>"


class Workflow(Base):
    """
    Workflow definition table.

    Stores the entire workflow as a React Flow graph (nodes + edges as JSON).
    This is the source of truth for both the visual builder and LangGraph compiler.

    Design decision: Store nodes/edges as JSON in one table vs normalized:
    - No need to query individual nodes
    - React Flow works natively with JSON
    - LangGraph compiler reads JSON directly
    - Fewer joins = faster reads
    - Schema evolution without migrations

    The is_template flag distinguishes user workflows from pre-built templates.
    template_type allows categorization ('research', 'content').
    """
    __tablename__ = "workflows"

    id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        default=new_uuid,
        nullable=False,
    )
    name = Column(String(100), nullable=False, index=True)
    description = Column(Text, nullable=True)
    nodes = Column(JSONB, nullable=False, default=list)  # React Flow nodes
    edges = Column(JSONB, nullable=False, default=list)  # React Flow edges
    is_template = Column(Boolean, nullable=False, default=False, index=True)
    template_type = Column(String(50), nullable=True)  # 'research', 'content'
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    # Relationships
    executions = relationship("Execution", back_populates="workflow", lazy="noload")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "nodes": self.nodes,
            "edges": self.edges,
            "is_template": self.is_template,
            "template_type": self.template_type,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<Workflow id={self.id} name={self.name!r}>"


class Execution(Base):
    """
    Execution tracking table.

    Each row represents one run of a workflow.
    Status progression: pending → running → completed | failed | waiting_human

    thread_id: LangGraph's checkpoint identifier.
    Using execution_id as thread_id ensures each execution has isolated state.

    Cost tracking uses OpenAI's pricing model:
    - Input: $0.000150 per 1K tokens (gpt-4o-mini)
    - Output: $0.000600 per 1K tokens (gpt-4o-mini)

    trigger_type: 'manual' | 'telegram' | 'schedule'
    trigger_data: Channel-specific metadata (Telegram chat_id, etc.)
    """
    __tablename__ = "executions"

    id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        default=new_uuid,
        nullable=False,
    )
    workflow_id = Column(
        UUID(as_uuid=False),
        ForeignKey("workflows.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = Column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
    )  # pending, running, completed, failed, waiting_human, cancelled
    trigger_type = Column(String(20), nullable=False, default="manual")
    trigger_data = Column(JSONB, nullable=True)  # {chat_id: 123, user: "Alice"}
    input_message = Column(Text, nullable=False)
    output_message = Column(Text, nullable=True)
    current_node = Column(String(100), nullable=True)  # For live tracking
    error_message = Column(Text, nullable=True)

    # Cost tracking
    total_tokens = Column(Integer, nullable=False, default=0)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    estimated_cost = Column(Float, nullable=False, default=0.0)

    # Timing
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    # Relationships
    workflow = relationship("Workflow", back_populates="executions", lazy="noload")
    messages = relationship(
        "Message",
        back_populates="execution",
        lazy="noload",
        cascade="all, delete-orphan",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "status": self.status,
            "trigger_type": self.trigger_type,
            "trigger_data": self.trigger_data,
            "input_message": self.input_message,
            "output_message": self.output_message,
            "current_node": self.current_node,
            "error_message": self.error_message,
            "total_tokens": self.total_tokens,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "estimated_cost": self.estimated_cost,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<Execution id={self.id} status={self.status!r}>"


class Message(Base):
    """
    Message table — all communications within an execution.

    Records every agent message, tool call, and user interaction.
    This is the audit trail and enables the monitoring dashboard.

    sender_type: 'user' | 'agent' | 'system' | 'tool'
    message_type: 'text' | 'tool_call' | 'tool_result' | 'handoff' | 'error'

    metadata stores per-message token counts and latency:
    {
        "tokens": 150,
        "latency_ms": 823,
        "model": "gpt-4o-mini",
        "tool_name": "web_search"  # for tool messages
    }
    """
    __tablename__ = "messages"

    id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        default=new_uuid,
        nullable=False,
    )
    execution_id = Column(
        UUID(as_uuid=False),
        ForeignKey("executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id = Column(
        UUID(as_uuid=False),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    sender_name = Column(String(100), nullable=False)  # Human-readable name
    sender_type = Column(String(20), nullable=False)   # user, agent, system, tool
    message_type = Column(String(30), nullable=False, default="text")
    content = Column(Text, nullable=False)
    metadata_ = Column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
    )  # {tokens, latency_ms, model}
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    # Relationships
    execution = relationship("Execution", back_populates="messages", lazy="noload")
    agent = relationship("Agent", back_populates="messages", lazy="noload")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "execution_id": self.execution_id,
            "agent_id": self.agent_id,
            "sender_name": self.sender_name,
            "sender_type": self.sender_type,
            "message_type": self.message_type,
            "content": self.content,
            "metadata": self.metadata_,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<Message id={self.id} sender={self.sender_name!r} type={self.message_type!r}>"
