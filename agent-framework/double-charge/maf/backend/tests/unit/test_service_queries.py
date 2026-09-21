from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from maf_double_charge.application.history import CaseCursor, CasePage
from maf_double_charge.application.models import (
    ApprovalResponse,
    BranchResult,
    DurableEvent,
    RunStatus,
    WorkflowState,
)
from maf_double_charge.application.service import DoubleChargeService
from maf_double_charge.projections.workspace import workspace_view
from maf_double_charge.testing.model import FakeModelClient
from maf_double_charge.testing.repository import InMemoryRepository
from model_to_harness_shared import WorkflowOutcome


def state(number: int) -> WorkflowState:
    return WorkflowState(
        case_id=f"case-{number}", run_id=f"run-{number}", complaint="PRIVATE complaint",
        customer_id="customer-100", scenario_id="duplicate-confirmed",
        idempotency_key=f"PRIVATE-key-{number}",
    )


def test_workspace_projection_uses_only_loaded_values_without_mutation() -> None:
    item = state(1).model_copy(update={
        "status": RunStatus.PAUSED, "approval_required": True, "checkpoint_id": "checkpoint",
        "billing_validation": BranchResult(
            branch="billing_validation", ok=True, summary="Validated.",
            evidence={"checked_charge_ids": ["charge-1"], "raw": {"prompt": "PRIVATE"}},
        ),
    })
    approval = ApprovalResponse(decision="approve", reviewer_id="reviewer", reason="Reviewed.")
    memory = {
        "customer_id": "customer-100", "fixture_id": ["not a string"],
        "last_normalized_issue": "Two charges.", "credentials": "PRIVATE",
    }
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    original_state = item.model_copy(deep=True)
    original_approval = approval.model_copy(deep=True)
    original_memory = memory.copy()
    result = workspace_view(
        item, approval=approval, memory=memory, outcome=None, created_at=created_at
    )
    assert result.created_at == created_at
    assert result.memory == {
        "customer_id": "customer-100", "last_normalized_issue": "Two charges.",
    }
    assert result.state.billing_validation.evidence == {"checked_charge_ids": ["charge-1"]}
    assert result.approval.checkpoint_id == "checkpoint"
    assert result.can_resume and not result.can_record_approval
    assert result == workspace_view(
        item, approval=approval, memory=memory, outcome=None, created_at=created_at
    )
    assert item == original_state
    assert approval == original_approval
    assert memory == original_memory


async def test_service_loads_each_workspace_record_for_run_and_case(
    repository: InMemoryRepository, service: DoubleChargeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = state(1)
    await repository.create_run(item)
    await repository.save_memory(item.case_id, {"customer_id": item.customer_id})
    outcome = WorkflowOutcome(
        case_id=item.case_id, run_id=item.run_id, duplicate_decision="not_found",
        policy_decision="not_evaluated", approval_decision="not_required",
        refund_status="not_requested", notification_status="not_sent",
        terminal_status="completed_no_refund",
    )
    await repository.save_outcome(outcome)
    spies = {}
    for name in ("get_approval", "get_memory", "get_outcome", "get_run_created_at"):
        spies[name] = AsyncMock(wraps=getattr(repository, name))
        monkeypatch.setattr(repository, name, spies[name])
    by_run = await service.get_workspace(item.run_id)
    assert by_run.outcome == outcome
    assert by_run.memory == {"customer_id": item.customer_id}
    assert by_run.created_at == repository.created_at[item.run_id]
    for name, spy in spies.items():
        spy.assert_awaited_once_with(item.case_id if name == "get_memory" else item.run_id)
        spy.reset_mock()
    assert await service.get_case_workspace(item.case_id) == by_run
    for name, spy in spies.items():
        spy.assert_awaited_once_with(item.case_id if name == "get_memory" else item.run_id)


async def test_service_case_page_owns_keyset_and_lookahead(
    repository: InMemoryRepository, service: DoubleChargeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    for number in range(3):
        item = state(number)
        await repository.create_run(item)
        repository.created_at[item.run_id] = created_at
    reads = AsyncMock(wraps=repository.list_cases)
    monkeypatch.setattr(repository, "list_cases", reads)
    first = await service.list_cases(limit=2)
    assert isinstance(first, CasePage)
    assert [item.run_id for item in first.items] == ["run-2", "run-1"]
    assert first.has_more
    assert CaseCursor.decode(first.next_cursor) == CaseCursor(
        created_at=created_at, run_id="run-1"
    )
    reads.assert_awaited_once_with(3, None)
    second = await service.list_cases(limit=2, cursor=first.next_cursor)
    assert [item.run_id for item in second.items] == ["run-0"]
    assert not second.has_more and second.next_cursor is None
    reads.assert_awaited_with(3, (created_at, "run-1"))
    reads.reset_mock()
    with pytest.raises(ValueError, match="invalid case history cursor"):
        await service.list_cases(cursor="invalid")
    reads.assert_not_awaited()
    empty = await service.list_cases(
        cursor=CaseCursor(created_at=created_at, run_id="run-0").encode()
    )
    assert empty.items == [] and not empty.has_more and empty.next_cursor is None


async def test_service_event_query_checks_existence_and_keeps_global_sequence_gaps(
    repository: InMemoryRepository, service: DoubleChargeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    item, other = state(1), state(2)
    for value in (item, other):
        await repository.create_run(value)
    events = []
    for value in (item, other, item, other, item):
        events.append(await repository.append_event(DurableEvent(
            run_id=value.run_id, case_id=value.case_id,
            event_type="decision.summary", summary="A safe fact.",
        )))
    reads = AsyncMock(wraps=repository.list_events)
    monkeypatch.setattr(repository, "list_events", reads)
    assert await service.list_events(item.run_id, after=1, limit=1) == [events[2]]
    reads.assert_awaited_once_with(item.run_id, after=1, limit=1)
    assert await service.list_events(item.run_id) == events[::2]
    reads.reset_mock()
    with pytest.raises(KeyError, match="unknown run"):
        await service.list_events("missing")
    reads.assert_not_awaited()


async def test_selected_run_resolution_is_run_first_then_case(
    repository: InMemoryRepository, service: DoubleChargeService
) -> None:
    first = state(1)
    ambiguous = state(2).model_copy(update={"case_id": first.run_id})
    for item in (first, ambiguous):
        await repository.create_run(item)
    assert await service.resolve_selected_run(first.run_id) == first
    assert await service.resolve_selected_run(first.case_id) == first
    assert await service.resolve_selected_run(ambiguous.run_id) == ambiguous
    with pytest.raises(KeyError, match="unknown case"):
        await service.resolve_selected_run("missing")
    with pytest.raises(KeyError, match="unknown run"):
        await service.get_selected_run(first.case_id)
    with pytest.raises(KeyError, match="unknown run"):
        await service.get_workspace(first.case_id)
    with pytest.raises(KeyError, match="unknown case"):
        await service.get_case_workspace(ambiguous.run_id)
    assert await service.get_outcome("missing") is None


async def test_explanation_model_receives_only_selected_safe_facts(
    repository: InMemoryRepository, service: DoubleChargeService, model: FakeModelClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item, other = state(1), state(2)
    for value in (item, other):
        await repository.create_run(value)
    for number in range(10):
        await repository.append_event(DurableEvent(
            run_id=item.run_id, case_id=item.case_id, event_type="decision.summary",
            summary=f"Safe summary {number}.", payload={"prompt": "PRIVATE"},
        ))
    await repository.append_event(DurableEvent(
        run_id=other.run_id, case_id=other.case_id, event_type="decision.summary",
        summary="PRIVATE other case.",
    ))
    await repository.append_event(DurableEvent(
        run_id=item.run_id, case_id=item.case_id, event_type="model.completed",
        summary="PRIVATE model details.", payload={"prompt": "PRIVATE"},
    ))
    explain = AsyncMock(wraps=model.explain_run)
    monkeypatch.setattr(model, "explain_run", explain)
    result = await service.explain_selected_run(item, "Why?")
    explain.assert_awaited_once_with("Why?", {
        "status": item.status, "current_step": item.current_step,
        "terminal_status": None, "refund_status": "not_requested",
        "latest_summary": "Safe summary 9.",
        "event_summaries": [f"Safe summary {number}." for number in range(2, 10)],
    })
    selected = await service.get_selected_run(item.run_id)
    assert len(selected["events"]) == 10
    assert "PRIVATE" not in str(selected) + result.text
    assert await repository.get_approval(item.run_id) is None
