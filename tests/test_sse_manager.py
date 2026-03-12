"""Tests for daiflow.sse_manager module."""

import asyncio

from daiflow.sse_manager import SSEManager


class TestSSEManager:
    async def test_subscribe_and_publish(self):
        mgr = SSEManager()
        q = mgr.subscribe("ch1")
        await mgr.publish("ch1", {"type": "test", "data": 1})
        event = q.get_nowait()
        assert event == {"type": "test", "data": 1}

    async def test_unsubscribe(self):
        mgr = SSEManager()
        q = mgr.subscribe("ch1")
        mgr.unsubscribe("ch1", q)
        await mgr.publish("ch1", {"type": "test"})
        assert q.empty()

    async def test_multiple_subscribers(self):
        mgr = SSEManager()
        q1 = mgr.subscribe("ch1")
        q2 = mgr.subscribe("ch1")
        await mgr.publish("ch1", {"type": "hello"})
        assert q1.get_nowait() == {"type": "hello"}
        assert q2.get_nowait() == {"type": "hello"}

    async def test_publish_to_nonexistent_channel(self):
        mgr = SSEManager()
        # Should not raise
        await mgr.publish("nope", {"type": "test"})

    async def test_unsubscribe_nonexistent(self):
        mgr = SSEManager()
        q = asyncio.Queue()
        # Should not raise
        mgr.unsubscribe("nope", q)

    async def test_queue_full_cleans_dead_subscriber(self):
        mgr = SSEManager()
        q = mgr.subscribe("ch1")
        # Fill the queue to capacity (maxsize=1024)
        for i in range(1024):
            await mgr.publish("ch1", {"i": i})
        # Queue is full now. Next publish should trigger cleanup.
        await mgr.publish("ch1", {"type": "overflow"})
        # The dead queue should have been removed
        assert q not in mgr._channels.get("ch1", [])

    async def test_cleanup_channel(self):
        mgr = SSEManager()
        mgr.subscribe("ch1")
        mgr.subscribe("ch1")
        mgr.cleanup_channel("ch1")
        assert "ch1" not in mgr._channels

    async def test_cleanup_nonexistent_channel(self):
        mgr = SSEManager()
        # Should not raise
        mgr.cleanup_channel("nope")

    async def test_unsubscribe_removes_empty_channel(self):
        mgr = SSEManager()
        q = mgr.subscribe("ch1")
        mgr.unsubscribe("ch1", q)
        assert "ch1" not in mgr._channels

    async def test_independent_channels(self):
        mgr = SSEManager()
        q1 = mgr.subscribe("ch1")
        q2 = mgr.subscribe("ch2")
        await mgr.publish("ch1", {"type": "a"})
        assert not q2.empty() is False or q2.qsize() == 0
        assert q1.get_nowait() == {"type": "a"}
        assert q2.empty()
