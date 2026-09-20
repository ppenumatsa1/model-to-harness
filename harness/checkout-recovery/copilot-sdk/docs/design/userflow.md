# User flow

```mermaid
flowchart LR
    start[Start with request UUID] --> investigate[Read-only investigation]
    investigate --> policy{Application policy}
    policy -->|Automatic recovery allowed| recover[Idempotent remediation]
    policy -->|Human decision required| paused[Durable pause]
    policy -->|Failed or unresolved| review[Failure or manual review]
    paused --> approve[Explicit approval command]
    approve --> resume[Explicit Resume]
    resume -->|Approved and valid| recover
    resume -->|Pending, denied or stale| blocked[No action]
    recover --> verify[Verify business evidence]
    verify --> outcome[Persist actual outcome]
```

The React workspace retains the selected case and pending Start request identity.
An ambiguous Start response retries that same identity. Refresh reloads persisted
case/event/artifact projections without approving or resuming.

The UI presents safe summaries and durable audit events, not raw native session
files, hidden reasoning, system prompts, unrestricted tool payloads or secrets.
Manual review and verification failure are explicit outcomes, not evidence that
another approval button should be enabled.

Conversational continuation is an internal SDK capability, not an additional chat
approval interface.
