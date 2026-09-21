# Trace acceptance

`acceptance.kql` is an exploratory inventory of application and native runtime
spans, not a release verdict. It includes native `chat`, `invoke_agent`, skill and
tool spans rather than selecting only `checkout.*` application spans.

For acceptance, start from the exact case IDs in saved API/Hosted reports:

1. Compute their `checkout.correlation` hashes (first 24 hex characters of SHA-256).
2. Find the corresponding command operation IDs in the selected lane's App Insights.
3. Retrieve **all** request/dependency spans in those operations, not just rows
   carrying the application correlation attribute.
4. Verify completed command/investigation/model/tool stages, deployed agent version
   for Hosted commands, and internal parent IDs. Inspect each original case.
5. Distinguish physical request/response/callback spans from unique model response
   and tool-call identities. Skill, workspace and delegation are real tool work.
6. Run content checks and verify the Foundry project's monitoring connection
   references this exact App Insights resource with private sharing.

Wait for bounded ingestion before stopping owned test sessions. If a final trace
is incomplete, retain the original failure; a replacement case is not a pass for it.
For remote smoke/E2E, `scripts/verify_hosted.py --keep-session` retains the owned
session and records its ID in the command journal. The caller must stop that exact
session after ingestion verification or failure diagnosis; default runs still
clean up automatically.

Native capture stays off. Explicit fixture capture emits only three diagnostic
tool shapes validated against deterministic fixtures; raw prompts, native session
files, workspace text and reviewer content are never included. `redaction.kql`
distinguishes these expected diagnostic records from unexpected payloads; also
validate actual payload shapes in downloaded acceptance data.

`CHECKOUT_COPILOT_TRACE_FILE` optionally records sanitized native spans locally.
For the API, appending `.application.jsonl` to the complete native filename
(for example, `native.jsonl.application.jsonl`) selects the application receipt
through the same safe exporter. These files prove local flow/correlation, not
Azure ingestion. Writes are serialized within the process, files are mode `0600`,
and each file is capped at 32 MiB; exceeding the cap reports export failure rather
than silently rotating away acceptance evidence. Use a new ignored path per run.
Production configuration rejects this development-only file exporter.

Model span names use the configured deployment for stable grouping.
`checkout.model.configured_deployment` is configuration, not proof of a server-side
model response. Observed `gen_ai.request.model` / `gen_ai.response.model` and the
native behavior profile remain separate attributes.

The API owns one telemetry provider for its process lifetime. After shutdown,
restart the process rather than constructing another traced Runtime: OpenTelemetry
does not support replacing an installed global provider. Foundry owns its own
provider; the Hosted adapter must not install the API provider.
