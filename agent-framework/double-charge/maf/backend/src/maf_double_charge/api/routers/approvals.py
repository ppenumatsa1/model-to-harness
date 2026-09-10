from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ...infrastructure.telemetry import telemetry_context
from ..dependencies import ServiceDependency
from ..schemas import ApprovalCommand, ResumeCommand

router = APIRouter()


@router.post("/api/runs/{run_id}/approval")
async def approval(
    run_id: str, command: ApprovalCommand, service: ServiceDependency
) -> dict[str, Any]:
    try:
        with telemetry_context(run_id=run_id):
            state = await service.record_approval(run_id, command.to_command())
            with telemetry_context(case_id=state.case_id):
                return {"status": "recorded", "run_id": run_id, "state": state}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/runs/{run_id}/resume")
async def resume(run_id: str, command: ResumeCommand, service: ServiceDependency) -> dict[str, Any]:
    try:
        with telemetry_context(run_id=run_id):
            state = await service.resume(run_id, command.to_command().checkpoint_id)
            with telemetry_context(case_id=state.case_id):
                return {"status": state.status, "state": state}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
