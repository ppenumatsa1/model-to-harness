# Product requirements

## Product

`model-to-harness` is an educational comparison repository. It demonstrates how two
agent frameworks carry the same double-charge support case from complaint to a
verified outcome while keeping business controls deterministic.

## Audience

- Developers learning agent workflow primitives.
- Architects comparing MAF and LangGraph durability and HITL patterns.
- Reviewers who need a concrete example of safe, inspectable side effects.

## Goals

1. Teach nodes, edges, routing, parallel branches, retries, checkpoints, approval,
   resume, events, idempotency, verification, state, memory, and model context.
2. Implement equivalent behavior independently in MAF and LangGraph.
3. Provide a modern UI that makes durable execution evidence inspectable.
4. Keep cloud/model concerns replaceable in tests.
5. Produce a normalized outcome for fixture-based comparison.

## Functional requirements

- Accept a complaint, customer identifier, and scenario fixture.
- Normalize complaint text through a framework-owned model boundary.
- Load deterministic charges and detect duplicates by documented rules.
- Run billing and policy validation as parallel workflow branches.
- Persist and pause before a consequential refund.
- Record approve/deny separately from resume.
- Submit refunds with a stable idempotency key and verify one matching refund.
- Emit ordered durable events and expose safe polling/streaming projections.
- Show workflow state, selected memory, audit history, approval, and final outcome.
- Support fixtures for happy path, no duplicate, denial, transient failure,
  uncertain refund response, resumed approval, and verification mismatch.

## Quality and safety requirements

- The shared package remains free of API, database, cloud, telemetry, framework, and
  runtime dependencies.
- Each app owns its API, frontend, persistence, migrations, model adapter,
  observability, tests, and future-hosting placeholders.
- Tests use fake model boundaries and do not require cloud access.
- Billing and approval operations are deterministic and conflict-aware.
- A workflow cannot report a successful refund until verification observes exactly
  one matching record.
- UI projections exclude credentials, raw prompts, hidden reasoning, checkpoint
  internals, and unrestricted tool data.

## Non-goals

- Processing real payments or customer data.
- Providing production deployment infrastructure or service-level claims.
- Creating a shared workflow/API/frontend platform for both frameworks.
- Treating AG-UI or CopilotKit as the command bus.
- Building a multi-agent organization for a workflow that does not require one.

## Acceptance criteria

- All seven shared fixtures have normalized expected outcomes.
- Equivalent fixtures follow equivalent business routes in both applications.
- Approval denial performs no refund.
- Retrying an uncertain refund response yields one stored refund.
- Verification mismatch ends in manual review.
- Durable history makes retries, checkpoint, decision, resume, and terminal routing
  inspectable.
- Repository documentation links resolve locally.
