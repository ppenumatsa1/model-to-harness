"""API entrypoint: uvicorn checkout_recovery_maf.main:create_app --factory."""

from checkout_recovery_maf.api.app import create_app

__all__ = ["create_app"]
