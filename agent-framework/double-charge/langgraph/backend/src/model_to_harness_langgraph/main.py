import uvicorn

from .config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "model_to_harness_langgraph.api.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=True,
        access_log=False,
    )


if __name__ == "__main__":
    main()
