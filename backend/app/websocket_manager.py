# ============================================================
# Yuno Agent Platform — WebSocket Connection Manager
#
# Architecture: Redis Pub/Sub → WebSocket (NOT in-memory dict)
#
# Why Redis bridge instead of in-memory manager:
# - In-memory Dict[execution_id, List[WebSocket]] dies on restart
# - Can't scale to multiple FastAPI workers (connections on different processes)
# - Redis Pub/Sub is the single source of truth for events
# - WebSocket endpoint just subscribes to Redis and forwards
#
# Flow:
#   RQ Worker → redis.publish("exec:{id}", event)
#   FastAPI WS → redis.subscribe("exec:{id}") → ws.send_json(event)
# ============================================================
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from app.logger import get_logger
from app.redis_client import get_async_redis

logger = get_logger(__name__)


class WebSocketManager:
    """
    Manages WebSocket connections with Redis Pub/Sub backend.

    Each WebSocket connection subscribes to a Redis channel for
    the specific execution it wants to monitor. The RQ worker
    publishes events to those channels.

    This design is stateless — no in-memory connection registry.
    FastAPI can restart without losing event routing.
    """

    async def connect_and_stream(
        self,
        websocket: WebSocket,
        execution_id: str,
    ) -> None:
        """
        Accept WebSocket connection and stream events from Redis.

        Runs until:
        - Execution completes/fails (via event type)
        - Client disconnects
        - Server shuts down

        Args:
            websocket: The FastAPI WebSocket connection
            execution_id: Which execution to subscribe to
        """
        await websocket.accept()
        client_id = id(websocket)
        channel = f"exec:{execution_id}"

        logger.info(
            "websocket_connected",
            client_id=client_id,
            execution_id=execution_id,
        )

        # Send connection confirmation
        await self._send_event(websocket, {
            "type": "connected",
            "execution_id": execution_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {"message": f"Subscribed to execution {execution_id}"},
        })

        redis = get_async_redis()
        pubsub = redis.pubsub()

        try:
            await pubsub.subscribe(channel)

            # Run Redis listener and WebSocket keepalive concurrently
            listener_task = asyncio.create_task(
                self._listen_and_forward(pubsub, websocket, execution_id)
            )
            keepalive_task = asyncio.create_task(
                self._keepalive(websocket)
            )

            # Wait for either task to complete
            done, pending = await asyncio.wait(
                [listener_task, keepalive_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Cancel remaining task
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        except WebSocketDisconnect:
            logger.info("websocket_disconnected", client_id=client_id)
        except Exception as e:
            logger.error("websocket_error", client_id=client_id, error=str(e))
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
            except Exception:
                pass
            logger.info("websocket_cleaned_up", client_id=client_id)

    async def _listen_and_forward(
        self,
        pubsub: Any,
        websocket: WebSocket,
        execution_id: str,
    ) -> None:
        """
        Listen to Redis Pub/Sub and forward messages to WebSocket client.
        Terminates when execution_completed or execution_failed event received.
        """
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue

            try:
                event = json.loads(message["data"])
                await self._send_event(websocket, event)

                # Terminal events — stop listening
                if event.get("type") in ("execution_completed", "execution_failed"):
                    logger.info(
                        "execution_terminal_event",
                        execution_id=execution_id,
                        event_type=event["type"],
                    )
                    break

            except json.JSONDecodeError:
                logger.warning("invalid_event_json", data=message["data"])
            except WebSocketDisconnect:
                logger.info("websocket_disconnected_during_stream")
                break

    async def _keepalive(self, websocket: WebSocket) -> None:
        """
        Send periodic ping to detect dead WebSocket connections.
        Without this, stale connections accumulate silently.
        """
        while True:
            await asyncio.sleep(30)
            try:
                await websocket.send_json({
                    "type": "ping",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "data": {},
                })
            except Exception:
                # Connection is dead, exit
                break

    async def _send_event(self, websocket: WebSocket, event: dict[str, Any]) -> None:
        """Send event to WebSocket client with error handling."""
        try:
            await websocket.send_json(event)
        except Exception as e:
            logger.debug("websocket_send_failed", error=str(e))
            raise

    async def broadcast_to_all(self, event: dict[str, Any]) -> None:
        """
        Broadcast an event to the global monitoring channel.
        Used for system-wide events like execution_started.
        """
        redis = get_async_redis()
        await redis.publish("broadcast", json.dumps(event))

    async def connect_to_broadcast(self, websocket: WebSocket) -> None:
        """
        Subscribe WebSocket to global broadcast channel.
        Used by the monitoring dashboard to see all executions.
        """
        await websocket.accept()
        redis = get_async_redis()
        pubsub = redis.pubsub()

        try:
            await pubsub.subscribe("broadcast")

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    event = json.loads(message["data"])
                    await websocket.send_json(event)
                except (json.JSONDecodeError, WebSocketDisconnect):
                    break
        finally:
            await pubsub.unsubscribe("broadcast")
            await pubsub.close()


# Module-level singleton
ws_manager = WebSocketManager()
