CREATE SCHEMA IF NOT EXISTS __schema__;

CREATE TABLE IF NOT EXISTS __schema__.runs (
  run_id text PRIMARY KEY,
  case_id text UNIQUE NOT NULL,
  customer_id text NOT NULL,
  status text NOT NULL,
  current_step text NOT NULL,
  checkpoint_id text,
  approval_required boolean NOT NULL DEFAULT false,
  state jsonb NOT NULL DEFAULT '{}'::jsonb,
  outcome jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS __schema__.events (
  sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  event_id uuid NOT NULL UNIQUE,
  case_id text NOT NULL,
  run_id text NOT NULL REFERENCES __schema__.runs(run_id),
  event_type text NOT NULL,
  event_time timestamptz NOT NULL DEFAULT now(),
  node text,
  status text,
  summary text NOT NULL,
  data jsonb NOT NULL DEFAULT '{}'::jsonb,
  dedupe_key text,
  UNIQUE (run_id, dedupe_key)
);

CREATE INDEX IF NOT EXISTS langgraph_events_run_sequence
  ON __schema__.events(run_id, sequence);

CREATE TABLE IF NOT EXISTS __schema__.approvals (
  run_id text PRIMARY KEY REFERENCES __schema__.runs(run_id),
  checkpoint_id text NOT NULL,
  decision text NOT NULL CHECK (decision IN ('approve', 'deny')),
  reviewer_id text NOT NULL,
  reason text,
  consumed boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS __schema__.selected_memory (
  customer_id text NOT NULL,
  case_id text NOT NULL,
  facts jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (customer_id, case_id)
);

CREATE TABLE IF NOT EXISTS __schema__.refunds (
  idempotency_key text PRIMARY KEY,
  request_fingerprint text NOT NULL,
  refund_id text NOT NULL UNIQUE,
  case_id text NOT NULL,
  run_id text NOT NULL,
  customer_id text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
