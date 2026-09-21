from datetime import datetime

from pydantic import BaseModel, ConfigDict

from checkout_recovery_copilot.application.models import AuditEvent, CaseRecord, WorkspaceArtifact


class SafeWorkspaceArtifactResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str
    kind: str
    revision: int
    updated_at: datetime


class SafeAuditEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    occurred_at: datetime
    summary: str


class SafeCaseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    run_id: str
    fixture_id: str
    phase: str
    diagnostic_disposition: str | None
    approval_decision: str
    approval_request_id: str | None
    diagnostic_tools: tuple[str, ...]
    harness_mode: str
    remediation_action: str | None
    remediation_status: str | None
    verification_result: bool | None
    terminal_status: str | None
    failure_code: str
    workspace_artifact: SafeWorkspaceArtifactResponse


def project_case(case: CaseRecord) -> SafeCaseResponse:
    return SafeCaseResponse(
        case_id=case.case_id,
        run_id=case.run_id,
        fixture_id=case.fixture_id,
        phase=case.phase,
        diagnostic_disposition=case.diagnostic_disposition,
        approval_decision=case.approval_decision,
        approval_request_id=case.approval_request_id,
        diagnostic_tools=case.diagnostic_tools,
        harness_mode=case.harness_mode,
        remediation_action=case.remediation_action,
        remediation_status=case.remediation_status,
        verification_result=case.verification_result,
        terminal_status=case.terminal_status,
        failure_code=case.failure_code,
        workspace_artifact=project_artifact(case.artifact),
    )


def project_artifact(artifact: WorkspaceArtifact) -> SafeWorkspaceArtifactResponse:
    return SafeWorkspaceArtifactResponse(
        artifact_id=artifact.artifact_id,
        kind=artifact.kind,
        revision=artifact.revision,
        updated_at=artifact.updated_at,
    )


def project_event(event: AuditEvent) -> SafeAuditEventResponse:
    return SafeAuditEventResponse(
        code=event.code,
        occurred_at=event.occurred_at,
        summary=event.summary,
    )
