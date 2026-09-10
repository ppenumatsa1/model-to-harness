from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from ...projections.agui import project_events
from ..dependencies import RepositoryDependency, ServiceDependency, require_run

router = APIRouter()


@router.get("/api/runs/{run_id}/ag-ui")
async def ag_ui_stream(
    request: Request,
    run_id: str,
    repository: RepositoryDependency,
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
            durable = await repository.list_events(run_id, after=cursor)
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
