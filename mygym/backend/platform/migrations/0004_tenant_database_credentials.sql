-- Run ONLY on the dedicated platform registry database.
-- The value is Fernet-encrypted by the platform service and is never returned by its API.
ALTER TABLE platform_gyms
    ADD COLUMN IF NOT EXISTS database_url_ciphertext TEXT;
