from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from maf_double_charge.api.routers import streams
from maf_double_charge.application.models import DurableEvent, WorkflowState
from maf_double_charge.application.ports import WorkflowRunner
from maf_double_charge.application.service import DoubleChargeService
from maf_double_charge.infrastructure.persistence.postgres import PostgresRepository


def state(suffix="ordering"):
    return WorkflowState(
        run_id=f"run-{suffix}",
        case_id=f"case-{suffix}",
        complaint="Charged twice",
        customer_id="customer-100",
        scenario_id="duplicate-confirmed",
        idempotency_key=f"refund-{suffix}",
    )


def event(value, summary):
    return DurableEvent(
        case_id=value.case_id,
        run_id=value.run_id,
        event_type="node.completed",
        summary=summary,
    )


async def test_parallel_appends_cannot_expose_higher_sequence_before_lower_commit(
    postgres_repository: PostgresRepository, monkeypatch
):
    repository = postgres_repository
    first_run, other_run = state(), state("independent")
    await repository.create_run(first_run)
    await repository.create_run(other_run)
    first_event = event(first_run, "Delayed first commit")
    second_event = event(first_run, "Concurrent second append")
    inserted = asyncio.Event()
    release_commit = asyncio.Event()
    second_started = asyncio.Event()
    second_pid = None
    original_connection = repository.pool.connection

    class DelayedConnection:
        def __init__(self, connection):
            self.connection = connection
            self.delay_commit = False

        async def execute(self, query, params=None):
            nonlocal second_pid
            if (
                asyncio.current_task().get_name() == "second-event-append"
                and "pg_advisory_xact_lock" in query
            ):
                second_pid = self.connection.info.backend_pid
                second_started.set()
            result = await self.connection.execute(query, params)
            if "INSERT INTO execution_events" in query and params[0] == first_event.event_id:
                self.delay_commit = True
            return result

    @asynccontextmanager
    async def connection(*args, **kwargs):
        async with original_connection(*args, **kwargs) as conn:
            proxy = DelayedConnection(conn)
            yield proxy
            if proxy.delay_commit:
                inserted.set()
                await release_commit.wait()

    monkeypatch.setattr(repository.pool, "connection", connection)
    first = asyncio.create_task(repository.append_event(first_event))
    second = None
    try:
        await asyncio.wait_for(inserted.wait(), timeout=5)
        assert not first.done(), "append_event must not return before its transaction commits"
        second = asyncio.create_task(
            repository.append_event(second_event), name="second-event-append"
        )
        await asyncio.wait_for(second_started.wait(), timeout=5)

        async def wait_until_second_is_locked():
            while True:
                async with original_connection() as conn:
                    result = await conn.execute(
                        "SELECT wait_event FROM pg_stat_activity WHERE pid = %s", (second_pid,)
                    )
                    row = await result.fetchone()
                if row and row["wait_event"] == "advisory":
                    return
                if second.done():
                    pytest.fail(
                        "Second append committed while the earlier sequence was uncommitted"
                    )
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_until_second_is_locked(), timeout=5)
        assert await repository.list_events(first_run.run_id, limit=200) == []
        assert not second.done()
        unrelated = await asyncio.wait_for(
            repository.append_event(event(other_run, "Other run remains independent")), timeout=5
        )
        assert await repository.list_events(first_run.run_id, after=0, limit=200) == []
        release_commit.set()
        saved_first, saved_second = await asyncio.wait_for(asyncio.gather(first, second), timeout=5)
        assert saved_first.sequence < unrelated.sequence < saved_second.sequence
        assert await repository.list_events(first_run.run_id, limit=200) == [
            saved_first,
            saved_second,
        ]
        assert await repository.list_events(
            first_run.run_id, after=saved_first.sequence, limit=200
        ) == [saved_second]
    finally:
        release_commit.set()
        tasks = [task for task in (first, second) if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_live_stream_releases_postgres_connections_before_frames_and_idle(
    postgres_repository: PostgresRepository, model, monkeypatch
):
    repository = postgres_repository
    value = state("idle")
    await repository.create_run(value)
    await repository.append_event(event(value, "Committed event"))
    incoming = SimpleNamespace(headers={}, is_disconnected=AsyncMock(return_value=False))
    runner = AsyncMock(spec=WorkflowRunner)
    service = DoubleChargeService(repository, runner, model)
    active_connections = 0
    idle_calls = 0
    original_connection = repository.pool.connection

    @asynccontextmanager
    async def connection(*args, **kwargs):
        nonlocal active_connections
        async with original_connection(*args, **kwargs) as conn:
            active_connections += 1
            try:
                yield conn
            finally:
                active_connections -= 1

    async def idle(seconds):
        nonlocal idle_calls
        assert seconds == 1
        assert active_connections == 0
        stats = repository.pool.get_stats()
        assert stats["pool_available"] == stats["pool_size"]
        idle_calls += 1
        incoming.is_disconnected.return_value = True

    monkeypatch.setattr(repository.pool, "connection", connection)
    monkeypatch.setattr(
        streams, "asyncio", SimpleNamespace(sleep=idle, CancelledError=asyncio.CancelledError)
    )
    response = await streams.audit_stream(
        incoming, value.run_id, service, after=0, follow=True
    )
    chunks = []
    async for chunk in response.body_iterator:
        assert active_connections == 0
        chunks.append(chunk)
    assert chunks[0].startswith("event: audit\n")
    assert chunks[1].startswith("event: snapshot\n")
    assert idle_calls == 1
    runner.start.assert_not_awaited()
    runner.resume.assert_not_awaited()
