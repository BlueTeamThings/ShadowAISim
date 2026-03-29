"""
Async pub-sub event bus for real-time SSE streaming.

Each SSE client subscribes and gets its own asyncio.Queue.
Background tasks emit events; the bus fans them out to all queues.
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._queues: list[asyncio.Queue] = []
        self.history: list[dict] = []

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._queues:
            self._queues.remove(q)

    # ------------------------------------------------------------------
    # Event emission
    # ------------------------------------------------------------------

    async def emit(
        self,
        level: str,
        category: str,
        message: str,
        target: str = "",
        data_type: str = "",
        **extra: Any,
    ) -> None:
        entry: dict = {
            "ts":        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level":     level,
            "category":  category,
            "message":   message,
            "target":    target,
            "data_type": data_type,
            **extra,
        }
        self.history.append(entry)
        serialized = json.dumps(entry)
        for q in list(self._queues):
            await q.put(serialized)

    def clear_history(self) -> None:
        self.history.clear()


bus = EventBus()
