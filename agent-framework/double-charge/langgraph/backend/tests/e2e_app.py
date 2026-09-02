from langgraph.checkpoint.memory import InMemorySaver
from model_to_harness_langgraph.app import create_app
from model_to_harness_langgraph.audit import InMemoryAuditRepository
from model_to_harness_langgraph.config import Settings
from model_to_harness_langgraph.domain_gateway import SharedDomainGateway


class E2EFakeModel:
    async def normalize(self, complaint: str) -> str:
        return "Customer reports two charges for one purchase."

    async def draft_notification(self, facts: dict[str, str]) -> str:
        return f"Case {facts['case_id']}: the verified refund is ready."


app = create_app(
    settings=Settings(database_url="unused"),
    audit=InMemoryAuditRepository(),
    gateway=SharedDomainGateway(),
    model=E2EFakeModel(),
    checkpointer=InMemorySaver(),
)

