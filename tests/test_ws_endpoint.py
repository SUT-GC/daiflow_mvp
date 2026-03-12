"""Integration tests for the WebSocket endpoint."""

import pytest
from starlette.testclient import TestClient

from daiflow.main import app
from daiflow.ws_manager import ws_manager


class TestWebSocketEndpoint:
    def test_ping_pong(self):
        client = TestClient(app)
        with client.websocket_connect("/api/ws") as ws:
            ws.send_json({"action": "ping"})
            resp = ws.receive_json()
            assert resp == {"type": "pong"}

    def test_subscribe_ack(self):
        client = TestClient(app)
        with client.websocket_connect("/api/ws") as ws:
            ws.send_json({"action": "subscribe", "channel": "session:test:1"})
            resp = ws.receive_json()
            assert resp == {"type": "subscribed", "channel": "session:test:1"}

    def test_unknown_action(self):
        client = TestClient(app)
        with client.websocket_connect("/api/ws") as ws:
            ws.send_json({"action": "foobar"})
            resp = ws.receive_json()
            assert resp["type"] == "error"
            assert resp["code"] == "unknown_action"

    def test_chat_missing_fields(self):
        client = TestClient(app)
        with client.websocket_connect("/api/ws") as ws:
            ws.send_json({"action": "chat", "id": "req_1"})
            resp = ws.receive_json()
            assert resp["type"] == "error"
            assert resp["code"] == "invalid_request"
            assert resp["id"] == "req_1"

    def test_disconnect_cleans_subscriptions(self):
        client = TestClient(app)
        with client.websocket_connect("/api/ws") as ws:
            ws.send_json({"action": "subscribe", "channel": "session:cleanup:test"})
            ws.receive_json()  # subscribed ack
        # After disconnect, channel should be cleaned up
        assert "session:cleanup:test" not in ws_manager._channels
