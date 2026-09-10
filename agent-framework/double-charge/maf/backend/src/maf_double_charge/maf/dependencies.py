from dataclasses import dataclass

from ..application.ports import Actions, ModelClient, Repository
from ..application.refunds import DurableRefundService


@dataclass(frozen=True)
class WorkflowDependencies:
    repository: Repository
    model: ModelClient
    actions: Actions
    refunds: DurableRefundService
    max_tool_attempts: int
