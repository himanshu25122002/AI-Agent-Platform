# ============================================================
# Yuno Agent Platform — LangGraph Node Implementations
#
# Each function returns a node callable:
# node_fn(state: WorkflowState) -> dict (partial state update)
#
# Nodes RETURN a dict of state updates, not the full state.
# LangGraph merges updates using reducers defined in WorkflowState.
#
# Node types:
# - create_agent_node: Executes LLM + tools, saves message to DB
# - create_trigger_node: Pass-through for start nodes
# - create_human_approval_node: Pauses for human input
# - create_decision_node: Conditional routing
# - create_delay_node: Async sleep
# ============================================================
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.config import settings
from app.logger import get_logger
from runtime.state import WorkflowState

logger = get_logger(__name__)


def create_agent_node(
    agent_config: dict[str, Any],
    execution_id: str,
    node_label: str,
) -> Callable[[WorkflowState], dict]:
    """
    Factory function that creates an agent node for LangGraph.

    Each agent node:
    1. Builds messages from state (system prompt + conversation history)
    2. Calls LLM (streaming-compatible via astream_events parent)
    3. Saves message to DB for persistence + monitoring
    4. Publishes agent_message event to Redis
    5. Returns state updates

    Factory pattern: allows agent_config to be captured in closure,
    keeping the node function signature clean (just state → dict).
    """
    agent_id = agent_config["id"]
    agent_name = agent_config["name"]
    model = agent_config["model"]
    system_prompt = agent_config["system_prompt"]
    tools_config = agent_config.get("tools", [])
    guardrails = agent_config.get("guardrails", {})

    async def agent_node(state: WorkflowState) -> dict:
        logger.info(
            "agent_node_executing",
            agent=agent_name,
            execution_id=execution_id,
            message_count=len(state["messages"]),
        )

        # ---- Check cancellation ---------------------------------
        from app.redis_client import cache_get
        if await cache_get(f"cancel:{execution_id}"):
            logger.info("agent_node_cancelled", agent=agent_name)
            return {"should_end": True, "error": "Cancelled by user"}

        # ---- Check iteration limits ----------------------------
        iteration = state.get("iteration_count", 0)
        max_iter = state.get("max_iterations", guardrails.get("max_iterations", 10))
        if iteration >= max_iter:
            logger.warning("max_iterations_reached", agent=agent_name, iterations=iteration)
            return {"should_end": True}

        # ---- Check cost limits ---------------------------------
        current_cost = state.get("estimated_cost", 0.0)
        if current_cost > settings.max_cost_per_execution:
            logger.warning(
                "cost_limit_exceeded",
                agent=agent_name,
                cost=current_cost,
                limit=settings.max_cost_per_execution,
            )
            return {"should_end": True, "error": f"Cost limit exceeded: ${current_cost:.4f}"}

        # ---- Build message list for LLM ------------------------
        messages = [
            SystemMessage(content=system_prompt),
            SystemMessage(
                content="""
        If current information is needed, use available tools.

        After receiving a tool result, answer the user directly.

        Do not repeatedly call the same tool unless absolutely necessary.
        """
            ),
        ]

        # Add previous agent outputs as context
        agent_outputs = state.get("agent_outputs", {})
        if agent_outputs:
            context_lines = []
            for prev_agent, prev_output in agent_outputs.items():
                context_lines.append(f"[{prev_agent}]: {prev_output}")
            context = "\n\n".join(context_lines)
            messages.append(HumanMessage(
                content=f"Previous agent outputs:\n{context}\n\n"
                        f"User request: {state['input_message']}"
            ))
        else:
            messages.append(
                HumanMessage(
                    content=
                    f"""
            User request: {state['input_message']}

            IMPORTANT:
            If current information, news, web results, latest updates,
            or factual lookup is required,
            you MUST use the available tools before answering.
            """
                )
            )

        # ---- Build tools list ----------------------------------
        tools = []
        if "web_search" in tools_config:
            from runtime.tools import get_web_search_tool
            tools.append(get_web_search_tool())
        if "calculator" in tools_config:
            from runtime.tools import get_calculator_tool
            tools.append(get_calculator_tool())
        if "datetime" in tools_config:
            from runtime.tools import get_datetime_tool
            tools.append(get_datetime_tool())

        # ---- Execute LLM ----------------------------------------
        from langchain_openai import ChatOpenAI
        logger.info(
            "llm_config",
            model=model,
            agent=agent_name,
        )
        llm = ChatOpenAI(
            model=model,
            api_key=settings.openai_api_key,
            temperature=0.7,
            streaming=True,
            stream_usage=True,  
        )

        if tools:
            logger.info(
                "tools_bound",
                tools=[t.name for t in tools],
                agent=agent_name,
            )
            llm_with_tools = llm.bind_tools(tools)
            
        else:
            logger.info(
                "no_tools_bound",
                agent=agent_name,
            )
            llm_with_tools = llm

        start_time = time.perf_counter()

        try:
            response = await llm_with_tools.ainvoke(messages)
            max_tool_calls = 5
            while getattr(response, "tool_calls", None) and max_tool_calls > 0:
                from langchain_core.messages import ToolMessage

                messages.append(response)

                for tool_call in response.tool_calls:

                    tool_name = tool_call["name"]
                    tool_args = tool_call.get("args", {})

                    for tool in tools:

                        if tool.name == tool_name:

                            logger.info(
                                "executing_tool",
                                tool_name=tool_name,
                                tool_args=str(tool_args),
                            )

                            tool_result = tool.invoke(tool_args)

                            logger.info(
                                "tool_executed",
                                tool_name=tool_name,
                                result=str(tool_result),
                            )

                            messages.append(
                                ToolMessage(
                                    content=str(tool_result),
                                    tool_call_id=tool_call["id"],
                                )
                            )

                            break

                logger.info("calling_llm_after_all_tools")

                response = await llm_with_tools.ainvoke(messages)

                max_tool_calls -= 1
            logger.info(
                "raw_llm_response",
                response_dump=str(response),
                response_type=str(type(response)),
                content=str(response.content),
                additional_kwargs=str(getattr(response, "additional_kwargs", {})),
                tool_calls=str(getattr(response, "tool_calls", [])),
                usage=str(getattr(response, "usage_metadata", {})),
            )
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

            # Extract token usage
            usage = getattr(response, "usage_metadata", {}) or {}
            p_tokens = usage.get("input_tokens", 0)
            c_tokens = usage.get("output_tokens", 0)
            t_tokens = p_tokens + c_tokens

            content = response.content if isinstance(response.content, str) else str(response.content)

            logger.info(
                "agent_node_completed",
                agent=agent_name,
                tokens=t_tokens,
                latency_ms=latency_ms,
            )

        except Exception as e:
            logger.error("llm_invocation_failed", agent=agent_name, error=str(e))
            error_content = f"Agent {agent_name} encountered an error: {str(e)}"
            return {
                "messages": [AIMessage(content=error_content, name=agent_name)],
                "error": str(e),
                "current_agent": agent_name,
                "iteration_count": state.get("iteration_count", 0) + 1,
            }

        # ---- Persist message to DB ------------------------------
        try:
            await _save_message(
                execution_id=execution_id,
                agent_id=agent_id,
                agent_name=agent_name,
                content=content,
                tokens=t_tokens,
                latency_ms=latency_ms,
                model=model,
            )
        except Exception as e:
            logger.error("message_save_failed", agent=agent_name, error=str(e))
            # Non-critical — continue execution

        # ---- Publish agent_message event to Redis ---------------
        try:
            from app.redis_client import publish_event
            await publish_event(f"exec:{execution_id}", {
                "type": "agent_message",
                "execution_id": execution_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": {
                    "agent": agent_name,
                    "content": content,
                    "tokens": t_tokens,
                    "latency_ms": latency_ms,
                    "model": model,
                },
            })
        except Exception as e:
            logger.error("event_publish_failed", agent=agent_name, error=str(e))

        # ---- Update cost tracking --------------------------------
        from runtime.graph_factory import calculate_cost
        cost = calculate_cost(
            state.get("prompt_tokens", 0) + p_tokens,
            state.get("completion_tokens", 0) + c_tokens,
            model,
        )

        # ---- Return state updates --------------------------------
        updated_outputs = {**state.get("agent_outputs", {}), agent_name: content}

        return {
            "messages": [AIMessage(content=content, name=agent_name)],
            "agent_outputs": updated_outputs,
            "current_agent": agent_name,
            "iteration_count": state.get("iteration_count", 0) + 1,
            "total_tokens": state.get("total_tokens", 0) + t_tokens,
            "prompt_tokens": state.get("prompt_tokens", 0) + p_tokens,
            "completion_tokens": state.get("completion_tokens", 0) + c_tokens,
            "estimated_cost": cost,
        }

    return agent_node


def create_trigger_node(execution_id: str, label: str) -> Callable[[WorkflowState], dict]:
    """
    Trigger/start node — passes input through unchanged.
    Publishes a node_started event for monitoring.
    """
    async def trigger_node(state: WorkflowState) -> dict:
        logger.info("trigger_node_executing", label=label, execution_id=execution_id)

        from app.redis_client import publish_event
        await publish_event(f"exec:{execution_id}", {
            "type": "node_started",
            "execution_id": execution_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "node": label,
                "node_type": "trigger",
                "input": state["input_message"],
            },
        })

        return {
            "current_agent": label,
        }

    return trigger_node


def create_human_approval_node(execution_id: str, label: str) -> Callable[[WorkflowState], dict]:
    """
    Human-in-the-loop node.

    Pauses execution by polling Redis for approval.
    The UI POSTs to /executions/{id}/approve which stores
    the decision in Redis cache.

    This polls every 2 seconds for up to 5 minutes.
    LangGraph checkpointer saves state, so the graph can resume.
    """
    async def human_approval_node(state: WorkflowState) -> dict:
        logger.info("human_approval_waiting", execution_id=execution_id)

        # Mark execution as waiting for human
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
                    execution.status = "waiting_human"
                    execution.current_node = label
                    await session.commit()
        except Exception as e:
            logger.error("human_approval_db_update_failed", error=str(e))

        # Publish event to notify UI
        from app.redis_client import publish_event, cache_get
        await publish_event(f"exec:{execution_id}", {
            "type": "human_approval_needed",
            "execution_id": execution_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "node": label,
                "prompt": "Please review and approve to continue the workflow.",
                "current_output": state.get("agent_outputs", {}),
            },
        })

        # Poll for approval (max 5 minutes)
        max_wait = 300  # seconds
        poll_interval = 2
        waited = 0

        while waited < max_wait:
            approval = await cache_get(f"approval:{execution_id}")
            if approval is not None:
                approved = approval.get("approved", False)
                feedback = approval.get("feedback", "")

                logger.info(
                    "human_approval_received",
                    execution_id=execution_id,
                    approved=approved,
                )

                if not approved:
                    return {
                        "should_end": True,
                        "error": f"Rejected by human reviewer: {feedback}",
                    }

                return {
                    "human_approval_needed": False,
                    "human_feedback": feedback,
                    "messages": [HumanMessage(content=f"Approved. {feedback}" if feedback else "Approved.")] if feedback else [],
                }

            await asyncio.sleep(poll_interval)
            waited += poll_interval

        # Timeout
        return {
            "should_end": True,
            "error": "Human approval timeout (5 minutes)",
        }

    return human_approval_node


def create_decision_node(execution_id: str, label: str) -> Callable[[WorkflowState], dict]:
    """
    Decision node — evaluates state and determines routing.
    Currently a pass-through; routing is done via LangGraph conditional edges.
    """
    async def decision_node(state: WorkflowState) -> dict:
        logger.info("decision_node_executing", label=label, execution_id=execution_id)

        from app.redis_client import publish_event
        await publish_event(f"exec:{execution_id}", {
            "type": "node_started",
            "execution_id": execution_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "node": label,
                "node_type": "decision",
            },
        })

        return {"current_agent": label}

    return decision_node


def create_delay_node(delay_ms: int) -> Callable[[WorkflowState], dict]:
    """
    Delay node — sleeps for specified milliseconds.
    Useful for rate limiting and pacing agent execution.
    """
    async def delay_node(state: WorkflowState) -> dict:
        logger.info("delay_node_executing", delay_ms=delay_ms)
        await asyncio.sleep(delay_ms / 1000)
        return {}

    return delay_node


async def _save_message(
    execution_id: str,
    agent_id: str,
    agent_name: str,
    content: str,
    tokens: int,
    latency_ms: float,
    model: str,
) -> None:
    """
    Persist agent message to database.
    Called from within agent nodes.
    """
    from app.database import AsyncSessionFactory
    from app.models import Message

    async with AsyncSessionFactory() as session:
        message = Message(
            execution_id=execution_id,
            agent_id=agent_id,
            sender_name=agent_name,
            sender_type="agent",
            message_type="text",
            content=content,
            metadata_={
                "tokens": tokens,
                "latency_ms": latency_ms,
                "model": model,
            },
        )
        session.add(message)
        await session.commit()
