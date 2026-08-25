BEGIN;

-- Upgrade the existing Hand whitelist without deleting commands or rebuilding
-- the table. The original unnamed CHECK constraint has PostgreSQL's default
-- name: hand_commands_action_check.
ALTER TABLE hand_commands
    DROP CONSTRAINT IF EXISTS hand_commands_action_check;

ALTER TABLE hand_commands
    ADD CONSTRAINT hand_commands_action_check
    CHECK (action IN (
        'flashlight',
        'volume',
        'open_app',
        'timer',
        'alarm',
        'do_not_disturb',
        'battery_saver',
        'navigation',
        'knock'
    ));

CREATE TABLE IF NOT EXISTS eye_requests (
    id UUID PRIMARY KEY,
    request_type TEXT NOT NULL
        DEFAULT 'screen'
        CHECK (request_type = 'screen'),
    frame_count SMALLINT NOT NULL
        DEFAULT 1
        CHECK (frame_count BETWEEN 1 AND 3),
    focus TEXT,
    status TEXT NOT NULL
        DEFAULT 'pending'
        CHECK (status IN (
            'pending',
            'capturing',
            'uploaded',
            'analyzing',
            'completed',
            'failed',
            'expired'
        )),
    created_at TIMESTAMPTZ NOT NULL,
    claimed_at TIMESTAMPTZ,
    uploaded_at TIMESTAMPTZ,
    analysis_started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    result_expires_at TIMESTAMPTZ NOT NULL,
    visual_facts JSONB,
    error_code TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_eye_requests_pending
    ON eye_requests (created_at, id)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_eye_requests_status_updated
    ON eye_requests (status, updated_at);

CREATE INDEX IF NOT EXISTS idx_eye_requests_result_expiry
    ON eye_requests (result_expires_at)
    WHERE status IN ('completed', 'failed', 'expired');

COMMIT;

