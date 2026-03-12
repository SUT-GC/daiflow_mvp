"""Tests for daiflow.ws_manager module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from starlette.websockets import WebSocketState

from daiflow.ws_manager import WSManager


def _make_mock_ws(connected=True):
    """Create a mock WebSocket that records sent messages."""
    ws = MagicMock()
    ws.send_json = AsyncMock()
    state = WebSocketState.CONNECTED if connected else WebSocketState.DISCONNECTED
    type(ws).client_state = PropertyMock(return_value=state)
    return ws


class TestWSManager:
    async def test_subscribe_and_publish(self):
        mgr = WSManager()
        ws = _make_mock_ws()
        mgr.subscribe(ws, "ch1")
        await mgr.publish("ch1", {"type": "test", "data": 1})
        ws.send_json.assert_called_once_with({
            "channel": "ch1",
            "event": {"type": "test", "data": 1},
        })

    async def test_unsubscribe(self):
        mgr = WSManager()
        ws = _make_mock_ws()
        mgr.subscribe(ws, "ch1")
        mgr.unsubscribe(ws, "ch1")
        await mgr.publish("ch1", {"type": "test"})
        ws.send_json.assert_not_called()

    async def test_multiple_subscribers(self):
        mgr = WSManager()
        ws1 = _make_mock_ws()
        ws2 = _make_mock_ws()
        mgr.subscribe(ws1, "ch1")
        mgr.subscribe(ws2, "ch1")
        await mgr.publish("ch1", {"type": "hello"})
        ws1.send_json.assert_called_once()
        ws2.send_json.assert_called_once()

    async def test_publish_to_nonexistent_channel(self):
        mgr = WSManager()
        # Should not raise
        await mgr.publish("nope", {"type": "test"})

    async def test_unsubscribe_nonexistent(self):
        mgr = WSManager()
        ws = _make_mock_ws()
        # Should not raise
        mgr.unsubscribe(ws, "nope")

    async def test_disconnect_cleans_all_channels(self):
        mgr = WSManager()
        ws = _make_mock_ws()
        mgr.subscribe(ws, "ch1")
        mgr.subscribe(ws, "ch2")
        mgr.disconnect(ws)
        await mgr.publish("ch1", {"type": "test"})
        await mgr.publish("ch2", {"type": "test"})
        ws.send_json.assert_not_called()
        assert "ch1" not in mgr._channels
        assert "ch2" not in mgr._channels

    async def test_dead_connection_cleanup(self):
        mgr = WSManager()
        ws = _make_mock_ws()
        ws.send_json.side_effect = Exception("Connection closed")
        mgr.subscribe(ws, "ch1")
        await mgr.publish("ch1", {"type": "test"})
        # Dead connection should be removed
        assert "ch1" not in mgr._channels

    async def test_cleanup_channel(self):
        mgr = WSManager()
        ws1 = _make_mock_ws()
        ws2 = _make_mock_ws()
        mgr.subscribe(ws1, "ch1")
        mgr.subscribe(ws2, "ch1")
        mgr.cleanup_channel("ch1")
        assert "ch1" not in mgr._channels

    async def test_cleanup_nonexistent_channel(self):
        mgr = WSManager()
        # Should not raise
        mgr.cleanup_channel("nope")

    async def test_unsubscribe_removes_empty_channel(self):
        mgr = WSManager()
        ws = _make_mock_ws()
        mgr.subscribe(ws, "ch1")
        mgr.unsubscribe(ws, "ch1")
        assert "ch1" not in mgr._channels

    async def test_independent_channels(self):
        mgr = WSManager()
        ws1 = _make_mock_ws()
        ws2 = _make_mock_ws()
        mgr.subscribe(ws1, "ch1")
        mgr.subscribe(ws2, "ch2")
        await mgr.publish("ch1", {"type": "a"})
        ws1.send_json.assert_called_once()
        ws2.send_json.assert_not_called()

    async def test_send_to(self):
        mgr = WSManager()
        ws = _make_mock_ws()
        await mgr.send_to(ws, "chat:req_1", {"type": "text_delta", "content": "hi"})
        ws.send_json.assert_called_once_with({
            "channel": "chat:req_1",
            "event": {"type": "text_delta", "content": "hi"},
        })

    async def test_send_to_handles_error(self):
        mgr = WSManager()
        ws = _make_mock_ws()
        ws.send_json.side_effect = Exception("closed")
        # Should not raise
        await mgr.send_to(ws, "chat:req_1", {"type": "test"})

    async def test_multiple_channels_per_connection(self):
        mgr = WSManager()
        ws = _make_mock_ws()
        mgr.subscribe(ws, "ch1")
        mgr.subscribe(ws, "ch2")
        await mgr.publish("ch1", {"type": "a"})
        await mgr.publish("ch2", {"type": "b"})
        assert ws.send_json.call_count == 2
