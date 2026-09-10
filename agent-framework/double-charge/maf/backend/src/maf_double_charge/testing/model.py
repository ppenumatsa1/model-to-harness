from ..application.ports import ModelResult


class FakeModelClient:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.closed = False

    async def normalize_complaint(self, complaint: str) -> ModelResult:
        self.calls.append("normalize")
        text = " ".join(complaint.strip().split())
        return ModelResult(text=text, latency_ms=1, model="fake-model")

    async def draft_notification(self, facts: dict[str, object]) -> ModelResult:
        self.calls.append("notification")
        status = facts.get("refund_status", "not_requested")
        refund_id = facts.get("refund_id")
        suffix = f" Reference: {refund_id}." if refund_id else ""
        return ModelResult(
            text=f"Your double-charge case is complete. Refund status: {status}.{suffix}",
            latency_ms=1,
            model="fake-model",
        )

    async def explain_run(self, question: str, facts: dict[str, object]) -> ModelResult:
        self.calls.append("explain")
        return ModelResult(
            text=(
                f"Current status is {facts.get('status', 'unknown')}; "
                f"the latest safe event is {facts.get('latest_summary', 'not available')}."
            ),
            latency_ms=1,
            model="fake-model",
        )

    async def close(self) -> None:
        self.closed = True
