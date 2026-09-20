# Checkout recovery with GitHub Copilot SDK

An independent implementation of the [checkout recovery contract](../docs/).
Copilot owns the model/tool loop and native conversation state. The application
owns deterministic policy, durable approval, idempotent remediation and verification.

**Deployed and verified on 2026-09-20:** isolated Azure infrastructure, API/UI and
Foundry Hosted version **3**. API and Hosted seven-case E2E, all eight browser
paths, seven native Foundry evaluations and replacement-container native
conversation restoration passed. Original traces are present in the project's
linked Application Insights with no internal parent gaps. Details, the browser
DNS retry, original failed Hosted versions and evidence are in the
[issues, changes and fixes ledger](docs/design/issues-changes-fixes.md).

**Temporary public demo:** browser login is off; anyone with the UI URL can issue
demo commands. Private API/Azure authentication and business approval checks
remain enabled. See [configuration](docs/configuration.md) to restore login.
Successful health/polling API spans are filtered; command/error/model/tool traces
remain.

Laptop dependencies remain in `uv.lock`, using the Microsoft mirror. Cloud
dependencies use independently validated, hashed public-PyPI locks, including
`urllib3==2.8.0`; the laptop mirror is not a cloud-source restriction. Both profiles
use SDK **1.0.13**, native runtime **1.0.85**, protocol **3**.
[Cloud packaging instructions](infra/README.md) use `.venv-cloud`, never implicit
local `uv run`. The release gate still rejects vulnerable or mismatched artifacts.

The package, API, frontend, PostgreSQL state, configuration, telemetry and delivery
tooling belong to this lane. It does not import the MAF application or ignored POC.
Only framework-neutral domain models, fixtures and simulators come from `shared/`.

## Development and design

- [Local configuration](docs/configuration.md) and `.env.example`
- [Product requirements](docs/design/prd.md)
- [Business rules and approval](docs/design/business-rules.md)
- [User flow](docs/design/userflow.md)
- [4+1 architecture](docs/design/architecture.md)
- [Technology stack](docs/design/techstack.md)
- [Source map](docs/design/projectstructure.md)

Native SDK investigations use Azure-model BYOK with a refreshing Entra credential.
The packaged Copilot runtime owns conversation state and the model/tool loop.
Native files are archived privately, unchanged, at completed investigation
boundaries; business approval/resume never depends on those files.
