# Harness stage

This directory is reserved for the next article-series stage: placing the framework
workflows inside complete task environments that can carry work to verified results.

Future projects should demonstrate:

- context assembly from instructions, state, selected memory, history, and workspace;
- scoped skills, tools, permissions, identity, and approval;
- filesystem, shell, browser, API, and artifact boundaries;
- planning, helper-agent collaboration, and context compaction;
- durable pause/resume, cancellation, recovery, and verification loops;
- inspectable finished artifacts rather than transcript-only success.

Nothing here is a shared runtime for the MAF or LangGraph examples. Harness projects
should preserve the same rule: business side effects are deterministic, authorized,
idempotent, audited, and verified.
