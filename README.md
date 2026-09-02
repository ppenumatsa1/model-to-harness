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
6. Continue to the future harness layer described in [`harness/`](harness/).

## Repository boundaries

```text
shared/                         deterministic domain contracts and simulators
agent-framework/.../maf/        independent MAF application
agent-framework/.../langgraph/  independent LangGraph application
harness/                        next-stage teaching placeholder
compose.yaml                    one local PostgreSQL developer dependency
```

`shared/` contains no web API, database, cloud, telemetry, model, framework, or
runtime code. Each application owns its API, UI, persistence, migrations, model
client, event projection, deployment assets, and tests. PostgreSQL is the durable
application source of truth; the root Compose file is only a local convenience.

## Prerequisites

- Python 3.12
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
- [Part 2 outline](docs/articles/agent-framework-primitives.md)

## Contributor skills

`.github/skills/` contains a small, pinned set of third-party Microsoft and LangChain
skills for current SDK and platform guidance. No repository-owned custom skills are
included yet, and skills are never part of either application runtime. See
[the skills provenance file](.github/skills/README.md).

## Status

Both independent teaching lanes are deployed in `northcentralus` under
`rg-model-harness` with separate Foundry projects, Hosted Agents, PostgreSQL servers,
Container Apps, registries, identities, and telemetry resources.

| Lane | Public application | Hosted Agent | Hosted evaluation |
|---|---|---|---|
| MAF | [Open UI](https://mth-maf-wh2su65huqw5o-web.livelyhill-0f2b68f2.northcentralus.azurecontainerapps.io) | `model-harness-maf` v2 | 2 passed, 0 failed, 0 errored |
| LangGraph | [Open UI](https://mth-lg-2vq7rokaqwhae-web.mangodune-3886db41.northcentralus.azurecontainerapps.io) | `model-harness-langgraph` v5 | 2 passed, 0 failed, 0 errored |

Both use the `gpt-5.6-sol` `2026-07-09` Global Standard deployment. Remote
start/approval/resume tests verified durable human approval and exactly one refund
after an uncertain response. This remains an educational deployment: the
deterministic simulators are not payment systems, public networking is intentionally
simple, and the environment is not presented as production-ready.
