CREATE TABLE checkout_recovery_maf_sessions (
    case_id UUID PRIMARY KEY REFERENCES checkout_recovery_cases(case_id),
    framework_state JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
