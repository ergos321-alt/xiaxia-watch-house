BEGIN;

CREATE TABLE IF NOT EXISTS hand_commands (
    id UUID PRIMARY KEY,

    action TEXT NOT NULL
        CHECK (action IN (
            'flashlight',
            'volume',
            'open_app',
            'timer',
            'alarm',
            'do_not_disturb',
            'battery_saver',
            'navigation'
        )),

    parameters JSONB NOT NULL
        DEFAULT '{}'::jsonb,

    status TEXT NOT NULL
        DEFAULT 'pending'
        CHECK (status IN (
            'pending',
            'delivered',
            'executed',
            'failed',
            'expired'
        )),

    created_at TIMESTAMPTZ NOT NULL,
    delivered_at TIMESTAMPTZ,
    executed_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL,

    result JSONB,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_hand_commands_pending
    ON hand_commands (created_at, id)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_hand_commands_status_created
    ON hand_commands (status, created_at);

COMMIT;

