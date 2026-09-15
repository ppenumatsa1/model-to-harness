# Agent guidance

This project was built with the microsoft-foundry skill. Before working on or
answering questions about Foundry agents, read the microsoft-foundry skill first.

- Keep this MAF implementation independent from `agent-framework/double-charge`.
- Keep framework-neutral checkout records, simulators, fixtures, and evaluation
  contracts in `shared/`; do not put API, PostgreSQL, MAF, Azure, UI, or
  telemetry code there.
- PostgreSQL is authoritative for business state, approval commands, remediation
  idempotency, audit records, and verification. MAF session/checkpoint state is
  framework-owned.
- Preserve explicit FastAPI and Hosted Agent start, approval, and resume
  commands. Chat and model output never approve remediation.
- Do not expose prompts, model content, raw workspace files, raw checkpoints,
  credentials, connection strings, operation keys, or unrestricted tool data.
- Keep `infra/`, `.foundry/`, `evals/`, and deployment scripts lane-owned.
