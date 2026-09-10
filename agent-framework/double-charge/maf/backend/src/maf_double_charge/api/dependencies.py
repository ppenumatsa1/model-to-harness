from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from ..application.models import WorkflowState
from ..application.ports import ModelClient, Repository
from ..application.service import DoubleChargeService
from ..bootstrap import Runtime


def get_runtime(request: Request) -> Runtime:
    return request.app.state.runtime


def get_service(runtime: Annotated[Runtime, Depends(get_runtime)]) -> DoubleChargeService:
    return runtime.service


def get_repository(runtime: Annotated[Runtime, Depends(get_runtime)]) -> Repository:
    return runtime.repository


def get_model(runtime: Annotated[Runtime, Depends(get_runtime)]) -> ModelClient:
    return runtime.model


ServiceDependency = Annotated[DoubleChargeService, Depends(get_service)]
RepositoryDependency = Annotated[Repository, Depends(get_repository)]
ModelDependency = Annotated[ModelClient, Depends(get_model)]


async def require_run(run_id: str, service: ServiceDependency) -> WorkflowState:
    try:
        return await service.get_state(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc


RunDependency = Annotated[WorkflowState, Depends(require_run)]
