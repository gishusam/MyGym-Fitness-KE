-- Run ONLY on a dedicated platform database, never on an operational gym database.
CREATE TABLE IF NOT EXISTS platform_gyms (
    id VARCHAR(36) PRIMARY KEY,
    slug VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(120) NOT NULL,
    owner_clerk_user_id VARCHAR(128),
    status VARCHAR(32) NOT NULL DEFAULT 'pending_provisioning',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT platform_gym_status_check CHECK (status IN ('pending_provisioning','active','suspended','archived'))
);
CREATE INDEX IF NOT EXISTS ix_platform_gyms_slug ON platform_gyms (slug);
CREATE TABLE IF NOT EXISTS platform_audit (
    id VARCHAR(36) PRIMARY KEY,
    actor_clerk_user_id VARCHAR(128) NOT NULL,
    gym_id VARCHAR(36) REFERENCES platform_gyms(id),
    event VARCHAR(80) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
