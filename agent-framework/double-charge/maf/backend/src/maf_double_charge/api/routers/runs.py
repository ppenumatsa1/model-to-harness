from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from model_to_harness_shared import WorkflowOutcome

from ...application.models import DurableEvent
from ...projections.workflow_graph import WORKFLOW_GRAPH
from ..dependencies import RepositoryDependency, RunDependency, ServiceDependency, require_run

router = APIRouter()


@router.get("/api/workflow/graph")
async def workflow_graph() -> dict[str, Any]:
    return WORKFLOW_GRAPH


@router.get("/api/runs/{run_id}")
async def get_run(
    run_id: str,
    state: RunDependency,
    repository: RepositoryDependency,
    service: ServiceDependency,
) -> dict[str, Any]:
    return {
        "state": state,
        "memory": await repository.get_memory(state.case_id),
        "outcome": await service.get_outcome(run_id),
        "graph": WORKFLOW_GRAPH,
    }


@router.get("/api/runs/{run_id}/events", response_model=list[DurableEvent])
async def events(
    run_id: str,
    repository: RepositoryDependency,
    service: ServiceDependency,
    after: int = Query(default=0, ge=0),
) -> list[DurableEvent]:
    await require_run(run_id, service)
    return await repository.list_events(run_id, after=after)


@router.get("/api/runs/{run_id}/history", response_model=list[DurableEvent])
async def history(
    run_id: str, state: RunDependency, repository: RepositoryDependency
) -> list[DurableEvent]:
    return await repository.list_events(run_id, after=0)


@router.get("/api/runs/{run_id}/outcome", response_model=WorkflowOutcome)
async def outcome(run_id: str, service: ServiceDependency) -> WorkflowOutcome:
    result = await service.get_outcome(run_id)
    if result is None:
        raise HTTPException(status_code=409, detail="run has not reached a terminal outcome")
    return result
