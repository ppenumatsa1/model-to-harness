import base64
import binascii
import json
from datetime import datetime


def encode_cursor(created_at: datetime, run_id: str) -> str:
    value = json.dumps([created_at.isoformat(), run_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if cursor is None:
        return None
    try:
        if not cursor or len(cursor) > 1024:
            raise ValueError
        raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        value = json.loads(raw)
        if (
            not isinstance(value, list)
            or len(value) != 2
            or not all(isinstance(item, str) for item in value)
            or not 1 <= len(value[1]) <= 128
        ):
            raise ValueError
        timestamp = datetime.fromisoformat(value[0])
        if timestamp.tzinfo is None:
            raise ValueError
        return timestamp, value[1]
    except (ValueError, TypeError, binascii.Error, UnicodeError):
        raise ValueError("Invalid case history cursor") from None
