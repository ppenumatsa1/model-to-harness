# Agent guidance

This project was built with the microsoft-foundry skill. Before working on or answering questions about foundry agents, read the microsoft-foundry skill first.

## Workspace boundaries

- Keep `eval.yaml` at this agent root.
- Treat `.foundry/` as metadata, cache, and evaluation-result storage only.
- Keep runtime prompts, model instructions, tools, and orchestration in backend source.
- Do not place secrets, endpoints, resource IDs, subscriptions, or credentials in
  `.foundry/`.
- Keep Azure deployment assets inside this LangGraph lane. Do not import or reuse MAF
  deployment modules, images, scripts, identities, databases, or azd state.
- `azure.yaml` deploys the Foundry Responses 2.0 adapter from
  `infra/foundry-hosted/agent` with hosted runtime `python_3_13`. Local application
  development and Container Apps continue to use Python 3.12.
- Run `python scripts/prepare_hosted.py` before direct-code agent deployment so the
  generated source contains this lane package plus the framework-neutral shared
  package. Never add a runtime path back to the repository or another framework.
- Keep deployment values parameterized. Secrets belong only in the selected azd
  environment or secure Bicep parameters, never committed files.
- Preserve explicit FastAPI workflow command endpoints and PostgreSQL as the durable
  audit/checkpoint boundary. The hosted adapter must call `WorkflowService`; it must
  not introduce a second workflow authority or infer approval from conversation.
- Keep frontend traffic same-origin through the nginx `/api` proxy. Do not expose the
  internal backend Container App directly.
- Keep the Foundry project connected to this lane's Application Insights resource
  through `infra/main.bicep`. Do not set the platform-reserved
  `APPLICATIONINSIGHTS_CONNECTION_STRING` in the hosted `azure.yaml`.
- Preserve the Responses trace boundary and safe correlation hierarchy:
  `foundry.responses.invoke` -> `workflow.run` -> workflow node/model/tool evidence.
  Durable events may project node and deterministic tool spans, but telemetry never
  replaces PostgreSQL audit state.
- Never trace complaint text, prompts, model content, raw checkpoint state,
  idempotency keys, credentials, connection strings, or unrestricted tool
  arguments/results.

## Required validation

From this lane, run:

```bash
uv run pytest
uv run ruff check backend/src backend/tests scripts/prepare_hosted.py
./scripts/smoke.sh
```

For deployment changes, also compile `infra/main.bicep`, run `bash -n` on changed
scripts, prepare the hosted package, and run `./scripts/smoke_azure.sh` after rollout.
