from pydantic import BaseModel


class ApprovalRequest(BaseModel):
    case_id: str
    run_id: str
    evidence_summary: str
    amount: str | None = None
    currency: str | None = None
