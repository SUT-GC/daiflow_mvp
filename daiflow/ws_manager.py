import asyncio
import json
import logging
from collections import defaultdict

from starlette.websockets import WebSocket, WebSocketState

logger = logging.getLogger(__name__)


class WSManager:
    """In-process WebSocket connection manager with channel-based pub/sub.

    Manages WebSocket connections with channel-based pub/sub,
    delivering events directly over WebSocket connections.

    Concurrency note: This class is designed for single-threaded asyncio use.
    The publish() method yields control via ``await ws.send_json()``, so
    concurrent publishes on the same channel are possible. The implementation
    collects dead connections into a separate list before cleanup to avoid
    mutating the iterated set. All callers must run on the same event loop.
    """

    def __init__(self):
        self._channels: dict[str, set[WebSocket]] = defaultdict(set)
        self._conn_channels: dict[int, set[str]] = defaultdict(set)  # id(ws) → channels

    def subscribe(self, ws: WebSocket, channel: str):
        self._channels[channel].add(ws)
        self._conn_channels[id(ws)].add(channel)

    def unsubscribe(self, ws: WebSocket, channel: str):
        conns = self._channels.get(channel)
        if conns:
            conns.discard(ws)
            if not conns:
                del self._channels[channel]
        ch_set = self._conn_channels.get(id(ws))
        if ch_set:
            ch_set.discard(channel)
            if not ch_set:
                del self._conn_channels[id(ws)]

    def disconnect(self, ws: WebSocket):
        """Remove a WebSocket from all its subscribed channels."""
        channels = self._conn_channels.pop(id(ws), set())
        for channel in channels:
            conns = self._channels.get(channel)
            if conns:
                conns.discard(ws)
                if not conns:
                    del self._channels[channel]

    async def publish(self, channel: str, event: dict):
        """Broadcast an event to all subscribers on a channel.

        Dead connections are cleaned up automatically.
        """
        conns = self._channels.get(channel)
        if not conns:
            return

        dead: list[WebSocket] = []
        message = {"channel": channel, "event": event}

        for ws in conns:
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_json(message)
                else:
                    dead.append(ws)
            except Exception:
                logger.debug("Failed to send to WebSocket on channel %s", channel)
                dead.append(ws)

        for ws in dead:
            self.disconnect(ws)

    async def send_to(self, ws: WebSocket, channel: str, event: dict):
        """Send an event directly to a specific WebSocket (for chat responses)."""
        try:
            await ws.send_json({"channel": channel, "event": event})
        except Exception:
            logger.debug("Failed to send direct message on channel %s", channel)

    def cleanup_channel(self, channel: str):
        """Remove a channel and all its subscribers."""
        conns = self._channels.pop(channel, set())
        for ws in conns:
            ch_set = self._conn_channels.get(id(ws))
            if ch_set:
                ch_set.discard(channel)
                if not ch_set:
                    del self._conn_channels[id(ws)]


ws_manager = WSManager()
