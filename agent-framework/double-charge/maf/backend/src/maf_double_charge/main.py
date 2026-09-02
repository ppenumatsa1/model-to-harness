from __future__ import annotations

import uvicorn

from .api import create_app
from .config import get_settings

app = create_app()


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        "maf_double_charge.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.app_env == "development",
    )


if __name__ == "__main__":
    run()
