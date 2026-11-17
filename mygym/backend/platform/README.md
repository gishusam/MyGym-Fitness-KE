# MyGym platform admin — Milestone 9A starter

This is a **separate, opt-in FastAPI application** for the SaaS operator. It does not alter the current gym API, or its database migrations and permissions.

The API artifact routes `/api/platform/*` to this service on its own process and port. The gym API continues to serve the other `/api/*` routes. Configure the platform service's `PLATFORM_DATABASE_URL` and `PLATFORM_ADMIN_CLERK_IDS` server-side before using the console; without them, platform requests fail closed.

## Scope in this initial commit

- Central **gym registry**: list, register, fetch gyms
- Explicit Clerk user-ID allowlist for platform admin access (`PLATFORM_ADMIN_CLERK_IDS`)
- Audit record whenever a gym is registered
- New gyms remain `pending_provisioning` — **this does not create a database or invite a user yet**
- No cross-gym personal data access and no support impersonation in this phase

## Deployment requirements

1. Provision a *separate* PostgreSQL database, e.g. `mygym_platform`, with credentials that have **no access** to the per-gym databases.
2. Set `PLATFORM_DATABASE_URL` to that platform database URL. Never set it to the gym `DATABASE_URL`.
3. Run `backend/platform/migrations/0001_platform_registry.sql` against the platform DB using your normal deployment/migration tooling. Do not execute it on a gym database.
4. Set `PLATFORM_ADMIN_CLERK_IDS` to one or more specific verified Clerk `sub` values (comma-separated). Do not use a gym Owner role, an email address, or a wildcard.
5. Deploy this service separately from the gym API with HTTPS, restricted origins, appropriate rate limits, and a separate service account.
6. Apply `0002_provisioning_status.sql`, `0003_existing_gym_links.sql`, and `0004_tenant_database_credentials.sql` in order.
7. Set `PLATFORM_CREDENTIAL_ENCRYPTION_KEYS` as a server-side secret. Generate a key in the protected operator environment with `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`. It is a comma-separated list of Fernet keys, with the current encryption key first and any temporary decryption-only keys after it. Never place it in a frontend build environment or commit the value.

To rotate the encryption key, add the new key first and keep the current key after it, then run `uv run python -m backend.platform.rotate_credentials` to validate the stored records. Apply with `--apply`, verify the command reports the expected number of rotated records, then remove the old key from the configured list. The rotation command never prints tenant URLs or passwords.

For local development, the API artifact starts this service on port `8083` and routes `/api/platform` to it. The service's health check is `/api/platform/healthz`. Keep the platform service's environment separate from the gym API service; in particular, do not put platform or provisioning credentials in frontend build variables.

Local server command (after setting the environment variables):

```sh
uv run uvicorn backend.platform.app:app --host 127.0.0.1 --port 8083
```

Run the platform tests:

```sh
uv run pytest backend/tests/test_platform_admin.py -q
```

## Next slices

- 9A: transactionally safe gym provisioning with per-gym DB credentials, migration execution, owner invitation, lifecycle state and rollback/retry support
- 9B: platform dashboard and billing/usage aggregation without reading private gym records
- 9C: short-lived support sessions, explicit gym-approved scope, request correlation, strict read-only default, and full audit trails. **Do not add direct Clerk impersonation**.

The registry does not represent a provisioned or functioning tenant until provisioning completes and its status is transitioned to `active` by a future service.

The existing-gym linking command still verifies the two known databases without changing them; it does not yet enroll separate per-gym connection credentials or change their PostgreSQL roles. Do not route requests to those linked gyms until each has its own restricted connection URL stored in the encrypted registry.

## 9B — Operator-controlled provisioning

This adds a controlled **request → provisioning → awaiting_owner** lifecycle.
The `provisioning-request` API creates an audit event but **never** starts a database operation in the web process.

1. Run `0002_provisioning_status.sql` on the platform DB (after migration 0001).
2. Register a gym through the authenticated platform registry API.
3. Prepare a **separate, pre-created, least-privileged** PostgreSQL tenant owner role. The operator connection needs `CREATEDB` and should be restricted to an administrator-maintained provisioning environment.
4. Set `PLATFORM_DATABASE_URL` to the platform DB and `GYM_PROVISION_ADMIN_URL` to an operator-only PostgreSQL maintenance connection with `CREATEDB` and `CREATEROLE`. Do not put the admin URL in the platform API or frontend runtime.
5. Set `PLATFORM_CREDENTIAL_ENCRYPTION_KEYS` on the server. Generate a Fernet key in the protected operator environment, save it directly as a secret, and never commit or paste it into chat.
6. Run a dry run (does not change data):

   ```sh
   uv run python -m backend.platform.provisioning --gym-id <gym-uuid>
   ```

7. When ready, run the operator-only provisioner:

   ```sh
   uv run python -m backend.platform.provisioning --gym-id <gym-uuid> --apply
   ```

The command creates a dedicated, restricted PostgreSQL login for that gym, creates the `mygym_tenant_<slug>` database if absent, encrypts the tenant connection URL into the platform registry, applies Alembic migrations using that gym's role, verifies essential tables, and updates the registry to `awaiting_owner`. The connection URL is not returned by platform API responses. Retries reuse the encrypted credential and only continue when the existing database is owned by the expected per-gym role. Migration subprocesses receive only the tenant URL, not platform or provisioning credentials. It **never** creates mock Clerk users, impersonates an owner, automatically activates a gym or drops a database on failure. Failures move to `provision_failed` and can be retried after investigation.

**Important limits before production:** PostgreSQL maintenance credentials and tenant isolation must be properly provisioned; an authenticated owner invitation/bootstrap and per-request tenant routing are not yet built. Do not treat `awaiting_owner` as an activated or usable gym. The current CLI is intended for a carefully controlled local/operator environment, not an untrusted multi-user deployment or automated public provisioning.
