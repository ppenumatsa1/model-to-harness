# Microsoft Foundry workspace overlay

This directory follows the Microsoft Foundry workspace convention and contains
metadata, caches, and evaluation results only:

- `agent-metadata.yaml` is the preferred single-environment local overlay.
- `suites/` caches remotely verified suite definitions.
- `datasets/` caches dataset references or reviewed local copies.
- `evaluators/` caches remotely verified evaluator definitions.
- `results/` stores local or downloaded evaluation results.

The `local` overlay intentionally has no project endpoint, resource identifier,
agent version, registry, or remote suite reference. `evaluationSuites` remains empty
until a suite, dataset, and evaluator are found or registered in Microsoft Foundry.
`eval.yaml` at the agent root is local evaluation intent, not proof that remote
assets exist.

Runtime prompts, model instructions, workflow tools, and executable code stay in
`backend/src/maf_double_charge/`; they do not belong in `.foundry`. Never place
credentials, raw prompts, PostgreSQL state, checkpoint payloads, or production
conversation data in this workspace.

No `azure.yaml`, azd environment, or deployment binding exists in this app.

