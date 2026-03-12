import json
import traceback
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from daiflow.config import FILE_WRITE_TOOLS, LANGUAGE_INSTRUCTIONS, SESSIONS_DIR, safe_filename
from daiflow.models import Session, SessionStatus
from daiflow.ws_manager import ws_manager


def _now():
    return datetime.now(timezone.utc)


def _chunk_to_event(chunk) -> dict | None:
    """Convert a Cody StreamChunk to a DaiFlow event dict."""
    t = chunk.type
    if t == "text_delta":
        return {"type": "text_delta", "content": chunk.content}
    elif t == "thinking":
        return {"type": "thinking", "content": chunk.content}
    elif t == "tool_call":
        return {
            "type": "tool_call",
            "tool_name": chunk.tool_name,
            "args": chunk.args if hasattr(chunk, "args") else {},
            "tool_call_id": chunk.tool_call_id if hasattr(chunk, "tool_call_id") else "",
        }
    elif t == "tool_result":
        return {
            "type": "tool_result",
            "content": chunk.content if hasattr(chunk, "content") else "",
            "tool_name": chunk.tool_name if hasattr(chunk, "tool_name") else "",
            "tool_call_id": chunk.tool_call_id if hasattr(chunk, "tool_call_id") else "",
        }
    elif t == "compact":
        return None  # logged only, not pushed
    elif t == "done":
        return {
            "type": "done",
            "usage": {
                "input_tokens": chunk.usage.input_tokens if hasattr(chunk, "usage") and chunk.usage else 0,
                "output_tokens": chunk.usage.output_tokens if hasattr(chunk, "usage") and chunk.usage else 0,
            },
        }
    return None


def _log_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{safe_filename(session_id)}.jsonl"


def _append_log(session_id: str, event: dict):
    path = _log_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


class SessionRunner:
    """Unified AI task executor that wraps a Cody client.

    Supports client reuse across sessions (e.g. plan + todo share one client).
    """

    def __init__(self, cody_client):
        self.client = cody_client
        self._last_cody_session_id: str | None = None
        self._tool_call_args: dict[str, dict] = {}  # tool_call_id -> args cache

    @property
    def last_cody_session_id(self) -> str | None:
        return self._last_cody_session_id

    async def run(
        self,
        db: AsyncSession,
        session_id: str,
        prompt: str,
        extra_channels: list[str] | None = None,
        on_tool_result=None,
        cody_session_id: str | None = None,
        language: str | None = None,
    ):
        """Execute a Cody task with full lifecycle management.

        Args:
            db: Database session (must be an independent session for background tasks)
            session_id: DaiFlow business session ID
            prompt: The prompt to send to Cody
            extra_channels: Additional WebSocket channels to publish status to
            on_tool_result: Optional callback(event) for detecting file writes
            cody_session_id: Optional Cody session ID to continue a previous conversation
            language: Language code (e.g. 'zh', 'en') to append language instruction
        """
        if language:
            prompt = prompt + LANGUAGE_INSTRUCTIONS.get(language, "")
        channel = f"session:{session_id}"

        # Update session status to running
        await db.execute(
            update(Session)
            .where(Session.session_id == session_id)
            .values(status=SessionStatus.RUNNING, started_at=_now())
        )
        await db.commit()

        # Log user message
        user_event = {"type": "user_message", "content": prompt, "ts": _now().isoformat()}
        _append_log(session_id, user_event)

        try:
            result_cody_session_id = None
            stream_kwargs = {}
            if cody_session_id:
                stream_kwargs["session_id"] = cody_session_id

            async for chunk in self.client.stream(prompt, **stream_kwargs):
                event = _chunk_to_event(chunk)
                if event is None:
                    _append_log(session_id, {"type": "compact", "ts": _now().isoformat()})
                    continue

                event["ts"] = _now().isoformat()
                _append_log(session_id, event)

                if event["type"] == "done":
                    if hasattr(chunk, "session_id"):
                        result_cody_session_id = chunk.session_id

                    status_event = {"type": "status_change", "status": SessionStatus.DONE, "ts": event["ts"]}
                    await ws_manager.publish(channel, status_event)
                    _append_log(session_id, status_event)

                    if extra_channels:
                        for ch in extra_channels:
                            await ws_manager.publish(ch, {
                                "type": "session_status",
                                "session_id": session_id,
                                "status": SessionStatus.DONE,
                                "ts": event["ts"],
                            })
                else:
                    await ws_manager.publish(channel, event)

                    # Cache tool_call args for later association with tool_result
                    if event["type"] == "tool_call":
                        call_id = event.get("tool_call_id", "")
                        if call_id:
                            self._tool_call_args[call_id] = event.get("args", {})

                    if event["type"] == "tool_result" and on_tool_result:
                        # Enrich tool_result with cached args from tool_call
                        call_id = event.get("tool_call_id", "")
                        if call_id and call_id in self._tool_call_args:
                            event["args"] = self._tool_call_args.pop(call_id)
                        extra_event = await on_tool_result(event)
                        if extra_event:
                            _append_log(session_id, extra_event)
                            await ws_manager.publish(channel, extra_event)

            self._last_cody_session_id = result_cody_session_id

            # Update session to done
            await db.execute(
                update(Session)
                .where(Session.session_id == session_id)
                .values(
                    status=SessionStatus.DONE,
                    cody_session_id=result_cody_session_id,
                    finished_at=_now(),
                )
            )
            await db.commit()

        except Exception as e:
            error_msg = traceback.format_exc()
            error_event = {"type": "error", "content": str(e), "ts": _now().isoformat()}
            _append_log(session_id, error_event)

            status_event = {"type": "status_change", "status": SessionStatus.FAILED, "error": str(e), "ts": _now().isoformat()}
            await ws_manager.publish(channel, status_event)

            if extra_channels:
                for ch in extra_channels:
                    await ws_manager.publish(ch, {
                        "type": "session_status",
                        "session_id": session_id,
                        "status": SessionStatus.FAILED,
                        "error": str(e),
                        "ts": _now().isoformat(),
                    })

            await db.execute(
                update(Session)
                .where(Session.session_id == session_id)
                .values(status=SessionStatus.FAILED, error=error_msg, finished_at=_now())
            )
            await db.commit()


async def run_stage_chat(
    session_id: str,
    cody_client,
    cody_session_id: str,
    message: str,
    on_tool_result=None,
    language: str | None = None,
):
    """
    Stage chat async generator. Yields raw event dicts.

    Used by WS handler. The caller sends events via ws.send_json.
    """
    if language:
        message = message + LANGUAGE_INSTRUCTIONS.get(language, "")

    # Log user message
    user_event = {"type": "user_message", "content": message, "ts": _now().isoformat()}
    _append_log(session_id, user_event)

    # Cache tool_call args for association with tool_result
    tool_call_args: dict[str, dict] = {}

    try:
        stream_kwargs = {}
        if cody_session_id:
            stream_kwargs["session_id"] = cody_session_id

        async for chunk in cody_client.stream(message, **stream_kwargs):
            event = _chunk_to_event(chunk)
            if event is None:
                continue

            event["ts"] = _now().isoformat()
            _append_log(session_id, event)

            if event["type"] == "done":
                yield {"type": "done"}
                return

            yield event

            # Cache tool_call args for later association with tool_result
            if event["type"] == "tool_call":
                call_id = event.get("tool_call_id", "")
                if call_id:
                    tool_call_args[call_id] = event.get("args", {})

            # Detect file writes for *_updated events
            if event["type"] == "tool_result" and on_tool_result:
                # Enrich tool_result with cached args from tool_call
                call_id = event.get("tool_call_id", "")
                if call_id and call_id in tool_call_args:
                    event["args"] = tool_call_args.pop(call_id)
                updated_event = await on_tool_result(event)
                if updated_event:
                    _append_log(session_id, updated_event)
                    yield updated_event

    except Exception as e:
        error_event = {"type": "error", "content": str(e), "ts": _now().isoformat()}
        _append_log(session_id, error_event)
        yield error_event


def _extract_file_path(event: dict) -> str:
    """Extract file path from a tool_result event's args."""
    args = event.get("args", {})
    if isinstance(args, dict):
        return args.get("path", args.get("file_path", ""))
    if isinstance(args, str):
        return args
    return ""


def make_file_write_detector(target_file: str | None, event_type: str, on_match=None):
    """Factory for on_tool_result callbacks that detect file writes.

    Args:
        target_file: Filename to match (e.g. "plan.md"), or None to match any write.
        event_type: Event type to emit (e.g. "plan_updated", "code_updated").
        on_match: Optional async callback(file_path) called on match, returns event content or None.
    """
    async def on_tool_result(event: dict):
        tool_name = event.get("tool_name", "")
        if tool_name not in FILE_WRITE_TOOLS:
            return None

        if target_file is None:
            # Match any file write
            content = await on_match(None) if on_match else None
            return {"type": event_type, "content": content}

        file_path = _extract_file_path(event)
        if file_path and (target_file in file_path):
            content = await on_match(file_path) if on_match else None
            return {"type": event_type, "content": content}

        return None

    return on_tool_result
