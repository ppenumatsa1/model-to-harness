from __future__ import annotations

import json
from time import perf_counter

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from azure.identity.aio import DefaultAzureCredential

from ..application.ports import ModelResult
from ..config import Settings
from .agents import create_agents


class FoundryModelClient:
    """Owns the pinned MAF Foundry client's transports and async credential."""

    def __init__(self, settings: Settings) -> None:
        if not settings.foundry_configured:
            raise RuntimeError(
                "Real runs require FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_MODEL. "
                "Tests must inject FakeModelClient."
            )
        self._model = settings.foundry_model or ""
        self._credential = DefaultAzureCredential()
        self._client = FoundryChatClient(
            project_endpoint=settings.foundry_project_endpoint,
            model=self._model,
            credential=self._credential,
        )
        self._agents = create_agents(self._client)
        self._closed = False

    async def _run(self, agent: Agent, text: str) -> ModelResult:
        started = perf_counter()
        response = await agent.run(text)
        latency = round((perf_counter() - started) * 1000)
        return ModelResult(text=response.text.strip(), latency_ms=latency, model=self._model)

    async def normalize_complaint(self, complaint: str) -> ModelResult:
        return await self._run(self._agents.normalizer, complaint)

    async def draft_notification(self, facts: dict[str, object]) -> ModelResult:
        return await self._run(self._agents.writer, json.dumps(facts, sort_keys=True, default=str))

    async def explain_run(self, question: str, facts: dict[str, object]) -> ModelResult:
        prompt = json.dumps({"question": question, "run_facts": facts}, sort_keys=True, default=str)
        return await self._run(self._agents.explainer, prompt)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        # MAF 1.16 exposes these owned clients, but has no aggregate close method.
        try:
            await self._client.client.close()
        finally:
            try:
                await self._client.project_client.close()
            finally:
                await self._credential.close()
