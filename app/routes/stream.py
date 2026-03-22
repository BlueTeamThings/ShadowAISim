"""SSE streaming endpoint — fans out event bus messages to connected clients."""

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.core.event_bus import bus

router = APIRouter()


@router.get("/api/stream")
async def sse_stream(request: Request):
    q = bus.subscribe()

    async def generator():
        try:
            # Replay history to new subscriber
            for entry in list(bus.history):
                yield f"data: {json.dumps(entry)}\n\n"

            # Stream live events
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"

        except asyncio.CancelledError:
            pass
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )
