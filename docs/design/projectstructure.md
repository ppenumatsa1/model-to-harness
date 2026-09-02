# Project structure

The repository is deliberately split by ownership rather than by reusable
application layers.

```text
model-to-harness/
├── README.md, LICENSE, .env.example, compose.yaml
├── docs/
│   ├── articles/                  series articles and Part 2 outline
│   ├── design/                    canonical implementation documentation
│   └── diagrams/                  focused Mermaid views
├── shared/
│   ├── src/model_to_harness_shared/
│   │   ├── domain/                Pydantic records and enums
│   │   ├── simulators/            billing, policy, and approval behavior
│   │   ├── fixtures/              deterministic scenarios
│   │   └── evaluation_contracts/  normalized expectations
│   └── tests/
├── agent-framework/double-charge/
│   ├── maf/
│   │   ├── backend/src/maf_double_charge/
│   │   ├── backend/migrations/ and backend/tests/
│   │   ├── frontend/
│   │   └── scripts/, evals/, observability/, infra/, .foundry/
│   └── langgraph/
│       ├── backend/src/model_to_harness_langgraph/
│       ├── backend/migrations/ and backend/tests/
│       ├── frontend/
│       └── scripts/, evals/, observability/, infra/, .foundry/
└── harness/                        next article-stage placeholder
```

Related documents: [architecture](architecture.md),
[technology stack](techstack.md), and [implementation ledger](issues-changes-fixes.md).

## Canonical design documents

- `prd.md`: problem, goals, requirements, and acceptance criteria.
- `architecture.md`: boundaries, flow, persistence, events, and comparison contract.
- `business-rules.md`: authoritative deterministic business behavior.
- `hitl-approval-conditions.md`: approval and resume invariants.
- `userflow.md`: support-user and reviewer journey.
- `techstack.md`: implemented technologies and exclusions.
- `projectstructure.md`: repository ownership map.
- `issues-changes-fixes.md`: concise implementation and validation ledger.

## Independence rule

Code that is specific to MAF or LangGraph stays in that application's folder. Shared
code is limited to framework-neutral business contracts, simulators, fixtures, and
evaluation expectations. The root Compose file starts PostgreSQL only; it does not
run applications or migrations.

Each lane's deployment source is also local to that lane:

- `azure.yaml`: Foundry Hosted Agent declaration.
- `infra/`: lane-owned Bicep, container images, nginx proxy, and hosted entrypoint.
- `scripts/deploy_azure.sh`: lane-owned provisioning and rollout automation.
- `scripts/smoke_azure.sh`: lane-owned public deployment smoke.
- `infra/foundry-hosted/agent/eval.yaml`: deployed-agent evaluation intent.
- `.foundry/`: metadata, datasets, suites, evaluators, and results only.

Generated hosted `_packages/` copies are deployment artifacts, not another source of
truth.
