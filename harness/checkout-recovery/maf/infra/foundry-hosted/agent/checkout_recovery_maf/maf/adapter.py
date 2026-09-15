from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Protocol


class FoundryClientFactory(Protocol):
    def create(self, *, project_endpoint: str, model_deployment: str) -> Any: ...


class DefaultFoundryClientFactory:
    def create(self, *, project_endpoint: str, model_deployment: str) -> Any:
        try:
            foundry_module = import_module("agent_framework.foundry")
            identity_module = import_module("azure.identity")
        except ImportError as error:
            raise RuntimeError(
                "Microsoft Agent Framework Foundry dependencies are not installed."
            ) from error
        return foundry_module.FoundryChatClient(
            project_endpoint=project_endpoint,
            model=model_deployment,
            credential=identity_module.DefaultAzureCredential(),
        )


@dataclass(frozen=True)
class HarnessAgentSettings:
    project_endpoint: str | None = None
    model_deployment: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.project_endpoint and self.model_deployment)


def create_harness_agent_if_configured(
    settings: HarnessAgentSettings,
    *,
    client_factory: FoundryClientFactory | None = None,
    importer: Callable[[str], Any] = import_module,
) -> Any | None:
    """Create a current MAF Harness Agent only for explicitly configured deployments."""
    if not settings.configured:
        return None
    try:
        agent_framework = importer("agent_framework")
    except ImportError as error:
        raise RuntimeError(
            "The agent-framework package is required for a configured harness."
        ) from error
    factory = client_factory or DefaultFoundryClientFactory()
    client = factory.create(
        project_endpoint=settings.project_endpoint or "",
        model_deployment=settings.model_deployment or "",
    )
    try:
        create_harness_agent = agent_framework.create_harness_agent
    except AttributeError as error:
        raise RuntimeError(
            "Installed agent-framework does not expose create_harness_agent; upgrade the package."
        ) from error
    return create_harness_agent(
        client=client,
        tools=(),
        disable_file_memory=True,
        disable_web_search=True,
    )
