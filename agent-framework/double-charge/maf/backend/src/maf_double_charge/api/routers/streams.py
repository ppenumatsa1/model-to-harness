from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from time import monotonic

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ...projections.agui import project_events
from ...projections.workspace import safe_event
from ..dependencies import ServiceDependency, require_run

router = APIRouter()

_MAX_SEQUENCE = 2**63 - 1
_EVENT_BATCH_SIZE = 200
_POLL_SECONDS = 1
_HEARTBEAT_SECONDS = 15


@router.get("/api/runs/{run_id}/events/stream")
async def audit_stream(
    request: Request,
    run_id: str,
    service: ServiceDependency,
    after: int = Query(default=0, ge=0, le=_MAX_SEQUENCE),
    follow: bool = True,
) -> StreamingResponse:
    header_after = request.headers.get("last-event-id")
    cursor = after
    if header_after is not None:
        if re.fullmatch(r"[0-9]{1,19}", header_after) is None or int(header_after) > _MAX_SEQUENCE:
            raise HTTPException(
                status_code=422, detail="Last-Event-ID must be a valid event sequence"
            )
        cursor = max(cursor, int(header_after))
    await require_run(run_id, service)

    async def stream() -> AsyncIterator[str]:
        nonlocal cursor
        previous_snapshot: str | None = None
        last_sent = monotonic()
        try:
            while not await request.is_disconnected():
                # Application queries release connections before any yield or idle wait.
                durable = await service.list_events(
                    run_id, after=cursor, limit=_EVENT_BATCH_SIZE
                )
                for item in durable:
                    if await request.is_disconnected():
                        return
                    yield (
                        f"event: audit\nid: {item.sequence}\n"
                        f"data: {safe_event(item).model_dump_json()}\n\n"
                    )
                    cursor = item.sequence
                    last_sent = monotonic()

                if await request.is_disconnected():
                    return
                snapshot = (await service.get_workspace(run_id)).model_dump_json()
                if snapshot != previous_snapshot:
                    yield f"event: snapshot\ndata: {snapshot}\n\n"
                    previous_snapshot = snapshot
                    last_sent = monotonic()

                # A terminal event can precede outcome/native audit commits. Keep following.
                if len(durable) == _EVENT_BATCH_SIZE:
                    continue
                if not follow:
                    return
                if monotonic() - last_sent >= _HEARTBEAT_SECONDS:
                    yield ": keepalive\n\n"
                    last_sent = monotonic()
                await asyncio.sleep(_POLL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception:
            if not await request.is_disconnected():
                yield (
                    "event: error\n"
                    'data: {"message":"Live updates are unavailable. Reconnect."}\n\n'
                )

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/runs/{run_id}/ag-ui")
async def ag_ui_stream(
    request: Request,
    run_id: str,
    service: ServiceDependency,
    after: int = Query(default=0, ge=0),
    follow: bool = False,
) -> StreamingResponse:
    state = await require_run(run_id, service)
    header_after = request.headers.get("last-event-id")
    cursor = max(after, int(header_after)) if header_after and header_after.isdigit() else after

    async def stream() -> AsyncIterator[str]:
        nonlocal cursor, state
        idle_ticks = 0
        while True:
            durable = await service.list_events(run_id, after=cursor)
            if durable:
                state = await service.get_state(run_id)
                for item in durable:
                    for projected in project_events([item], state):
                        yield f"id: {item.sequence}\ndata: {json.dumps(projected)}\n\n"
                    cursor = item.sequence
                idle_ticks = 0
            else:
                yield ": keepalive\n\n"
                idle_ticks += 1
            if not follow or idle_ticks >= 30:
                break
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream")
