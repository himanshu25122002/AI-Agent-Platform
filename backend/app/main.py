# ============================================================
# Yuno Agent Platform — FastAPI Application Entry Point
#
# Application lifecycle:
# 1. startup: DB tables created, Redis checked, templates seeded
# 2. request: Handled by routers with DB sessions via dependency
# 3. shutdown: Connections cleanly closed
#
# Design decisions:
# - lifespan context manager (newer FastAPI pattern, vs @app.on_event)
# - CORS middleware configured from settings (no hardcoded origins)
# - Structured error handling with consistent error response format
# - Health endpoint for Docker healthcheck and monitoring
# ============================================================
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import check_database_connection, create_all_tables, dispose_engine
from app.logger import get_logger, setup_logging
from app.redis_client import check_redis_connection, close_redis
from app.schemas import HealthCheck

# Configure logging FIRST, before any other imports use the logger
setup_logging(
    log_level=settings.log_level,
    json_logs=settings.is_production,
)

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.

    Startup:
    - Initialize database tables
    - Verify Redis connectivity
    - Seed workflow templates if not present
    - Log configuration summary

    Shutdown:
    - Close DB connection pool
    - Close Redis connections
    """
    # ---- STARTUP ------------------------------------------------
    logger.info(
        "application_starting",
        app_name=settings.app_name,
        version=settings.version,
        environment=settings.app_env,
        demo_mode=settings.demo_mode,
    )

    # Verify services are reachable
    db_ok = await check_database_connection()
    redis_ok = await check_redis_connection()

    if not db_ok:
        logger.error("database_unreachable_on_startup")
        # Don't crash — let health endpoint report degraded status

    if not redis_ok:
        logger.error("redis_unreachable_on_startup")

    # Create tables (idempotent — safe to run every startup)
    try:
        await create_all_tables()
    except Exception as e:
        logger.error("table_creation_failed", error=str(e))

    # Seed templates
    try:
        from app.seed import seed_templates
        await seed_templates()
    except Exception as e:
        logger.warning("template_seeding_failed", error=str(e))

    logger.info(
        "application_ready",
        database=db_ok,
        redis=redis_ok,
        telegram_configured=settings.has_telegram,
    )

    yield  # Application runs here

    # ---- SHUTDOWN -----------------------------------------------
    logger.info("application_shutting_down")
    await dispose_engine()
    await close_redis()
    logger.info("application_shutdown_complete")


# ============================================================
# FastAPI Application Instance
# ============================================================
app = FastAPI(
    title=settings.app_name,
    description=(
        "AI Agent Orchestration Platform — LangGraph-powered multi-agent system "
        "with Telegram integration, real-time monitoring, and visual workflow builder."
    ),
    version=settings.version,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    openapi_url="/openapi.json" if not settings.is_production else None,
    lifespan=lifespan,
)


# ============================================================
# Middleware
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """
    Log all HTTP requests with timing.
    Adds correlation ID for request tracing.
    """
    start_time = time.perf_counter()
    request_id = request.headers.get("X-Request-ID", f"req_{int(time.time() * 1000)}")

    # Bind request context to all log entries for this request
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        method=request.method,
        path=request.url.path,
    )

    response = await call_next(request)

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "request_completed",
        status_code=response.status_code,
        duration_ms=round(duration_ms, 2),
    )

    response.headers["X-Request-ID"] = request_id
    return response


# ============================================================
# Error Handlers
# ============================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Consistent JSON error format for all HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": exc.detail,
            "status_code": exc.status_code,
            "path": str(request.url.path),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unhandled exceptions."""
    logger.error(
        "unhandled_exception",
        path=request.url.path,
        error=str(exc),
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "Internal server error",
            "status_code": 500,
            "path": str(request.url.path),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


# ============================================================
# Core Endpoints
# ============================================================

@app.get("/health", response_model=HealthCheck, tags=["System"])
async def health_check() -> HealthCheck:
    """
    Health check endpoint.

    Checks:
    - Database connectivity
    - Redis connectivity

    Returns degraded status if any service is down.
    Used by Docker healthcheck and load balancers.
    """
    db_healthy = await check_database_connection()
    redis_healthy = await check_redis_connection()

    all_healthy = db_healthy and redis_healthy
    status = "healthy" if all_healthy else "degraded"

    return HealthCheck(
        status=status,
        version=settings.version,
        services={
            "database": db_healthy,
            "redis": redis_healthy,
            "telegram": settings.has_telegram,
            "openai": settings.has_openai,
        },
        timestamp=datetime.now(timezone.utc),
    )


@app.get("/", tags=["System"])
async def root():
    """Root endpoint — API information."""
    return {
        "name": settings.app_name,
        "version": settings.version,
        "environment": settings.app_env,
        "docs": "/docs",
        "health": "/health",
        "api": settings.api_prefix,
    }


# ============================================================
# Register API Routers
# ============================================================

# Import and register all routers
# Each router is in its own module for clean separation

from app.api.agents import router as agents_router
from app.api.workflows import router as workflows_router
from app.api.executions import router as executions_router
from app.api.monitoring import router as monitoring_router
from app.api.websocket import router as websocket_router

app.include_router(agents_router, prefix=f"{settings.api_prefix}/agents", tags=["Agents"])
app.include_router(workflows_router, prefix=f"{settings.api_prefix}/workflows", tags=["Workflows"])
app.include_router(executions_router, prefix=f"{settings.api_prefix}/executions", tags=["Executions"])
app.include_router(monitoring_router, prefix=f"{settings.api_prefix}/monitoring", tags=["Monitoring"])
app.include_router(websocket_router, prefix="/ws", tags=["WebSocket"])

# Telegram router is optional — only register if token is configured
try:
    from app.api.telegram import router as telegram_router
    app.include_router(telegram_router, prefix=f"{settings.api_prefix}/telegram", tags=["Telegram"])
    logger.info("telegram_router_registered")
except ImportError as e:
    logger.warning("telegram_router_not_available", reason=str(e))
