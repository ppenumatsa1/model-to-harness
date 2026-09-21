from datetime import UTC, datetime

from maf_double_charge.application.models import WorkflowState
from maf_double_charge.infrastructure.persistence.postgres import PostgresRepository


async def test_history_uses_created_timestamp_and_tie_breaker(
    postgres_repository: PostgresRepository,
) -> None:
    repository = postgres_repository
    for number in range(25):
        await repository.create_run(WorkflowState(
            case_id=f"case-{number:03}", run_id=f"run-{number:03}",
            complaint="Two captured charges.", customer_id="customer",
            scenario_id="duplicate-confirmed", idempotency_key=f"private-{number}",
        ))
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    async with repository.pool.connection() as connection:
        await connection.execute("UPDATE runs SET created_at = %s", (timestamp,))
    first = await repository.list_cases(10)
    assert len(first) == 10 and first[0].run_id == "run-024"
    await repository.create_run(WorkflowState(
        case_id="new-case", run_id="new-run", complaint="A new complaint.",
        customer_id="customer", scenario_id="no-duplicate", idempotency_key="new-private",
    ))
    second = await repository.list_cases(10, (first[-1].created_at, first[-1].run_id))
    third = await repository.list_cases(10, (second[-1].created_at, second[-1].run_id))
    assert [row.run_id for row in first + second + third] == [
        f"run-{number:03}" for number in reversed(range(25))
    ]
    assert await repository.get_run_created_at("run-000") == timestamp
    selected = await repository.get_state_by_case("case-000")
    assert selected.run_id == "run-000"
    assert "private-" not in first[0].model_dump_json()
