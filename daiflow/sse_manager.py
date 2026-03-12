import asyncio
from collections import defaultdict


class SSEManager:
    """In-process pub/sub using asyncio.Queue for SSE streaming."""

    def __init__(self):
        self._channels: dict[str, list[asyncio.Queue]] = defaultdict(list)

    def subscribe(self, channel: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1024)
        self._channels[channel].append(queue)
        return queue

    async def publish(self, channel: str, event: dict):
        dead: list[asyncio.Queue] = []
        for queue in self._channels.get(channel, []):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(queue)
        # Clean up dead queues
        for q in dead:
            self.unsubscribe(channel, q)

    def unsubscribe(self, channel: str, queue: asyncio.Queue):
        queues = self._channels.get(channel, [])
        if queue in queues:
            queues.remove(queue)
        if not queues:
            self._channels.pop(channel, None)

    def cleanup_channel(self, channel: str):
        """Remove a channel and all its subscribers."""
        self._channels.pop(channel, None)


sse_manager = SSEManager()
