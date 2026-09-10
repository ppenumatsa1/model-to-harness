from model_to_harness_shared.simulators.billing import (
    BillingReadError,
    UncertainRefundResponseError,
)


class RefundIdempotencyConflictError(ValueError):
    pass


class StorageReadinessError(RuntimeError):
    """Storage is unavailable or requires an explicit migration."""


class SchemaVersionError(StorageReadinessError):
    """The configured schema does not match this application build."""


__all__ = [
    "BillingReadError",
    "RefundIdempotencyConflictError",
    "SchemaVersionError",
    "StorageReadinessError",
    "UncertainRefundResponseError",
]
