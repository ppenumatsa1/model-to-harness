from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..dependencies import RepositoryDependency

router = APIRouter()


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(repository: RepositoryDependency) -> dict[str, str]:
    try:
        await repository.check_ready()
        return {"status": "ready"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database is not ready") from exc
