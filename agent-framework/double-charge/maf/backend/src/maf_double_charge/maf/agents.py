from dataclasses import dataclass

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient

from .prompts import DRAFT_NOTIFICATION, EXPLAIN_RUN, NORMALIZE_COMPLAINT


@dataclass(frozen=True)
class WorkflowAgents:
    normalizer: Agent
    writer: Agent
    explainer: Agent


def create_agents(client: FoundryChatClient) -> WorkflowAgents:
    return WorkflowAgents(
        normalizer=Agent(
            client=client, name="ComplaintNormalizer", instructions=NORMALIZE_COMPLAINT
        ),
        writer=Agent(
            client=client, name="CustomerNotificationWriter", instructions=DRAFT_NOTIFICATION
        ),
        explainer=Agent(client=client, name="RunExplainer", instructions=EXPLAIN_RUN),
    )
