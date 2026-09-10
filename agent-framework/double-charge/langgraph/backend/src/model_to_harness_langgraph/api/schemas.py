from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ExplainRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)


class ExplainResponse(BaseModel):
    answer: str
    cited_sequences: list[int] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: bool
    model_configured: bool
    shared_package: bool


class CopilotRunPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    thread_id: str = Field(
        alias="threadId",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    run_id: str = Field(
        alias="runId",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
