# Agent instructions

This project was built with the microsoft-foundry skill. Before working on or answering questions about foundry agents, read the microsoft-foundry skill first.

Keep Microsoft Foundry overlay/cache work inside `.foundry/`. Runtime prompts,
instructions, tools, workflow logic, API code, and model integration remain in
`backend/src/maf_double_charge/`.

Treat root `eval.yaml` as local evaluation intent and `evals/run.py` as the
framework-specific executable evaluation runner. Do not claim that datasets,
evaluators, or suites exist remotely until they are verified.

Do not add `azure.yaml`, run azd, deploy resources, or invent endpoints, subscription
IDs, resource names, registry names, agent versions, or credentials.

