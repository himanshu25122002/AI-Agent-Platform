# ============================================================
# Yuno Agent Platform — LangGraph State Definition
#
# WorkflowState is the shared state that flows through the graph.
# Every node receives this state, modifies it, and returns updates.
#
# Design decisions:
# - Annotated[list, add_messages] for proper message accumulation
#   (LangGraph knows to APPEND, not replace, using add_messages reducer)
# - All other fields are simple scalars (last-write-wins)
# - Separate cost tracking fields for real-time monitoring
# - human_feedback field for human-in-the-loop resume
# ============================================================
from __future__ import annotations

from typing import Annotated, Any, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class WorkflowState(TypedDict):
    """
    Shared state for all workflow graph executions.

    This TypedDict defines the complete state schema.
    Each field is the accumulated state across all nodes.

    Key design: messages uses add_messages reducer which:
    1. Merges new messages into existing list
    2. Deduplicates by message ID
    3. Handles AIMessage, HumanMessage, ToolMessage correctly
    """

    # ---- Core message history ----------------------------------
    # add_messages reducer: new messages are APPENDED, not replaced
    messages: Annotated[list[BaseMessage], add_messages]

    # ---- Execution context ------------------------------------
    execution_id: str
    workflow_id: str
    workflow_name: str
    input_message: str  # Original user input

    # ---- Agent outputs ----------------------------------------
    # Each agent stores its output here for the next agent to read
    agent_outputs: dict[str, str]  # {"research_agent": "findings...", "analysis_agent": "analysis..."}
    current_agent: str  # Name of currently executing agent

    # ---- Human-in-the-loop ------------------------------------
    human_approval_needed: bool
    human_approval_prompt: Optional[str]  # What to ask the human
    human_feedback: Optional[str]  # Human's response

    # ---- Cost tracking ----------------------------------------
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    estimated_cost: float

    # ---- Control flow -----------------------------------------
    iteration_count: int
    max_iterations: int
    should_end: bool
    error: Optional[str]

    # ---- Metadata ---------------------------------------------
    metadata: dict[str, Any]  # Extensible, non-structured data


def initial_state(
    execution_id: str,
    workflow_id: str,
    workflow_name: str,
    input_message: str,
    max_iterations: int = 10,
) -> WorkflowState:
    """
    Create the initial state for a new execution.
    All fields initialized to safe defaults.
    """
    from langchain_core.messages import HumanMessage

    return WorkflowState(
        messages=[HumanMessage(content=input_message)],
        execution_id=execution_id,
        workflow_id=workflow_id,
        workflow_name=workflow_name,
        input_message=input_message,
        agent_outputs={},
        current_agent="",
        human_approval_needed=False,
        human_approval_prompt=None,
        human_feedback=None,
        total_tokens=0,
        prompt_tokens=0,
        completion_tokens=0,
        estimated_cost=0.0,
        iteration_count=0,
        max_iterations=max_iterations,
        should_end=False,
        error=None,
        metadata={},
    )
