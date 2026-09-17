from __future__ import annotations

import base64
import binascii

from pydantic import AwareDatetime, BaseModel, Field, ValidationError

from .models import CaseSummary


class CasePage(BaseModel):
    items: list[CaseSummary]
    next_cursor: str | None = None
    has_more: bool


class CaseCursor(BaseModel):
    created_at: AwareDatetime
    run_id: str = Field(min_length=1, max_length=128)

    def encode(self) -> str:
        return base64.urlsafe_b64encode(self.model_dump_json().encode()).decode().rstrip("=")

    @classmethod
    def decode(cls, value: str) -> CaseCursor:
        try:
            raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
            return cls.model_validate_json(raw)
        except (ValueError, binascii.Error, ValidationError) as error:
            raise ValueError("invalid case history cursor") from error
