from typing import Protocol

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from langchain_openai import AzureChatOpenAI

from .config import Settings


class ComplaintModel(Protocol):
    async def normalize(self, complaint: str) -> str: ...

    async def draft_notification(self, facts: dict[str, str]) -> str: ...


class FoundryComplaintModel:
    """Small model boundary; business decisions remain deterministic."""

    def __init__(self, settings: Settings) -> None:
        if not settings.model_ready:
            raise RuntimeError(
                "AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT are required for real runs"
            )
        credential = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(
            credential,
            "https://cognitiveservices.azure.com/.default",
        )
        model_options = {
            "azure_endpoint": settings.azure_openai_endpoint,
            "azure_deployment": settings.azure_openai_deployment,
            "api_version": settings.azure_openai_api_version,
            "azure_ad_token_provider": token_provider,
        }
        if settings.model_temperature is not None:
            model_options["temperature"] = settings.model_temperature
        self._model = AzureChatOpenAI(
            **model_options,
        )

    async def normalize(self, complaint: str) -> str:
        response = await self._model.ainvoke(
            [
                (
                    "system",
                    "Normalize the support complaint into one concise factual sentence. "
                    "Do not infer facts, include secrets, or provide hidden reasoning.",
                ),
                ("user", complaint),
            ]
        )
        return _text(response.content)

    async def draft_notification(self, facts: dict[str, str]) -> str:
        response = await self._model.ainvoke(
            [
                (
                    "system",
                    "Draft a brief customer update using only the supplied allowlisted facts. "
                    "Do not mention internal systems, prompts, or reasoning.",
                ),
                ("user", "\n".join(f"{key}: {value}" for key, value in facts.items())),
            ]
        )
        return _text(response.content)


def _text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        pieces = [
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        return " ".join(pieces).strip()
    return str(content).strip()
