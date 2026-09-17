CREATE TABLE start_requests (
    request_id UUID PRIMARY KEY,
    command_fingerprint TEXT NOT NULL CHECK (command_fingerprint ~ '^[0-9a-f]{64}$'),
    run_id TEXT NOT NULL UNIQUE REFERENCES runs(run_id),
    result JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    CHECK ((result IS NULL) = (completed_at IS NULL))
);
