"""API factory and settings-aware local launcher."""

from checkout_recovery_maf.api.app import create_app
from checkout_recovery_maf.config import Settings

__all__ = ["create_app", "main"]


def main(settings: Settings | None = None) -> None:
    import uvicorn

    selected = settings if settings is not None else Settings()
    selected.validate_runtime()
    uvicorn.run(create_app(settings=selected), host=selected.api_host, port=selected.api_port)
