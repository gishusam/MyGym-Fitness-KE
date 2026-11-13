-- Run ONLY on the platform registry DB, after 0002_provisioning_status.sql.
-- Stores a non-secret logical alias. Never put passwords or connection URLs here.
ALTER TABLE platform_gyms ADD COLUMN IF NOT EXISTS environment_kind VARCHAR(20) NOT NULL DEFAULT 'customer';
ALTER TABLE platform_gyms ADD COLUMN IF NOT EXISTS database_ref VARCHAR(64);
CREATE UNIQUE INDEX IF NOT EXISTS uq_platform_gyms_database_ref ON platform_gyms(database_ref);
ALTER TABLE platform_gyms DROP CONSTRAINT IF EXISTS platform_gym_environment_check;
ALTER TABLE platform_gyms ADD CONSTRAINT platform_gym_environment_check
  CHECK (environment_kind IN ('customer', 'development', 'demo'));
ALTER TABLE platform_gyms DROP CONSTRAINT IF EXISTS platform_gym_status_check;
ALTER TABLE platform_gyms ADD CONSTRAINT platform_gym_status_check
  CHECK (status IN ('pending_provisioning', 'provisioning', 'provision_failed',
                   'awaiting_owner', 'linked', 'active', 'suspended', 'archived'));
