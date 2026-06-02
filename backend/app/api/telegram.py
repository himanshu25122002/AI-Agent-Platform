# ============================================================
# Yuno Agent Platform — Telegram Webhook Router
#
# Telegram flow (webhook mode):
# 1. User sends message to bot
# 2. Telegram POST to /api/telegram/webhook
# 3. Verify secret token header
# 4. Extract chat_id and text
# 5. Find default Telegram workflow
# 6. Create execution record
# 7. Enqueue job in Redis (return 200 IMMEDIATELY)
# 8. Worker executes LangGraph
# 9. On completion, worker sends result to Telegram via Bot API
#
# Critical: Steps 1-7 must complete in <1 second.
# LangGraph execution (step 8) happens asynchronously in worker.
# ============================================================
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.logger import get_logger
from app.models import Execution, Workflow
import httpx
TELEGRAM_USER_WORKFLOWS = {}
router = APIRouter()
logger = get_logger(__name__)


def verify_telegram_signature(
    secret: str,
    body: bytes,
    signature_header: Optional[str],
) -> bool:
    """
    Verify Telegram webhook signature.

    Telegram sends X-Telegram-Bot-Api-Secret-Token header.
    We configured this secret when calling setWebhook.

    This prevents spoofed webhook calls.
    """
    if not signature_header:
        # In development, allow without signature
        return settings.is_development

    return hmac.compare_digest(signature_header, secret)


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Telegram webhook receiver.

    Must return 200 OK within 1 second or Telegram will retry.
    Never execute LangGraph here — always enqueue and return immediately.
    """
    # Read raw body for signature verification
    body = await request.body()

    # Verify webhook authenticity
    if not verify_telegram_signature(
        settings.telegram_webhook_secret,
        body,
        x_telegram_bot_api_secret_token,
    ):
        logger.warning("telegram_webhook_invalid_signature")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook signature",
        )

    # Parse update
    import json
    try:
        update = json.loads(body)
    except json.JSONDecodeError:
        logger.error("telegram_webhook_invalid_json")
        return {"ok": True}  # Return 200 to stop Telegram retrying

    # Only handle text messages or click
    callback_query = update.get("callback_query")

    if callback_query:

        chat_id = callback_query["message"]["chat"]["id"]

        data = callback_query.get("data", "")

        if data.startswith("wf:"):

            workflow_id = int(data.replace("wf:", ""))

            TELEGRAM_USER_WORKFLOWS[chat_id] = workflow_id

            result = await db.execute(
                select(Workflow).where(Workflow.id == workflow_id)
            )

            selected_wf = result.scalar_one_or_none()

            await send_telegram_message(
                chat_id,
                f"✅ Workflow Selected: *{selected_wf.name}*\n\nSend your task now."
            )

        return {"ok": True}

    message = update.get("message") or update.get("edited_message")
    if not message:
        logger.debug("telegram_update_no_message", update_keys=list(update.keys()))
        return {"ok": True}

    text = message.get("text", "").strip()
    chat_id = message.get("chat", {}).get("id")
    user = message.get("from", {})
    username = user.get("username") or user.get("first_name", "unknown")

    if not text or not chat_id:
        return {"ok": True}

    # Handle bot commands
    if text.startswith("/start"):
        await send_telegram_message(
            chat_id,
            "👋 Welcome to *Yuno Agent Platform*!\n\n"
            "I'm connected to a multi-agent AI system.\n"
            "Send me any message and our agents will collaborate to help you.\n\n"
            "Commands:\n"
            "/workflows - Choose workflow to use\n"
            "/status - Check system status\n"
            "/help - Show this message",
        )
        return {"ok": True}

    if text.startswith("/status"):
        from app.redis_client import check_redis_connection
        from app.database import check_database_connection
        db_ok = await check_database_connection()
        redis_ok = await check_redis_connection()
        await send_telegram_message(
            chat_id,
            f"*System Status*\n"
            f"✅ Database: {'Online' if db_ok else '❌ Offline'}\n"
            f"✅ Queue: {'Online' if redis_ok else '❌ Offline'}",
        )
        return {"ok": True}

    if text.startswith("/help"):
        await send_telegram_message(
            chat_id,
            "Send any message to trigger the Research Team workflow.\n"
            "Agents will collaborate and send you a comprehensive response!",
        )
        return {"ok": True}
    if text.startswith("/workflows"):

        result = await db.execute(
            select(Workflow)
            .where(Workflow.is_active == True)
            .order_by(Workflow.created_at.asc())
        )

        workflows = result.scalars().all()

        if not workflows:
            await send_telegram_message(
                chat_id,
                "No workflows available."
            )
            return {"ok": True}

        keyboard = []

        for wf in workflows:
            keyboard.append([{
                "text": wf.name,
                "callback_data": f"wf:{wf.id}"
            }])

        payload = {
            "chat_id": chat_id,
            "text": "📋 Choose a workflow:",
            "reply_markup": {
                "inline_keyboard": keyboard
            }
        }

        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"

        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json=payload)

        return {"ok": True}
    # Find default Telegram workflow (Research Team template preferred)
    selected_workflow_id = TELEGRAM_USER_WORKFLOWS.get(chat_id)

    if selected_workflow_id:

        result = await db.execute(
            select(Workflow)
            .where(Workflow.id == selected_workflow_id)
        )

        workflow = result.scalar_one_or_none()

    else:

        result = await db.execute(
            select(Workflow)
            .where(Workflow.is_active == True)
            .order_by(Workflow.created_at.asc())
            .limit(1)
        )

        workflow = result.scalar_one_or_none()

    if not workflow:
        # Fall back to any active workflow
        result = await db.execute(
            select(Workflow)
            .where(Workflow.is_active == True)
            .limit(1)
        )
        workflow = result.scalar_one_or_none()

    if not workflow:
        await send_telegram_message(
            chat_id,
            "⚠️ No workflows configured yet. Please set up a workflow in the platform.",
        )
        return {"ok": True}

    # Create execution record
    execution = Execution(
        workflow_id=workflow.id,
        status="pending",
        trigger_type="telegram",
        trigger_data={
            "chat_id": chat_id,
            "username": username,
            "user_id": user.get("id"),
        },
        input_message=text,
    )
    db.add(execution)
    await db.commit()
    await db.refresh(execution)

    import asyncio
    from worker.jobs import _execute_workflow_async

    asyncio.create_task(
        _execute_workflow_async(
            str(execution.id),
            workflow.to_dict()
        )
    )

    logger.info(
        "telegram_message_enqueued",
        chat_id=chat_id,
        username=username,
        execution_id=execution.id,
        workflow=workflow.name,
    )

    # Acknowledge receipt
    await send_telegram_message(
        chat_id,
        f"⏳ Processing your request with *{workflow.name}*...\n"
        f"Our agents are collaborating on this.",
    )

    return {"ok": True}


async def send_telegram_message(chat_id: int | str, text: str) -> bool:
    """
    Send a message to a Telegram chat.

    Uses httpx for async HTTP — no blocking calls in the event loop.
    Markdown parse mode for rich formatting.
    """
    if not settings.telegram_bot_token:
        logger.warning("telegram_send_skipped_no_token")
        return False

    import httpx

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, json=payload)
            if response.status_code != 200:
                logger.error(
                    "telegram_send_failed",
                    chat_id=chat_id,
                    status=response.status_code,
                    body=response.text,
                )
                return False
        logger.info("telegram_message_sent", chat_id=chat_id)
        return True
    except Exception as e:
        logger.error("telegram_send_error", chat_id=chat_id, error=str(e))
        return False


@router.get("/status")
async def telegram_status() -> Dict[str, Any]:
    """Check Telegram integration status."""
    return {
        "configured": settings.has_telegram,
        "webhook_url": settings.telegram_webhook_url or "not set",
        "bot_token_set": bool(settings.telegram_bot_token),
    }
