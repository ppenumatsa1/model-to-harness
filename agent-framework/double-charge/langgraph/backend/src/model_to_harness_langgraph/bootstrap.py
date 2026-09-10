import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from .application.ports import AuditRepository
from .application.service import WorkflowService
from .config import Settings, get_settings
from .graph.runner import DoubleChargeWorkflow
from .infrastructure.domain_gateway import DomainGateway, SharedDomainGateway
from .infrastructure.logging import configure_logging
from .infrastructure.model_client import ComplaintModel, open_model
from .infrastructure.persistence.audit import PostgresAuditRepository
from .infrastructure.persistence.checkpointing import checkpoint_conninfo
from .infrastructure.persistence.migrations import setup_storage
from .infrastructure.telemetry import configure_telemetry


@dataclass
class Runtime:
    service: WorkflowService
    audit: AuditRepository
    checkpointer: Any
    settings: Settings
    verify_storage: bool

    async def verify(self) -> None:
        if self.verify_storage:
            await setup_storage(self.settings, verify_only=True)
        elif not await self.audit.ping():
            raise RuntimeError("Injected audit store is not ready")


@asynccontextmanager
async def open_runtime(
    settings: Settings | None = None,
    *,
    audit: AuditRepository | None = None,
    gateway: DomainGateway | None = None,
    model: ComplaintModel | None = None,
    checkpointer: Any | None = None,
    hosted: bool = False,
) -> AsyncIterator[Runtime]:
    settings = settings or get_settings()
    configure_logging(settings.log_level, hosted=hosted)
    async with AsyncExitStack() as stack:
        try:
            telemetry = configure_telemetry(hosted=hosted)
            stack.callback(telemetry.close)
            # Exporter handlers can be installed by the distro after console setup.
            configure_logging(settings.log_level, hosted=hosted)
            needs_storage = audit is None or checkpointer is None
            if needs_storage:
                await setup_storage(settings, verify_only=True)
            if audit is None:
                audit = PostgresAuditRepository(settings.database_url, settings.langgraph_schema)
                stack.push_async_callback(audit.close)
                await audit.open()
            if checkpointer is None:
                checkpointer = await stack.enter_async_context(
                    AsyncPostgresSaver.from_conn_string(
                        checkpoint_conninfo(
                            settings.database_url, settings.langgraph_checkpoint_schema
                        )
                    )
                )
            if model is None:
                model = await stack.enter_async_context(open_model(settings))
            workflow = DoubleChargeWorkflow(
                audit=audit,
                gateway=gateway if gateway is not None else SharedDomainGateway(),
                model=model,
                checkpointer=checkpointer,
            )
        except Exception as exc:
            logging.getLogger(__name__).error(
                "runtime_startup_failed", extra={"error_type": type(exc).__name__}
            )
            raise
        yield Runtime(
            WorkflowService(workflow, audit), audit, checkpointer, settings, needs_storage
        )
