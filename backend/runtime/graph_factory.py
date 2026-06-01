# ============================================================
# Yuno Agent Platform — LangGraph Graph Factory
#
# Converts the workflow JSON (stored in DB as React Flow format)
# into a compiled LangGraph StateGraph.
#
# This is the architectural bridge between:
# - Frontend: Visual workflow builder (React Flow)
# - Backend: Database storage (JSONB)
# - Runtime: LangGraph execution (StateGraph)
#
# Key design decisions:
# - Pure function: build_graph(workflow_dict) → CompiledGraph
# - No side effects in graph building phase
# - PostgreSQL checkpointer for LangGraph memory persistence
# - astream_events() for real-time token streaming
# ============================================================
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.logger import get_logger

logger = get_logger(__name__)


def calculate_cost(prompt_tokens: int, completion_tokens: int, model: str) -> float:
    """
    Calculate estimated cost based on OpenAI pricing.

    Pricing (per 1K tokens, as of 2024):
    - gpt-4o-mini: $0.000150 input, $0.000600 output
    - gpt-4o: $0.0025 input, $0.010 output
    - gpt-3.5-turbo: $0.0005 input, $0.0015 output
    """
    pricing = {
        "gpt-4o-mini": (0.000150, 0.000600),
        "gpt-4o": (0.0025, 0.010),
        "gpt-3.5-turbo": (0.0005, 0.0015),
        "gpt-4-turbo": (0.010, 0.030),
    }
    input_price, output_price = pricing.get(model, (0.000150, 0.000600))
    return (prompt_tokens / 1000 * input_price) + (completion_tokens / 1000 * output_price)


async def build_and_run_graph(
    execution_id: str,
    workflow_data: dict[str, Any],
    input_message: str,
) -> dict[str, Any]:
    """
    Build a LangGraph StateGraph from workflow JSON and execute it.

    This is the main entry point called by the RQ worker.

    Flow:
    1. Parse workflow nodes and edges
    2. Load agent configurations from DB
    3. Build StateGraph with agent nodes
    4. Compile with PostgreSQL checkpointer
    5. Stream execution events → Redis Pub/Sub → WebSocket
    6. Return final output and metrics

    Args:
        execution_id: UUID for this execution (used as LangGraph thread_id)
        workflow_data: Full workflow dict with nodes and edges
        input_message: User's input message

    Returns:
        Dict with final_output, total_tokens, estimated_cost, etc.
    """
    from langgraph.graph import StateGraph, START, END
    from runtime.state import WorkflowState, initial_state
    from runtime.nodes import create_agent_node, create_trigger_node

    nodes = workflow_data.get("nodes", [])
    edges = workflow_data.get("edges", [])
    workflow_id = workflow_data.get("id", "")
    workflow_name = workflow_data.get("name", "Unnamed Workflow")

    logger.info(
        "graph_building",
        execution_id=execution_id,
        workflow_name=workflow_name,
        node_count=len(nodes),
        edge_count=len(edges),
    )

    # ---- Load all agent configurations -------------------------
    from app.database import AsyncSessionFactory
    from app.models import Agent
    from sqlalchemy import select

    agent_configs: dict[str, dict] = {}
    async with AsyncSessionFactory() as session:
        result = await session.execute(select(Agent).where(Agent.is_active == True))
        agents = result.scalars().all()
        agent_configs = {str(a.id): a.to_dict() for a in agents}

    # ---- Build the StateGraph ----------------------------------
    graph = StateGraph(WorkflowState)

    # Map workflow node IDs to LangGraph node IDs (safe names)
    node_id_map: dict[str, str] = {}
    agent_nodes: list[str] = []  # Ordered list of agent node IDs

    for node in nodes:
        node_id = node["id"]
        node_data = node.get("data", {})
        node_type = node_data.get("node_type", "agent")
        label = node_data.get("label", node_id)

        # Create a safe LangGraph node name (no spaces, special chars)
        safe_name = node_id.replace("-", "_").replace(" ", "_").lower()
        node_id_map[node_id] = safe_name

        if node_type in ("trigger", "start"):
            # Trigger node: just passes input through
            graph.add_node(safe_name, create_trigger_node(execution_id, label))

        elif node_type == "agent":
            agent_id = node_data.get("agent_id", "")
            agent_config = agent_configs.get(agent_id)

            if not agent_config:
                logger.warning("agent_not_found", agent_id=agent_id, node=label)
                # Create placeholder node
                graph.add_node(safe_name, create_trigger_node(execution_id, f"[Missing: {label}]"))
            else:
                graph.add_node(
                    safe_name,
                    create_agent_node(
                        agent_config=agent_config,
                        execution_id=execution_id,
                        node_label=label,
                    )
                )
                agent_nodes.append(safe_name)

        elif node_type == "human_approval":
            from runtime.nodes import create_human_approval_node
            graph.add_node(safe_name, create_human_approval_node(execution_id, label))

        elif node_type == "decision":
            from runtime.nodes import create_decision_node
            graph.add_node(safe_name, create_decision_node(execution_id, label))

        elif node_type == "delay":
            from runtime.nodes import create_delay_node
            delay_ms = node_data.get("config", {}).get("delay_ms", 1000)
            graph.add_node(safe_name, create_delay_node(delay_ms))

        else:
            # Unknown node type — pass through
            graph.add_node(safe_name, create_trigger_node(execution_id, label))

    # ---- Add edges to graph ------------------------------------
    if not nodes:
        raise ValueError("Workflow has no nodes")

    # Find the start node
    start_node_id = None
    for node in nodes:
        if node.get("data", {}).get("node_type") in ("trigger", "start"):
            start_node_id = node["id"]
            break

    if not start_node_id:
        # Default to first node
        start_node_id = nodes[0]["id"]

    start_safe_name = node_id_map[start_node_id]
    graph.add_edge(START, start_safe_name)

    # Add workflow edges
    for edge in edges:
        source = node_id_map.get(edge.get("source", ""))
        target = node_id_map.get(edge.get("target", ""))

        if source and target:
            graph.add_edge(source, target)

    # Add END edge to last node
    if nodes:
        last_node_id = nodes[-1]["id"]
        last_safe_name = node_id_map[last_node_id]
        # Only add END if not already connected
        target_ids = {node_id_map.get(e.get("target", "")) for e in edges}
        if last_safe_name not in {node_id_map.get(e.get("source", "")) for e in edges}:
            graph.add_edge(last_safe_name, END)
        else:
            # Find nodes with no outgoing edges
            source_ids = {node_id_map.get(e.get("source", "")) for e in edges}
            for safe_name in node_id_map.values():
                if safe_name not in source_ids and safe_name != node_id_map.get(start_node_id, ""):
                    graph.add_edge(safe_name, END)

    # ---- Compile with PostgreSQL checkpointer ------------------
    compiled_graph = None
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        async with await AsyncPostgresSaver.from_conn_string(
            settings.database_url_sync.replace("+asyncpg", "").replace("postgresql+", "postgresql://").replace("postgresql://", "")
        ) as checkpointer:
            compiled_graph = graph.compile(checkpointer=checkpointer)

            # ---- Execute and stream events ---------------------
            return await _stream_execution(
                compiled_graph=compiled_graph,
                execution_id=execution_id,
                workflow_id=workflow_id,
                workflow_name=workflow_name,
                input_message=input_message,
            )

    except Exception as e:
        logger.warning(
            "checkpointer_unavailable_falling_back",
            error=str(e),
        )
        # Fallback: compile without checkpointer (no persistence)
        compiled_graph = graph.compile()
        return await _stream_execution(
            compiled_graph=compiled_graph,
            execution_id=execution_id,
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            input_message=input_message,
        )


async def _stream_execution(
    compiled_graph,
    execution_id: str,
    workflow_id: str,
    workflow_name: str,
    input_message: str,
) -> dict[str, Any]:
    """
    Stream LangGraph execution events to Redis Pub/Sub.

    Uses astream_events() for granular event streaming:
    - on_chat_model_start: LLM call beginning
    - on_chat_model_stream: Token-by-token streaming
    - on_chat_model_end: LLM call complete with full response
    - on_tool_start: Tool being called
    - on_tool_end: Tool returned result
    - on_chain_start/end: Node lifecycle events
    """
    from runtime.state import initial_state
    from app.redis_client import publish_event, get_async_redis

    config = {
        "configurable": {
            "thread_id": execution_id,  # LangGraph checkpoint key
        },
        "recursion_limit": 50,
    }

    state = initial_state(
        execution_id=execution_id,
        workflow_id=workflow_id,
        workflow_name=workflow_name,
        input_message=input_message,
    )

    total_tokens = 0
    prompt_tokens = 0
    completion_tokens = 0
    final_output = ""

    logger.info("execution_streaming_start", execution_id=execution_id)

    try:
        async for event in compiled_graph.astream_events(state, config=config, version="v2"):
            event_name = event.get("event", "")
            event_data = event.get("data", {})
            tags = event.get("tags", [])

            # ---- LLM Token Streaming ---------------------------
            if event_name == "on_chat_model_stream":
                chunk = event_data.get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    await publish_event(f"exec:{execution_id}", {
                        "type": "token_chunk",
                        "execution_id": execution_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "data": {
                            "token": chunk.content,
                            "agent": event.get("name", ""),
                        },
                    })

            # ---- LLM Call Complete -----------------------------
            elif event_name == "on_chat_model_end":
                output = event_data.get("output")
                if output and hasattr(output, "usage_metadata") and output.usage_metadata:
                    meta = output.usage_metadata
                    p_tokens = meta.get("input_tokens", 0)
                    c_tokens = meta.get("output_tokens", 0)
                    prompt_tokens += p_tokens
                    completion_tokens += c_tokens
                    total_tokens += p_tokens + c_tokens

                    # Determine model for cost calc
                    model = getattr(output, "response_metadata", {}).get("model_name", settings.openai_default_model)
                    cost = calculate_cost(prompt_tokens, completion_tokens, model)

                    await publish_event(f"exec:{execution_id}", {
                        "type": "cost_update",
                        "execution_id": execution_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "data": {
                            "total_tokens": total_tokens,
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": completion_tokens,
                            "estimated_cost": round(cost, 6),
                        },
                    })

            # ---- Tool Calls ------------------------------------
            elif event_name == "on_tool_start":
                tool_name = event.get("name", "unknown_tool")
                tool_input = event_data.get("input", {})
                await publish_event(f"exec:{execution_id}", {
                    "type": "tool_call",
                    "execution_id": execution_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "data": {
                        "tool": tool_name,
                        "input": str(tool_input)[:500],
                    },
                })

            elif event_name == "on_tool_end":
                tool_name = event.get("name", "unknown_tool")
                output = event_data.get("output", "")
                await publish_event(f"exec:{execution_id}", {
                    "type": "tool_result",
                    "execution_id": execution_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "data": {
                        "tool": tool_name,
                        "output": str(output)[:500],
                    },
                })

            # ---- Node (Chain) lifecycle events -----------------
            elif event_name == "on_chain_start" and "LangGraph" not in event.get("name", ""):
                node_name = event.get("name", "")
                await publish_event(f"exec:{execution_id}", {
                    "type": "node_started",
                    "execution_id": execution_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "data": {"node": node_name},
                })

                # Update DB with current node
                try:
                    from app.database import AsyncSessionFactory
                    from app.models import Execution
                    from sqlalchemy import select

                    async with AsyncSessionFactory() as session:
                        result = await session.execute(
                            select(Execution).where(Execution.id == execution_id)
                        )
                        exec_record = result.scalar_one_or_none()
                        if exec_record:
                            exec_record.current_node = node_name
                            await session.commit()
                except Exception:
                    pass  # Non-critical

            elif event_name == "on_chain_end" and "LangGraph" not in event.get("name", ""):
                node_name = event.get("name", "")
                output_data = event_data.get("output", {})

                # Capture final output from last node
                if isinstance(output_data, dict):
                    messages = output_data.get("messages", [])
                    if messages:
                        last_msg = messages[-1]
                        if hasattr(last_msg, "content"):
                            final_output = last_msg.content

                await publish_event(f"exec:{execution_id}", {
                    "type": "node_completed",
                    "execution_id": execution_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "data": {"node": node_name},
                })

    except Exception as e:
        logger.error("streaming_error", execution_id=execution_id, error=str(e))
        raise

    estimated_cost = calculate_cost(prompt_tokens, completion_tokens, settings.openai_default_model)

    logger.info(
        "execution_complete",
        execution_id=execution_id,
        total_tokens=total_tokens,
        estimated_cost=estimated_cost,
    )

    return {
        "final_output": final_output,
        "total_tokens": total_tokens,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "estimated_cost": round(estimated_cost, 6),
    }
