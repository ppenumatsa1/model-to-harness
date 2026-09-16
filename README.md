# Model to Harness

An educational repository that follows one customer-support problem—a duplicate
card charge—from model reasoning to durable, verified work.

[Part 1: From Models to Harnesses](docs/articles/model-to-harness.md) is complete.
The Part 2 implementation now demonstrates the same deterministic workflow twice,
once with Microsoft Agent Framework (MAF) and once with LangGraph.

## Learning path

1. Choose the independent [MAF](agent-framework/double-charge/maf/) or
   [LangGraph](agent-framework/double-charge/langgraph/) implementation.
2. Follow that lane's requirements, business rules, approval conditions, and user
   flow in its own design documents:
   [MAF design](agent-framework/double-charge/maf/docs/design/) or
   [LangGraph design](agent-framework/double-charge/langgraph/docs/design/).
3. Read its 4+1 architecture, technology choices, project structure, and
   implementation ledger. The [documentation index](docs/README.md) links each topic.
4. Explore the framework-neutral domain contracts and simulators in [`shared/`](shared/).
5. Read [Part 3: Agent Harnesses](docs/articles/03-agent-harnesses.md), then
   explore the [checkout-recovery MAF harness](harness/checkout-recovery/maf/).

## Repository boundaries

```text
shared/                         deterministic domain contracts and simulators
agent-framework/.../maf/        independent MAF application
agent-framework/.../langgraph/  independent LangGraph application
harness/checkout-recovery/maf/   independent MAF harness application
each application/compose.yaml   independent database-only local dependency
```

`shared/` contains no web API, database, cloud, telemetry, model, framework, or
runtime code. Each application owns its API, UI, persistence, migrations, model
client, event projection, deployment assets, and tests. PostgreSQL is the durable
application source of truth. Each project owns its own database-only Compose file,
network, and volume; there is no shared database or deployment abstraction.

## Prerequisites

- Python 3.12 for the framework lanes; Python 3.13 for the checkout harness
- Docker with Compose (for each application's optional local PostgreSQL)
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

Choose a project and follow its **Local PostgreSQL** instructions:

| Project | Compose project | Loopback PostgreSQL port |
| --- | --- | --- |
| [Double-charge MAF](agent-framework/double-charge/maf/README.md#local-postgresql) | `double-charge-maf` | `15432` |
| [Double-charge LangGraph](agent-framework/double-charge/langgraph/README.md#local-postgresql) | `double-charge-lg` | `25432` |
| [Checkout-recovery MAF](harness/checkout-recovery/maf/README.md#local-postgresql) | `checkout-recovery-maf` | `35432` |

All three databases can run concurrently. Compose starts **only PostgreSQL**, not
APIs, UIs, models, telemetry, or cloud resources. Each project uses a private,
ignored `.env.compose`; existing application `.env` files (including Azure
connections) are never replaced. A lane-owned command wrapper explicitly selects
the local database through process environment, without printing credentials or
shell-sourcing dotenv. Stop one project's database without affecting the others.
The root Docker build context excludes every project's private dotenv files,
Foundry caches, and local test logs; framework-neutral `shared/` remains available
to independently owned application builds.

The former root `compose.yaml` and `.env.example` are retired. Existing
`model-to-harness` containers, volumes, and data are **not** migrated or deleted.
Keep them until their owner explicitly retires them; do not use `down -v` or
volume pruning. The new independent volumes start empty and require each
application's explicit migrations. Root `shared/` remains unchanged.

## Documentation

- [MAF design documents](agent-framework/double-charge/maf/docs/design/)
- [LangGraph design documents](agent-framework/double-charge/langgraph/docs/design/)
- [Design-topic navigation](docs/README.md#implementation-design)
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

The framework lanes record their own implementation and release evidence:
[MAF ledger](agent-framework/double-charge/maf/docs/design/issues-changes-fixes.md)
and [LangGraph ledger](agent-framework/double-charge/langgraph/docs/design/issues-changes-fixes.md).
Those records distinguish dated Azure acceptance from newer local changes.
Local source, configuration, and simulations do not establish deployed version,
endpoint health, or telemetry completeness. Payments and notifications remain
simulated; neither lane is presented as a production payment system.
