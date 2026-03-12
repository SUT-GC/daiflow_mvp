"""Single WebSocket endpoint with multiplexed channels.

Protocol:
  Client → Server:
    {"action": "subscribe", "channel": "session:task:42:plan"}
    {"action": "unsubscribe", "channel": "session:task:42:plan"}
    {"action": "chat", "id": "req_1", "chat_path": "plan", "entity_id": "abc", "message": "..."}
    {"action": "ping"}

  Server → Client:
    {"type": "subscribed", "channel": "..."}
    {"type": "pong"}
    {"channel": "...", "event": {...}}
    {"type": "error", "id": "...", "code": "...", "message": "..."}
"""

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from daiflow.database import get_db_session
from daiflow.services.chat_service import prepare_stage_chat
from daiflow.session_runner import run_stage_chat
from daiflow.ws_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter()


async def _handle_chat(ws: WebSocket, data: dict):
    """Handle a chat request in a background task."""
    req_id = data.get("id", "")
    stage = data.get("chat_path", "")
    entity_id = data.get("entity_id", "")
    message = data.get("message", "")
    channel = f"chat:{req_id}"

    if not all([req_id, stage, entity_id, message]):
        try:
            await ws.send_json({
                "type": "error",
                "id": req_id,
                "code": "invalid_request",
                "message": "Missing required fields: id, chat_path, entity_id, message",
            })
        except Exception:
            pass
        return

    try:
        async with get_db_session() as db:
            ctx = await prepare_stage_chat(db, stage, entity_id)

            async with ctx.cody_client:
                async for event in run_stage_chat(
                    ctx.session_id, ctx.cody_client, ctx.cody_session_id,
                    message, ctx.on_tool_result, language=ctx.language,
                ):
                    if ws.client_state != WebSocketState.CONNECTED:
                        return
                    await ws.send_json({"channel": channel, "event": event})

    except ValueError as e:
        try:
            await ws.send_json({
                "type": "error",
                "id": req_id,
                "code": "not_found",
                "message": str(e),
            })
        except Exception:
            pass
    except Exception as e:
        logger.exception("Chat error for request %s", req_id)
        try:
            await ws.send_json({
                "type": "error",
                "id": req_id,
                "code": "internal_error",
                "message": str(e),
            })
        except Exception:
            pass


@router.websocket("/api/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    chat_tasks: list[asyncio.Task] = []

    try:
        while True:
            data = await ws.receive_json()
            action = data.get("action")

            if action == "ping":
                await ws.send_json({"type": "pong"})

            elif action == "subscribe":
                channel = data.get("channel", "")
                if channel:
                    ws_manager.subscribe(ws, channel)
                    await ws.send_json({"type": "subscribed", "channel": channel})

            elif action == "unsubscribe":
                channel = data.get("channel", "")
                if channel:
                    ws_manager.unsubscribe(ws, channel)

            elif action == "chat":
                # Clean up finished tasks first to prevent accumulation
                chat_tasks = [t for t in chat_tasks if not t.done()]
                task = asyncio.create_task(_handle_chat(ws, data))
                chat_tasks.append(task)

            else:
                await ws.send_json({
                    "type": "error",
                    "code": "unknown_action",
                    "message": f"Unknown action: {action}",
                })

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket error")
    finally:
        ws_manager.disconnect(ws)
        # Cancel any running chat tasks
        for task in chat_tasks:
            if not task.done():
                task.cancel()
