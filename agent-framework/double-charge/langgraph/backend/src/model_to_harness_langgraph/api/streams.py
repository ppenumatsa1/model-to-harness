import asyncio
import re
from collections.abc import AsyncIterator
from time import monotonic

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

from ..application.service import WorkflowService

MAX_SEQUENCE = 2**63 - 1
EVENT_BATCH_SIZE = 200
POLL_SECONDS = 1
HEARTBEAT_SECONDS = 15


async def audit_stream(
    request: Request,
    service: WorkflowService,
    case_id: str,
    after: int,
    follow: bool,
) -> StreamingResponse:
    header = request.headers.get("last-event-id")
    if header is not None:
        if re.fullmatch(r"[0-9]{1,19}", header) is None or int(header) > MAX_SEQUENCE:
            raise HTTPException(status_code=422, detail="Last-Event-ID must be an event sequence")
        after = max(after, int(header))
    await service.get_case(case_id)

    async def generate() -> AsyncIterator[str]:
        cursor = after
        previous_snapshot: str | None = None
        last_sent = monotonic()
        try:
            while not await request.is_disconnected():
                events = await service.list_events(case_id, cursor, EVENT_BATCH_SIZE)
                for event in events:
                    if await request.is_disconnected():
                        return
                    yield f"event: audit\nid: {event.sequence}\ndata: {event.model_dump_json()}\n\n"
                    cursor = event.sequence
                    last_sent = monotonic()
                if await request.is_disconnected():
                    return
                snapshot = (await service.workspace(case_id)).model_dump_json()
                if snapshot != previous_snapshot:
                    yield f"event: snapshot\ndata: {snapshot}\n\n"
                    previous_snapshot = snapshot
                    last_sent = monotonic()
                if len(events) == EVENT_BATCH_SIZE:
                    continue
                if not follow:
                    return
                if monotonic() - last_sent >= HEARTBEAT_SECONDS:
                    yield ": keepalive\n\n"
                    last_sent = monotonic()
                await asyncio.sleep(POLL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception:
            if not await request.is_disconnected():
                yield 'event: error\ndata: {"message":"Live updates unavailable. Reconnect."}\n\n'

    return StreamingResponse(
        generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
