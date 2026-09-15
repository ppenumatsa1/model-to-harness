# Model to Harness

An educational repository that follows one customer-support problem—a duplicate
card charge—from model reasoning to durable, verified work.

[Part 1: From Models to Harnesses](docs/articles/model-to-harness.md) is complete.
The Part 2 implementation now demonstrates the same deterministic workflow twice,
once with Microsoft Agent Framework (MAF) and once with LangGraph.

## Learning path

1. Start with the [product requirements](docs/design/prd.md).
2. Read the [business rules](docs/design/business-rules.md) and
   [approval conditions](docs/design/hitl-approval-conditions.md).
3. Follow the [user flow](docs/design/userflow.md) and
   [architecture](docs/design/architecture.md).
4. Review the [technology choices](docs/design/techstack.md) and
   [project structure](docs/design/projectstructure.md).
5. Explore the framework-neutral contracts in [`shared/`](shared/) and the
   independent [MAF](agent-framework/double-charge/maf/) and
   [LangGraph](agent-framework/double-charge/langgraph/) applications.
6. Read [Part 3: Agent Harnesses](docs/articles/03-agent-harnesses.md), then
   explore the [checkout-recovery MAF harness](harness/checkout-recovery/maf/).

## Repository boundaries

```text
shared/                         deterministic domain contracts and simulators
agent-framework/.../maf/        independent MAF application
agent-framework/.../langgraph/  independent LangGraph application
harness/checkout-recovery/maf/   independent MAF harness application
compose.yaml                    one local PostgreSQL developer dependency
```

`shared/` contains no web API, database, cloud, telemetry, model, framework, or
runtime code. Each application owns its API, UI, persistence, migrations, model
client, event projection, deployment assets, and tests. PostgreSQL is the durable
application source of truth; the root Compose file is only a local convenience.

## Prerequisites

- Python 3.12 for the framework lanes; Python 3.13 for the checkout harness
- Docker with Compose (only when running the framework applications)
- Node.js tooling required by each framework-owned frontend
- A Microsoft Foundry model configuration for model-backed local runs

The shared tests require no cloud service or database:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e "shared[test]"
python -m pytest shared/tests
```

## Local PostgreSQL

```bash
cp .env.example .env
docker compose up -d postgres
```

This starts one database only. The applications independently create and migrate
`maf_double_charge`, `langgraph_app`, and `langgraph_checkpoints` schema namespaces.
Start, migrate, test, and run each application from its own directory; neither
application is launched by the root Compose file.

## Documentation

- [Product requirements](docs/design/prd.md)
- [Architecture](docs/design/architecture.md)
- [Business rules](docs/design/business-rules.md)
- [HITL approval conditions](docs/design/hitl-approval-conditions.md)
- [User flow](docs/design/userflow.md)
- [Technology stack](docs/design/techstack.md)
- [Project structure](docs/design/projectstructure.md)
- [Issues, changes, and fixes](docs/design/issues-changes-fixes.md)
- [Part 2: Agent Frameworks](docs/articles/02-agent-frameworks.md)
- [Part 3: Agent Harnesses](docs/articles/03-agent-harnesses.md)

## Contributor skills

`.github/skills/` contains a small, pinned set of third-party Microsoft and LangChain
skills for current SDK and platform guidance. No repository-owned custom skills are
included yet. These contributor skills are not application runtime dependencies;
the checkout harness has a separately owned runtime triage procedure. See
[the skills provenance file](.github/skills/README.md).

## Status

The checkout-recovery MAF harness is independently deployed in `northcentralus`
under `rg-crmaf-20260912`, with Hosted Agent version 2, a private API, and an
authenticated UI. Its [lane-local delivery ledger](harness/checkout-recovery/maf/docs/issues-changes-fixes.md)
records the actual API, browser, hosted, evaluation, and telemetry results.

Both independent teaching lanes are deployed in `northcentralus` under
`rg-model-harness` with separate Foundry projects, Hosted Agents, PostgreSQL servers,
Container Apps, registries, identities, and telemetry resources.

| Lane | Public application | Hosted Agent | Hosted evaluation |
|---|---|---|---|
| MAF | [Open UI](https://mth-maf-wh2su65huqw5o-web.livelyhill-0f2b68f2.northcentralus.azurecontainerapps.io) | `model-harness-maf` v3 | 2 passed, 0 failed, 0 errored |
| LangGraph | [Open UI](https://mth-lg-2vq7rokaqwhae-web.mangodune-3886db41.northcentralus.azurecontainerapps.io) | `model-harness-langgraph` v13 | 2 passed, 0 failed, 0 errored |

Both use the `gpt-5.6-sol` `2026-07-09` Global Standard deployment. Remote
start/approval/resume tests verified durable human approval and exactly one refund
after an uncertain response. This remains an educational deployment: the
deterministic simulators are not payment systems, public networking is intentionally
simple, and the environment is not presented as production-ready.

Each Foundry project is connected through IaC to its lane-owned Application Insights
resource. Hosted Responses requests carry conversation correlation into workflow,
node, model, and safe tool spans. LangGraph reconstructs resumed node timing from its
durable PostgreSQL audit events because workflow state remains authoritative and an
approval resume is a separate request/trace boundary.
