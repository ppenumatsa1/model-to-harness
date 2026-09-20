from typing import Annotated

from fastapi import Depends, Request

from checkout_recovery_copilot.application import CheckoutRecoveryService
from checkout_recovery_copilot.application.ports import RuntimeHealth
from checkout_recovery_copilot.bootstrap import Runtime


def get_runtime(request: Request) -> Runtime:
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise RuntimeError("application service dependency was not initialized")
    return runtime


def get_service(request: Request) -> CheckoutRecoveryService:
    return get_runtime(request).service


def get_runtime_health(request: Request) -> RuntimeHealth:
    return get_runtime(request)


ServiceDependency = Annotated[CheckoutRecoveryService, Depends(get_service)]
RuntimeHealthDependency = Annotated[RuntimeHealth, Depends(get_runtime_health)]
