from fastapi import APIRouter, Depends, HTTPException, status

from checkout_recovery_maf.application import (
    CaseNotFoundError,
    CheckoutRecoveryService,
    InvalidCaseCommandError,
)
from checkout_recovery_maf.projections import (
    SafeAuditEventResponse,
    SafeCaseResponse,
    SafeWorkspaceArtifactResponse,
    project_artifact,
    project_case,
    project_event,
)

from .contracts import ApprovalCommandRequest, StartCaseRequest

router = APIRouter()


def get_service() -> CheckoutRecoveryService:
    raise RuntimeError("application service dependency was not initialized")


@router.get("/health/live", status_code=status.HTTP_200_OK)
def live() -> dict[str, str]:
    return {"status": "live"}


@router.get("/health/ready", status_code=status.HTTP_200_OK)
def ready(service: CheckoutRecoveryService = Depends(get_service)) -> dict[str, str]:
    if not service.ready():
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ready"}


@router.post(
    "/cases",
    response_model=SafeCaseResponse,
    status_code=status.HTTP_201_CREATED,
)
def start_case(
    command: StartCaseRequest, service: CheckoutRecoveryService = Depends(get_service)
) -> SafeCaseResponse:
    try:
        return project_case(
            service.start_case(
                command.fixture_id, str(command.request_id) if command.request_id else None
            )
        )
    except InvalidCaseCommandError as error:
        raise HTTPException(status_code=409, detail="start request conflicts") from error
    except KeyError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="fixture not found"
        ) from error


@router.get("/cases/{case_id}", response_model=SafeCaseResponse)
def get_case(
    case_id: str, service: CheckoutRecoveryService = Depends(get_service)
) -> SafeCaseResponse:
    return project_case(_find_case(service, case_id))


@router.post("/cases/{case_id}/approval", response_model=SafeCaseResponse)
def record_approval(
    case_id: str,
    command: ApprovalCommandRequest,
    service: CheckoutRecoveryService = Depends(get_service),
) -> SafeCaseResponse:
    try:
        return project_case(
            service.record_approval(
                case_id,
                decision=command.decision,
                reviewer_id=command.reviewer_id,
                approval_request_id=str(command.approval_request_id),
                reason=command.reason,
            )
        )
    except CaseNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="case not found"
        ) from error
    except InvalidCaseCommandError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="approval rejected"
        ) from error


@router.post("/cases/{case_id}/resume", response_model=SafeCaseResponse)
def resume_case(
    case_id: str, service: CheckoutRecoveryService = Depends(get_service)
) -> SafeCaseResponse:
    try:
        return project_case(service.resume_case(case_id))
    except CaseNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="case not found"
        ) from error
    except InvalidCaseCommandError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="resume rejected"
        ) from error


@router.get("/cases/{case_id}/events", response_model=list[SafeAuditEventResponse])
def list_events(
    case_id: str, service: CheckoutRecoveryService = Depends(get_service)
) -> list[SafeAuditEventResponse]:
    try:
        return [project_event(event) for event in service.events(case_id)]
    except CaseNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="case not found"
        ) from error


@router.get(
    "/cases/{case_id}/workspace-artifact",
    response_model=SafeWorkspaceArtifactResponse,
)
def workspace_artifact(
    case_id: str, service: CheckoutRecoveryService = Depends(get_service)
) -> SafeWorkspaceArtifactResponse:
    return project_artifact(_find_case(service, case_id).artifact)


def _find_case(service: CheckoutRecoveryService, case_id: str):
    try:
        return service.get_case(case_id)
    except CaseNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="case not found"
        ) from error
