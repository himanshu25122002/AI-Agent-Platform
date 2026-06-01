# ============================================================
# Yuno Agent Platform — WebSocket Endpoints
#
# Two WebSocket channels:
# 1. /ws/{execution_id} — Subscribe to specific execution events
# 2. /ws/monitor       — Subscribe to all system events (dashboard)
# ============================================================
from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.logger import get_logger
from app.websocket_manager import ws_manager

router = APIRouter()
logger = get_logger(__name__)


@router.websocket("/{execution_id}")
async def execution_websocket(
    websocket: WebSocket,
    execution_id: str,
) -> None:
    """
    WebSocket endpoint for real-time execution monitoring.

    Client connects here to receive streaming events from a specific
    workflow execution. Events are published by the RQ worker via
    Redis Pub/Sub and forwarded here.

    Connection lifecycle:
    1. Client connects: ws://localhost:8000/ws/{execution_id}
    2. Server subscribes to Redis channel: exec:{execution_id}
    3. Events forwarded to client as JSON
    4. Connection closes when execution completes or client disconnects

    Usage from browser:
        const ws = new WebSocket(`ws://localhost:8000/ws/${executionId}`)
        ws.onmessage = (e) => console.log(JSON.parse(e.data))
    """
    logger.info("websocket_connection_requested", execution_id=execution_id)
    await ws_manager.connect_and_stream(websocket, execution_id)


@router.websocket("/monitor/stream")
async def monitoring_websocket(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for the global monitoring dashboard.

    Receives all system-wide events: new executions, completions,
    errors across all workflows. Used by the Monitor tab in the UI.
    """
    logger.info("monitoring_websocket_connected")
    await ws_manager.connect_to_broadcast(websocket)
