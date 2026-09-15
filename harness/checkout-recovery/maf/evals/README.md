# Delivery evaluation contract

`checkout_recovery_cases.json` contains only deterministic fixture identifiers,
required explicit approval decisions, and safe terminal-state expectations. It
contains no customer text, prompts, credentials, raw tool results, or durable
record payloads.

Run `scripts/verify_evals.py` before preparing an evaluation group. It verifies
the delivery dataset agrees with the framework-neutral fixture contract and that
the hosted `eval.yaml` refers to the checked-in dataset. Evaluating a hosted
deployment remains an operator action against a specifically selected project,
agent version, and environment; it is not performed by this repository.
