-- Apply only to the PLATFORM DATABASE, after earlier platform migrations.
-- Prevent two concurrent signup requests from creating customer gyms for the same owner.
CREATE UNIQUE INDEX IF NOT EXISTS ux_platform_customer_owner
ON platform_gyms (owner_clerk_user_id)
WHERE environment_kind = 'customer' AND owner_clerk_user_id IS NOT NULL;
