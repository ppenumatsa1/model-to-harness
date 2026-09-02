# Microsoft Foundry workspace boundary

This folder follows the Foundry agent workspace convention for a single local
environment overlay:

- `agent-metadata.yaml` contains only non-secret local overlay/cache references.
- `suites/` caches reviewed evaluation-suite references or exports.
- `datasets/` caches local or remotely registered dataset references.
- `evaluators/` caches reviewed evaluator definitions.
- `results/` stores local evaluation outputs and comparison summaries.

These directories are metadata, cache, and result storage only. Ask before replacing
user-edited cache files. `evaluationSuites` remains empty until a suite, dataset, and
evaluators have actually been found or registered in Foundry.

`../eval.yaml` stays at the agent root and represents local evaluation intent, not
proof of a remote Foundry suite. This workspace contains no agent name, project
endpoint, resource ID, subscription, registry, credential, remote suite claim, azd
binding, or deployment state.

Runtime prompts and tools remain backend source code, primarily in
`backend/src/model_to_harness_langgraph/model_adapter.py`, `workflow.py`, and
`domain_gateway.py`. They must not be copied into `.foundry`. This folder never
overrides runtime orchestration, LangGraph checkpoints, PostgreSQL audit records, or
selected application memory.

No `azure.yaml` or azd deployment configuration belongs in this teaching placeholder.
