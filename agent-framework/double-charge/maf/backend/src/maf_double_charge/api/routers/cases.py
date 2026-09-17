from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from model_to_harness_shared import SCENARIO_FIXTURES

from ..dependencies import ServiceDependency
from ..schemas import CasePage, CaseView, ScenarioInput, StartResponse

router = APIRouter()


@router.get("/api/cases", response_model=CasePage)
async def list_cases(
    service: ServiceDependency,
    limit: int = Query(default=10, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=512),
) -> CasePage:
    try:
        page = await service.list_cases(limit, cursor)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return CasePage.model_validate(page, from_attributes=True)


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
async def get_case(case_id: str, service: ServiceDependency) -> CaseView:
    try:
        workspace = await service.get_case_workspace(case_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="case not found") from exc
    return CaseView.model_validate(workspace, from_attributes=True)
