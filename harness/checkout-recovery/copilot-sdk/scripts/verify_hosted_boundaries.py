"""Run with the hosted service venv to exercise its real SDK import and safe error boundary."""

import asyncio
import importlib.util
import io
import logging
import sys
import traceback
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "infra/foundry-hosted/agent"
sys.path.insert(0, str(AGENT))


async def main() -> None:
    from checkout_recovery_copilot.application import CheckoutRecoveryService
    from checkout_recovery_copilot.infrastructure import InMemoryCaseRepository
    from psycopg import OperationalError

    spec = importlib.util.spec_from_file_location("checkout_hosted_boundary", AGENT / "main.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    service = CheckoutRecoveryService(InMemoryCaseRepository())
    logs = io.StringIO()
    logger = logging.getLogger(module.__name__)
    handler = logging.StreamHandler(logs)
    logger.addHandler(handler)
    service_patch = patch.object(module, "_checkout_service", AsyncMock(return_value=service))
    service_patch.start()
    try:
        with patch.object(module, "TextResponse", side_effect=lambda *args, text: text):
            response = await module.response_handler(
                {"input": '{"action":"start","fixture_id":"PRIVATE-CONTENT-CANARY"}'}
            )
            assert response == '{"error":"checkout command was rejected"}'
        with patch.object(
            service, "start_case", side_effect=OperationalError("PRIVATE-CONTENT-CANARY")
        ):
            try:
                await module.response_handler(
                    {"input": '{"action":"start","fixture_id":"recoverable-inventory-reservation"}'}
                )
            except RuntimeError as error:
                assert str(error) == "checkout persistence command failed"
                assert "PRIVATE-CONTENT-CANARY" not in traceback.format_exc()
            else:
                raise AssertionError("Persistence failure must not become success")
        assert "PRIVATE-CONTENT-CANARY" not in logs.getvalue()
        print("Hosted boundary: unknown command and persistence error redaction passed")
    finally:
        service_patch.stop()
        logger.removeHandler(handler)


if __name__ == "__main__":
    asyncio.run(main())
