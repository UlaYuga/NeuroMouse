CREATE TABLE IF NOT EXISTS user_methods (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    method_id TEXT NOT NULL,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    source TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (owner_id, method_id)
);

CREATE INDEX IF NOT EXISTS idx_user_methods_owner ON user_methods (owner_id);
