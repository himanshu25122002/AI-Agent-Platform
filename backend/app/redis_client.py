# ============================================================
# Yuno Agent Platform — Redis Client & Queue Setup
#
# Redis serves THREE purposes in this architecture:
# 1. Job Queue (via RQ) — Telegram webhook → enqueue → worker
# 2. Pub/Sub — Worker publishes events → WebSocket reads
# 3. Cache — Execution state, agent configs
#
# Design decision: Redis over Kafka/RabbitMQ because:
# - Single binary, single docker service
# - RQ is dead simple (5 lines to enqueue)
# - Pub/Sub perfect for WebSocket bridge
# - Zero protocol overhead for demo
# ============================================================
from __future__ import annotations

import json
from typing import Any, AsyncGenerator

import redis.asyncio as aioredis
from redis import Redis
from rq import Queue

from app.config import settings
from app.logger import get_logger

logger = get_logger(__name__)

# ---- Synchronous Redis client (for RQ which requires sync) ----
_sync_redis: Redis | None = None

# ---- Async Redis client (for FastAPI, WebSocket, Pub/Sub) ----
_async_redis: aioredis.Redis | None = None


def get_sync_redis() -> Redis:
    """
    Get synchronous Redis client.
    Used by RQ queue (RQ is not async-native).
    Singleton per process.
    """
    global _sync_redis
    if _sync_redis is None:
        _sync_redis = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
            health_check_interval=30,
        )
    return _sync_redis


def get_async_redis() -> aioredis.Redis:
    """
    Get async Redis client.
    Used by FastAPI endpoints, WebSocket manager, Pub/Sub.
    Singleton per process.
    """
    global _async_redis
    if _async_redis is None:
        _async_redis = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
    return _async_redis


def get_job_queue() -> Queue:
    """
    Get the RQ job queue for LangGraph execution jobs.

    Queue configuration:
    - Default timeout: 600s (10 min) for long-running agents
    - Default TTL: 1 hour for job results
    - Failed job retention: 24 hours for debugging
    """
    redis_conn = get_sync_redis()
    return Queue(
        name=settings.redis_queue_name,
        connection=redis_conn,
        default_timeout=600,
        job_execution_timeout=settings.langgraph_timeout_seconds + 60,
    )


async def check_redis_connection() -> bool:
    """
    Verify Redis connectivity.
    Called during health check.
    """
    try:
        redis = get_async_redis()
        await redis.ping()
        return True
    except Exception as e:
        logger.error("redis_connection_failed", error=str(e))
        return False


async def publish_event(channel: str, event: dict[str, Any]) -> None:
    """
    Publish event to Redis Pub/Sub channel.

    Used by the RQ worker to broadcast execution events.
    WebSocket manager subscribes to these channels and
    forwards events to connected browser clients.

    Channel naming convention:
    - exec:{execution_id} — execution-specific events
    - broadcast — global events (new execution started, etc.)

    Args:
        channel: Redis channel name
        event: Dictionary that will be JSON-serialized
    """
    try:
        redis = get_async_redis()
        await redis.publish(channel, json.dumps(event))
        logger.debug(
            "event_published",
            channel=channel,
            event_type=event.get("type"),
        )
    except Exception as e:
        logger.error("event_publish_failed", channel=channel, error=str(e))


async def subscribe_to_execution(
    execution_id: str,
) -> AsyncGenerator[dict[str, Any], None]:
    """
    Subscribe to execution events via Redis Pub/Sub.

    This is consumed by the WebSocket endpoint to stream
    events to the browser client in real-time.

    Args:
        execution_id: The execution to subscribe to

    Yields:
        Deserialized event dictionaries
    """
    redis = get_async_redis()
    pubsub = redis.pubsub()
    channel = f"exec:{execution_id}"

    try:
        await pubsub.subscribe(channel)
        logger.info("subscribed_to_execution", execution_id=execution_id)

        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    yield data

                    # Stop listening if execution is complete
                    if data.get("type") in ("execution_completed", "execution_failed"):
                        break
                except json.JSONDecodeError:
                    logger.warning("invalid_pubsub_message", data=message["data"])
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()


async def cache_set(key: str, value: Any, ttl: int = 300) -> None:
    """Store value in Redis cache with TTL."""
    redis = get_async_redis()
    await redis.set(key, json.dumps(value), ex=ttl)


async def cache_get(key: str) -> Any | None:
    """Retrieve value from Redis cache."""
    redis = get_async_redis()
    data = await redis.get(key)
    if data:
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return data
    return None


async def cache_delete(key: str) -> None:
    """Delete key from Redis cache."""
    redis = get_async_redis()
    await redis.delete(key)


async def close_redis() -> None:
    """Close Redis connections on application shutdown."""
    global _async_redis, _sync_redis
    if _async_redis:
        await _async_redis.close()
        _async_redis = None
    if _sync_redis:
        _sync_redis.close()
        _sync_redis = None
    logger.info("redis_connections_closed")
