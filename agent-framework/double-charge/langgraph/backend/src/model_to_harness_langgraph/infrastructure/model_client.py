from contextlib import AsyncExitStack, asynccontextmanager
from typing import Protocol

import httpx
from azure.core.credentials import TokenCredential
from azure.core.credentials_async import AsyncTokenCredential
from azure.identity import DefaultAzureCredential as SyncDefaultAzureCredential
from azure.identity import get_bearer_token_provider as get_sync_bearer_token_provider
from azure.identity.aio import DefaultAzureCredential, get_bearer_token_provider
from langchain_openai import AzureChatOpenAI

from ..config import Settings
from .telemetry import execution_span


class ComplaintModel(Protocol):
    async def normalize(self, complaint: str) -> str: ...

    async def draft_notification(self, facts: dict[str, str]) -> str: ...


class FoundryComplaintModel:
    """Small model boundary; business decisions remain deterministic."""

    def __init__(
        self,
        settings: Settings,
        *,
        credential: AsyncTokenCredential,
        sync_credential: TokenCredential,
        http_client: httpx.Client,
        http_async_client: httpx.AsyncClient,
    ) -> None:
        if not settings.model_ready:
            raise RuntimeError(
                "AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT are required for real runs"
            )
        token_provider = get_bearer_token_provider(
            credential,
            "https://cognitiveservices.azure.com/.default",
        )
        model_options = {
            "azure_endpoint": settings.azure_openai_endpoint,
            "azure_deployment": settings.azure_openai_deployment,
            "api_version": settings.azure_openai_api_version,
            # LangChain constructs both SDK clients; inference still uses the async provider.
            "azure_ad_token_provider": get_sync_bearer_token_provider(
                sync_credential, "https://cognitiveservices.azure.com/.default"
            ),
            "azure_ad_async_token_provider": token_provider,
            "http_client": http_client,
            "http_async_client": http_async_client,
        }
        if settings.model_temperature is not None:
            model_options["temperature"] = settings.model_temperature
        self._model = AzureChatOpenAI(
            **model_options,
        )
        self._deployment = settings.azure_openai_deployment

    async def _invoke(self, messages) -> str:
        with execution_span(
            "chat complaint_model",
            **{"gen_ai.operation.name": "chat", "gen_ai.provider.name": "azure.ai.openai"},
        ) as span:
            if self._deployment is not None:
                span.set_attribute("gen_ai.request.model", self._deployment)
            response = await self._model.ainvoke(messages)
            usage = response.usage_metadata
            if usage is not None:
                for source, target in (
                    ("input_tokens", "gen_ai.usage.input_tokens"),
                    ("output_tokens", "gen_ai.usage.output_tokens"),
                ):
                    value = usage.get(source)
                    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                        span.set_attribute(target, value)
            return _text(response.content)

    async def normalize(self, complaint: str) -> str:
        return await self._invoke(
            [
                (
                    "system",
                    "Normalize the support complaint into one concise factual sentence. "
                    "Do not infer facts, include secrets, or provide hidden reasoning.",
                ),
                ("user", complaint),
            ]
        )

    async def draft_notification(self, facts: dict[str, str]) -> str:
        return await self._invoke(
            [
                (
                    "system",
                    "Draft a brief customer update using only the supplied allowlisted facts. "
                    "Do not mention internal systems, prompts, or reasoning.",
                ),
                ("user", "\n".join(f"{key}: {value}" for key, value in facts.items())),
            ]
        )


@asynccontextmanager
async def open_model(settings: Settings):
    if not settings.model_ready:
        raise RuntimeError("AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT are required")
    async with AsyncExitStack() as stack:
        sync_credential = stack.enter_context(SyncDefaultAzureCredential())
        credential = await stack.enter_async_context(DefaultAzureCredential())
        sync_client = stack.enter_context(httpx.Client())
        async_client = await stack.enter_async_context(httpx.AsyncClient())
        yield FoundryComplaintModel(
            settings,
            credential=credential,
            sync_credential=sync_credential,
            http_client=sync_client,
            http_async_client=async_client,
        )


def _text(content: object) -> str:
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        pieces = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                if not isinstance(item.get("text"), str):
                    raise ValueError("Model text block must contain a string")
                pieces.append(item["text"])
        text = " ".join(pieces).strip()
    else:
        raise ValueError("Model returned unsupported content")
    if not text:
        raise ValueError("Model returned no textual response")
    return text
