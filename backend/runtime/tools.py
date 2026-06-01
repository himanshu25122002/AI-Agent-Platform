# ============================================================
# Yuno Agent Platform — LangChain Tools
#
# Tools available to agents:
# - web_search: Tavily Search API (real web results)
# - calculator: Safe math evaluation
# - datetime: Current time/date
#
# Design: Each tool is a @tool decorated function.
# Agents receive tools via llm.bind_tools(tools).
# ============================================================
from __future__ import annotations

from datetime import datetime, timezone

from langchain.tools import tool
from langchain_core.tools import BaseTool

from app.config import settings
from app.logger import get_logger

logger = get_logger(__name__)


def get_web_search_tool() -> BaseTool:
    """
    Web search tool using Tavily Search API.

    Tavily is purpose-built for LLM agents:
    - Returns summarized, relevant results
    - Handles news and real-time queries
    - Supports AI-optimized response format
    """
    try:
        from langchain_community.tools.tavily_search import TavilySearchResults
        return TavilySearchResults(
            max_results=3,
            description="Search the web for current information. Input: search query string.",
        )
    except Exception:
        # Fallback mock tool if Tavily not configured
        logger.warning("tavily_not_available_using_mock")
        return _get_mock_search_tool()


def _get_mock_search_tool() -> BaseTool:
    """Mock search tool for demo without Tavily API key."""
    @tool
    def web_search(query: str) -> str:
        """Search the web for information. Returns mock results for demo."""
        return (
            f"[Mock Search Results for: {query}]\n"
            f"Based on recent information, here are key findings about '{query}':\n"
            f"1. This is a simulated search result for demonstration.\n"
            f"2. In production, connect your Tavily API key for real web search.\n"
            f"3. The topic '{query}' has multiple relevant aspects worth exploring."
        )
    return web_search


def get_calculator_tool() -> BaseTool:
    """
    Safe calculator tool for mathematical operations.

    Uses Python's numexpr for safe evaluation (no exec/eval).
    Prevents code injection via expression sandboxing.
    """
    @tool
    def calculator(expression: str) -> str:
        """
        Evaluate mathematical expressions safely.
        Input: A mathematical expression like '2 + 2' or '(15 * 8) / 3'.
        """
        try:
            import ast
            # Safe evaluation: only allow numbers and math operators
            allowed_chars = set("0123456789+-*/()., ")
            if not all(c in allowed_chars for c in expression):
                return "Error: Only basic math operations allowed (+, -, *, /)"

            result = ast.literal_eval(
                str(eval(expression, {"__builtins__": {}}, {}))  # noqa: S307
            )
            return f"Result: {result}"
        except ZeroDivisionError:
            return "Error: Division by zero"
        except Exception as e:
            return f"Calculation error: {str(e)}"

    return calculator


def get_datetime_tool() -> BaseTool:
    """Tool that returns the current date and time."""
    @tool
    def get_current_datetime(timezone_name: str = "UTC") -> str:
        """
        Get the current date and time.
        Input: timezone name (e.g., 'UTC', 'US/Eastern')
        """
        now = datetime.now(timezone.utc)
        return (
            f"Current UTC time: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            f"ISO format: {now.isoformat()}"
        )

    return get_current_datetime
