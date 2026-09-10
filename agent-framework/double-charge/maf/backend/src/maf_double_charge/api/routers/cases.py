from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from model_to_harness_shared import SCENARIO_FIXTURES

from ..dependencies import RepositoryDependency, ServiceDependency
from ..schemas import CaseView, ScenarioInput, StartResponse

router = APIRouter()


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
    return CaseView(
        state=state,
        memory=await repository.get_memory(case_id),
        outcome=await repository.get_outcome(state.run_id),
    )
