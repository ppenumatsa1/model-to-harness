# Agent guidance

This project was built with the `microsoft-foundry` skill. Before changing or
answering questions about Foundry agents, read that skill first.

## Workspace boundaries

- Keep Microsoft Foundry overlay/cache work inside `.foundry/`. Runtime prompts,
  instructions, tools, workflow logic, API code, and model integration remain in
  `backend/src/maf_double_charge/`.
- Keep all Azure deployment assets, identities, databases, images, scripts, and azd
  state inside this MAF lane. Do not import or reuse LangGraph deployment modules.
- `azure.yaml` packages the independent Responses 2.0 Hosted Agent from
  `infra/foundry-hosted/agent`. Local development and Container Apps use Python 3.12;
  the hosted runtime uses its declared Foundry Python runtime.
- Preserve explicit FastAPI start, approval, and resume commands. Human approval is a
  durable command boundary, not a blocking wait or a decision inferred from chat.
- PostgreSQL remains authoritative for workflow state, approval commands, refunds,
  and durable audit records. MAF checkpoints remain framework-owned.
- Keep frontend traffic same-origin through the nginx `/api` proxy. Do not expose the
  internal backend Container App directly.
- Treat root `eval.yaml` as evaluation intent and `evals/run.py` as the
  framework-specific executable runner. Do not claim remote evaluation results until
  the result rows have been inspected.
- Keep deployment values parameterized. Never commit secrets, endpoints,
  subscriptions, connection strings, or credentials.

## Observability safety

- Keep the Foundry project connected to this lane's Application Insights resource
  through `infra/app/main.bicep`. Do not set the platform-reserved
  `APPLICATIONINSIGHTS_CONNECTION_STRING` in hosted `azure.yaml`.
- Preserve MAF's native Responses, workflow, edge-group, executor, model, and message
  trace hierarchy with conversation, case, and run correlation.
- Never trace complaint text, prompts, model content, raw checkpoint payloads,
  idempotency keys, credentials, connection strings, or unrestricted tool
  arguments/results.

## Required validation

From this lane, run:

```bash
uv run pytest
uv run ruff check backend/src backend/tests
./scripts/smoke.sh
```

For deployment changes, also compile `infra/app/main.bicep`, run `bash -n` on changed
scripts, prepare the hosted package, and run the Azure smoke test after rollout.
