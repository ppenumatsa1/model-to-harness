from fastapi import APIRouter, HTTPException, status

from checkout_recovery_copilot.api.dependencies import RuntimeHealthDependency

router = APIRouter()


@router.get("/health/live", status_code=status.HTTP_200_OK)
def live() -> dict[str, str]:
    return {"status": "live"}


@router.get("/health/ready", status_code=status.HTTP_200_OK)
def ready(health: RuntimeHealthDependency) -> dict[str, str]:
    if not health.ready():
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ready"}
