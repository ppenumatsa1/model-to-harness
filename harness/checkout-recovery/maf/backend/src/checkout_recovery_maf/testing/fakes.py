from typing import Any


class FakeFoundryClientFactory:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.client = object()

    def create(self, *, project_endpoint: str, model_deployment: str) -> Any:
        self.calls.append((project_endpoint, model_deployment))
        return self.client


class FakeAgentFramework:
    def __init__(self) -> None:
        self.client: Any | None = None
        self.options: dict[str, Any] = {}

    def create_harness_agent(self, *, client: Any, **kwargs: Any) -> dict[str, str]:
        self.client = client
        self.options = kwargs
        return {"kind": "harness-agent"}
