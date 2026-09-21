from model_to_harness_shared.simulators.billing import (
    BillingReadError,
    UncertainRefundResponseError,
)


class RefundIdempotencyConflictError(ValueError):
    pass


class StartRequestConflictError(ValueError):
    """A Start identity cannot be reused for a different command."""


class StartRequestInProgressError(RuntimeError):
    def __init__(self, case_id: str, run_id: str) -> None:
        super().__init__("Start is already claimed; inspect the existing run before retrying.")
        self.case_id = case_id
        self.run_id = run_id


class StartExecutionError(RuntimeError):
    def __init__(self, case_id: str, run_id: str) -> None:
        super().__init__("Start was claimed but execution failed; inspect the existing run.")
        self.case_id = case_id
        self.run_id = run_id


class StorageReadinessError(RuntimeError):
    """Storage is unavailable or requires an explicit migration."""


class SchemaVersionError(StorageReadinessError):
    """The configured schema does not match this application build."""


__all__ = [
    "BillingReadError",
    "RefundIdempotencyConflictError",
    "SchemaVersionError",
    "StartExecutionError",
    "StartRequestConflictError",
    "StartRequestInProgressError",
    "StorageReadinessError",
    "UncertainRefundResponseError",
]
