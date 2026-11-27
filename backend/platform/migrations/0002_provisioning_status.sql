-- Run against the dedicated platform DB AFTER 0001_platform_registry.sql.
-- The operator CLI alone advances gyms through provisioning and awaiting_owner.
ALTER TABLE platform_gyms DROP CONSTRAINT IF EXISTS platform_gym_status_check;
ALTER TABLE platform_gyms ADD CONSTRAINT platform_gym_status_check
  CHECK (status IN (
    'pending_provisioning', 'provisioning', 'provision_failed',
    'awaiting_owner', 'active', 'suspended', 'archived'
  ));
