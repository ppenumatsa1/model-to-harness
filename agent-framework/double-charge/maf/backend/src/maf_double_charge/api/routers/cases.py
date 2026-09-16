from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from model_to_harness_shared import SCENARIO_FIXTURES

from ...application.history import CaseCursor
from ...projections.workspace import workspace_view
from ..dependencies import RepositoryDependency, ServiceDependency
from ..schemas import CasePage, CaseView, ScenarioInput, StartResponse

router = APIRouter()


@router.get("/api/cases", response_model=CasePage)
async def list_cases(
    repository: RepositoryDependency,
    limit: int = Query(default=10, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=512),
) -> CasePage:
    try:
        before = CaseCursor.decode(cursor) if cursor is not None else None
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    records = await repository.list_cases(
        limit + 1, (before.created_at, before.run_id) if before else None
    )
    items = records[:limit]
    has_more = len(records) > limit
    next_cursor = (
        CaseCursor(created_at=items[-1].created_at, run_id=items[-1].run_id).encode()
        if has_more else None
    )
    return CasePage(items=items, next_cursor=next_cursor, has_more=has_more)


@router.get("/api/scenarios")
async def scenarios() -> list[dict[str, Any]]:
    return [
        {
            "id": fixture.fixture_id,
            "description": fixture.description,
            "expected_terminal_status": fixture.expected.terminal_status,
            "tags": sorted(fixture.tags),
        }
        for fixture in SCENARIO_FIXTURES.values()
        if fixture.fixture_id != "verification-mismatch"
    ]


@router.post("/api/cases", response_model=StartResponse)
async def start_case(command: ScenarioInput, service: ServiceDependency) -> StartResponse:
    try:
        result = await service.start(command.to_command())
        return StartResponse.model_validate(result, from_attributes=True)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/cases/{case_id}", response_model=CaseView)
async def get_case(case_id: str, repository: RepositoryDependency) -> CaseView:
    state = await repository.get_state_by_case(case_id)
    if state is None:
        raise HTTPException(status_code=404, detail="case not found")
    return CaseView.model_validate(await workspace_view(repository, state), from_attributes=True)
