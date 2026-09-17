from fastapi import APIRouter, HTTPException, status

from checkout_recovery_maf.api.dependencies import ServiceDependency

router = APIRouter()


@router.get("/health/live", status_code=status.HTTP_200_OK)
def live() -> dict[str, str]:
    return {"status": "live"}


@router.get("/health/ready", status_code=status.HTTP_200_OK)
def ready(service: ServiceDependency) -> dict[str, str]:
    if not service.ready():
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ready"}
