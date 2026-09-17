from typing import Annotated

from fastapi import Depends, Request

from checkout_recovery_maf.application import CheckoutRecoveryService


def get_service(request: Request) -> CheckoutRecoveryService:
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise RuntimeError("application service dependency was not initialized")
    return runtime.service


ServiceDependency = Annotated[CheckoutRecoveryService, Depends(get_service)]
