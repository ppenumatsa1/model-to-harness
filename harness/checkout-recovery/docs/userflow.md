# User flow

```text
Start case
  -> inspect order
  -> gather selected context
  -> choose diagnostic tool or bounded delegate
  -> create safe workspace artifact
  -> propose remediation
  -> record approval if required
  -> explicitly resume
  -> remediate
  -> verify authoritative records
  -> report evidence, failure, or manual review
```

The UI displays allowlisted progress, evidence identifiers, approval state, and
outcome. It starts, approves, and resumes only through explicit API commands;
it does not receive raw model context, prompts, tool payloads, or checkpoints.
