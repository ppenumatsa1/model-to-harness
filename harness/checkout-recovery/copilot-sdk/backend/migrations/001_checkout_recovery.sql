CREATE TABLE checkout_recovery_cases (
    case_id UUID PRIMARY KEY,
    run_id UUID NOT NULL UNIQUE,
    order_id TEXT NOT NULL,
    fixture_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    state JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE checkout_recovery_approvals (
    case_id UUID PRIMARY KEY REFERENCES checkout_recovery_cases(case_id),
    decision TEXT NOT NULL,
    reviewer_id TEXT,
    recorded_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE checkout_recovery_remediation_ledger (
    case_id UUID PRIMARY KEY REFERENCES checkout_recovery_cases(case_id),
    operation_id UUID NOT NULL UNIQUE,
    request_fingerprint TEXT NOT NULL UNIQUE,
    action TEXT NOT NULL,
    status TEXT,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE checkout_recovery_audit_events (
    event_id BIGSERIAL PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES checkout_recovery_cases(case_id),
    code TEXT NOT NULL,
    summary TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL
);
