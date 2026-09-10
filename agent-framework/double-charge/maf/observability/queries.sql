-- Business audit only: these queries intentionally use raw business identifiers.
-- Replace the example schema with the release's actual DATABASE_SCHEMA.
-- Execute each parameterized query separately with a read-only database role.
-- Do not copy unrestricted audit records into logs, traces or release artifacts.

-- Ordered business audit for one run ($1 = raw run ID).
SELECT sequence, created_at, event_type, node, transition, summary, retry_attempt
FROM maf_double_charge.execution_events
WHERE run_id = $1
ORDER BY sequence;

-- Paused runs that require an explicit approval and resume.
SELECT run_id, case_id, current_step, checkpoint_id, updated_at
FROM maf_double_charge.runs
WHERE status = 'paused'
ORDER BY updated_at;

-- Retry and failure evidence ($1/$2 = bounded UTC start/end).
SELECT run_id, event_type, node, retry_attempt, summary, created_at
FROM maf_double_charge.execution_events
WHERE event_type IN ('tool.call.retried', 'tool.call.failed', 'run.failed')
  AND created_at >= $1 AND created_at < $2
ORDER BY created_at DESC;
