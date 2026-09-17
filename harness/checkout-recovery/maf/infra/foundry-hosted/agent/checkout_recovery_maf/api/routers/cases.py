from fastapi import APIRouter, HTTPException, status

from checkout_recovery_maf.api.contracts import ApprovalCommandRequest, StartCaseRequest
from checkout_recovery_maf.api.dependencies import ServiceDependency
from checkout_recovery_maf.application import (
    CaseNotFoundError,
    InvalidCaseCommandError,
)
from checkout_recovery_maf.projections import (
    SafeAuditEventResponse,
    SafeCaseResponse,
    SafeWorkspaceArtifactResponse,
    project_case,
)

router = APIRouter()


@router.post(
    "/cases",
    response_model=SafeCaseResponse,
    status_code=status.HTTP_201_CREATED,
)
def start_case(command: StartCaseRequest, service: ServiceDependency) -> SafeCaseResponse:
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
def get_case(case_id: str, service: ServiceDependency) -> SafeCaseResponse:
    try:
        return service.get_case_response(case_id)
    except CaseNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="case not found"
        ) from error


@router.post("/cases/{case_id}/approval", response_model=SafeCaseResponse)
def record_approval(
    case_id: str,
    command: ApprovalCommandRequest,
    service: ServiceDependency,
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
def resume_case(case_id: str, service: ServiceDependency) -> SafeCaseResponse:
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
def list_events(case_id: str, service: ServiceDependency) -> list[SafeAuditEventResponse]:
    try:
        return service.list_event_responses(case_id)
    except CaseNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="case not found"
        ) from error


@router.get(
    "/cases/{case_id}/workspace-artifact",
    response_model=SafeWorkspaceArtifactResponse,
)
def workspace_artifact(case_id: str, service: ServiceDependency) -> SafeWorkspaceArtifactResponse:
    try:
        return service.get_workspace_artifact_response(case_id)
    except CaseNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="case not found"
        ) from error
