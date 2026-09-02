import importlib
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class ToolResult:
    ok: bool
    value: dict[str, Any] = field(default_factory=dict)
    code: str | None = None
    transient: bool = False
    uncertain: bool = False
    safe_summary: str = ""


class DomainGateway(Protocol):
    async def load_account(
        self, run_id: str, customer_id: str, scenario_id: str
    ) -> ToolResult: ...

    async def detect_duplicate(
        self,
        run_id: str,
        customer_id: str,
        charges: list[dict[str, Any]],
        scenario_id: str,
    ) -> ToolResult: ...

    async def validate_billing(
        self,
        run_id: str,
        customer_id: str,
        charges: list[dict[str, Any]],
        scenario_id: str,
    ) -> ToolResult: ...

    async def validate_policy(
        self,
        run_id: str,
        customer_id: str,
        charges: list[dict[str, Any]],
        scenario_id: str,
    ) -> ToolResult: ...

    async def submit_refund(
        self,
        run_id: str,
        customer_id: str,
        duplicate_evidence: dict[str, Any],
        idempotency_key: str,
        scenario_id: str,
    ) -> ToolResult: ...

    async def verify_refund(
        self,
        run_id: str,
        customer_id: str,
        idempotency_key: str,
        scenario_id: str,
        durable_refund_id: str | None,
    ) -> ToolResult: ...

    async def send_notification(
        self,
        run_id: str,
        customer_id: str,
        message: str,
        scenario_id: str,
    ) -> ToolResult: ...


@dataclass(slots=True)
class _ScenarioContext:
    fixture: Any
    billing: Any
    policy: Any
    evidence: Any | None = None


class SharedDomainGateway:
    """Narrow adapter over root-owned deterministic fixtures and simulators."""

    def __init__(self) -> None:
        shared = importlib.import_module("model_to_harness_shared")
        self._get_fixture = shared.get_fixture
        self._billing_type = shared.BillingSimulator
        self._policy_type = shared.RefundPolicySimulator
        simulators = importlib.import_module("model_to_harness_shared.simulators.billing")
        self._read_error = simulators.BillingReadError
        self._uncertain_error = simulators.UncertainRefundResponseError
        self._idempotency_error = simulators.IdempotencyConflictError
        self._contexts: dict[tuple[str, str], _ScenarioContext] = {}

    @staticmethod
    def _fixture_id(scenario_id: str) -> str:
        return scenario_id.replace("_", "-")

    def _context(self, run_id: str, scenario_id: str) -> _ScenarioContext:
        key = (run_id, self._fixture_id(scenario_id))
        if key not in self._contexts:
            fixture = self._get_fixture(key[1])
            behavior = fixture.billing_behavior
            billing = self._billing_type(
                fixture.charges,
                transient_read_failures=behavior.transient_read_failures,
                uncertain_refund_response_once=behavior.uncertain_refund_response_once,
                verification_count_override=behavior.verification_count_override,
            )
            self._contexts[key] = _ScenarioContext(
                fixture=fixture,
                billing=billing,
                policy=self._policy_type(),
            )
        return self._contexts[key]

    async def load_account(
        self, run_id: str, customer_id: str, scenario_id: str
    ) -> ToolResult:
        del customer_id
        context = self._context(run_id, scenario_id)
        try:
            charges = context.billing.load_charges(context.fixture.scenario_input.account_id)
        except self._read_error:
            return ToolResult(
                ok=False,
                code="TRANSIENT_BILLING_READ",
                transient=True,
                safe_summary="The deterministic billing read was temporarily unavailable",
            )
        return ToolResult(
            ok=True,
            value={
                "charges": [charge.model_dump(mode="json") for charge in charges],
            },
            safe_summary=f"Loaded {len(charges)} deterministic charge record(s)",
        )

    async def detect_duplicate(
        self,
        run_id: str,
        customer_id: str,
        charges: list[dict[str, Any]],
        scenario_id: str,
    ) -> ToolResult:
        del customer_id, charges
        context = self._context(run_id, scenario_id)
        evidence = context.billing.detect_duplicate(
            context.fixture.scenario_input.account_id
        )
        context.evidence = evidence
        return ToolResult(
            ok=True,
            value={
                "decision": str(evidence.decision),
                "evidence": evidence.model_dump(mode="json"),
            },
            safe_summary=evidence.rationale,
        )

    async def validate_billing(
        self,
        run_id: str,
        customer_id: str,
        charges: list[dict[str, Any]],
        scenario_id: str,
    ) -> ToolResult:
        del customer_id, charges
        context = self._context(run_id, scenario_id)
        validation = context.billing.validate_duplicate(context.evidence)
        return ToolResult(
            ok=validation.valid,
            value=validation.model_dump(mode="json"),
            code=None if validation.valid else "BILLING_VALIDATION_FAILED",
            safe_summary=validation.reason,
        )

    async def validate_policy(
        self,
        run_id: str,
        customer_id: str,
        charges: list[dict[str, Any]],
        scenario_id: str,
    ) -> ToolResult:
        del customer_id, charges
        context = self._context(run_id, scenario_id)
        assessment = context.policy.assess(context.evidence, context.fixture.charges)
        eligible = str(assessment.decision) == "eligible"
        return ToolResult(
            ok=eligible,
            value=assessment.model_dump(mode="json"),
            code=None if eligible else "POLICY_INELIGIBLE",
            safe_summary=assessment.reason,
        )

    async def submit_refund(
        self,
        run_id: str,
        customer_id: str,
        duplicate_evidence: dict[str, Any],
        idempotency_key: str,
        scenario_id: str,
    ) -> ToolResult:
        del customer_id
        context = self._context(run_id, scenario_id)
        charge_ids = duplicate_evidence.get("matching_charge_ids", [])
        try:
            refund = context.billing.submit_refund(
                account_id=context.fixture.scenario_input.account_id,
                charge_id=charge_ids[-1],
                idempotency_key=idempotency_key,
            )
        except self._uncertain_error:
            verification = context.billing.verify_refund(idempotency_key)
            return ToolResult(
                ok=False,
                uncertain=True,
                value={"refund_id": verification.refund_id},
                safe_summary=(
                    "The refund was stored but the deterministic response was uncertain"
                ),
            )
        except self._idempotency_error:
            return ToolResult(
                ok=False,
                code="REFUND_IDEMPOTENCY_CONFLICT",
                safe_summary="The idempotency key is bound to a different refund",
            )
        return ToolResult(
            ok=True,
            value={"refund_id": refund.refund_id},
            safe_summary="The idempotent refund record was returned",
        )

    async def verify_refund(
        self,
        run_id: str,
        customer_id: str,
        idempotency_key: str,
        scenario_id: str,
        durable_refund_id: str | None,
    ) -> ToolResult:
        del customer_id
        context = self._context(run_id, scenario_id)
        override = context.fixture.billing_behavior.verification_count_override
        count = override if override is not None else (1 if durable_refund_id else 0)
        verified = count == 1 and durable_refund_id is not None
        return ToolResult(
            ok=verified,
            value={
                "matching_refunds": count,
                "refund_id": durable_refund_id if verified else None,
            },
            code=None if verified else "VERIFY_MISMATCH",
            safe_summary=(
                "Exactly one matching durable refund exists."
                if verified
                else f"Expected one matching durable refund; found {count}."
            ),
        )

    async def send_notification(
        self,
        run_id: str,
        customer_id: str,
        message: str,
        scenario_id: str,
    ) -> ToolResult:
        del run_id, customer_id, message, scenario_id
        return ToolResult(
            ok=True,
            safe_summary="The deterministic teaching notification was recorded as sent",
        )


def shared_package_available() -> bool:
    try:
        importlib.import_module("model_to_harness_shared")
        return True
    except ImportError:
        return False
