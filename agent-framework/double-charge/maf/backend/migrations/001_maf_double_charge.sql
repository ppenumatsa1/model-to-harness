CREATE SCHEMA IF NOT EXISTS maf_double_charge;

CREATE TABLE IF NOT EXISTS maf_double_charge.runs (
    run_id text PRIMARY KEY,
    case_id text UNIQUE NOT NULL,
    status text NOT NULL,
    current_step text NOT NULL,
    state jsonb NOT NULL,
    checkpoint_id text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS maf_double_charge.execution_events (
    sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id uuid UNIQUE NOT NULL,
    case_id text NOT NULL,
    run_id text NOT NULL REFERENCES maf_double_charge.runs(run_id),
    event_type text NOT NULL,
    node text,
    transition text,
    checkpoint_id text,
    retry_attempt integer,
    idempotency_key text,
    summary text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS execution_events_run_sequence_idx
    ON maf_double_charge.execution_events(run_id, sequence);

CREATE TABLE IF NOT EXISTS maf_double_charge.approvals (
    run_id text PRIMARY KEY REFERENCES maf_double_charge.runs(run_id),
    checkpoint_id text UNIQUE NOT NULL,
    response jsonb NOT NULL,
    resolved_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS maf_double_charge.outcomes (
    run_id text PRIMARY KEY REFERENCES maf_double_charge.runs(run_id),
    outcome jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS maf_double_charge.selected_memory (
    case_id text PRIMARY KEY,
    memory jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS maf_double_charge.maf_checkpoints (
    checkpoint_id text PRIMARY KEY,
    workflow_name text NOT NULL,
    run_id text NOT NULL REFERENCES maf_double_charge.runs(run_id),
    checkpoint jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS maf_checkpoints_workflow_created_idx
    ON maf_double_charge.maf_checkpoints(workflow_name, created_at DESC);

CREATE TABLE IF NOT EXISTS maf_double_charge.refund_ledger (
    idempotency_key text PRIMARY KEY,
    request_fingerprint text NOT NULL,
    account_id text NOT NULL,
    charge_id text NOT NULL,
    amount numeric(19, 4) NOT NULL,
    currency text NOT NULL,
    refund_id text UNIQUE NOT NULL,
    refund jsonb NOT NULL,
    created_by_run_id text NOT NULL
        REFERENCES maf_double_charge.runs(run_id),
    created_at timestamptz NOT NULL DEFAULT now()
);
