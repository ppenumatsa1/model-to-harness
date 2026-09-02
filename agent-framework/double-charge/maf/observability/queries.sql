-- Ordered business audit for one run.
SELECT sequence, created_at, event_type, node, transition, summary, retry_attempt
FROM maf_double_charge.execution_events
WHERE run_id = $1
ORDER BY sequence;

-- Paused runs that require an explicit approval and resume.
SELECT run_id, case_id, current_step, checkpoint_id, updated_at
FROM maf_double_charge.runs
WHERE status = 'paused'
ORDER BY updated_at;

-- Retry and failure evidence.
SELECT run_id, event_type, node, retry_attempt, summary, created_at
FROM maf_double_charge.execution_events
WHERE event_type IN ('tool.call.retried', 'tool.call.failed', 'run.failed')
ORDER BY created_at DESC;

