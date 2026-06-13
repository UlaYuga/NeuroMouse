ALTER TABLE sessions
    ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'anonymous';

CREATE INDEX IF NOT EXISTS idx_sessions_owner_id
    ON sessions (owner_id);

ALTER TABLE datasets
    ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'anonymous';

CREATE INDEX IF NOT EXISTS idx_datasets_owner_id
    ON datasets (owner_id);

ALTER TABLE jobs
    ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'anonymous';

CREATE INDEX IF NOT EXISTS idx_jobs_owner_id
    ON jobs (owner_id);
