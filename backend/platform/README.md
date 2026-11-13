# MyGym platform admin — Milestone 9A starter

This is a **separate, opt-in FastAPI application** for the SaaS operator. It does not alter the current gym API, or its database migrations and permissions.

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

## 9B — Operator-controlled provisioning

This adds a controlled **request → provisioning → awaiting_owner** lifecycle.
The `provisioning-request` API creates an audit event but **never** starts a database operation in the web process.

1. Run `0002_provisioning_status.sql` on the platform DB (after migration 0001).
2. Register a gym through the authenticated platform registry API.
3. Prepare a **separate, pre-created, least-privileged** PostgreSQL tenant owner role. The operator connection needs `CREATEDB` and should be restricted to an administrator-maintained provisioning environment.
4. Set `PLATFORM_DATABASE_URL` to the platform DB, `GYM_PROVISION_ADMIN_URL` to a PostgreSQL maintenance database connection with CREATEDB, `GYM_PROVISION_TENANT_URL` to the tenant owner's maintenance DB connection (same host/cluster), and `GYM_PROVISION_OWNER_ROLE` to that owner's PostgreSQL role identifier. **Never expose these secrets to the frontend.** Each gym must ultimately have its own restricted role and credentials; reusing a shared tenant role across customers is not safe for production.
5. Run a dry run (does not change data):

   ```sh
   uv run python -m backend.platform.provisioning --gym-id <gym-uuid>
   ```

6. When ready, run the operator-only provisioner:

   ```sh
   uv run python -m backend.platform.provisioning --gym-id <gym-uuid> --apply
   ```

The command creates the `mygym_tenant_<slug>` database if absent, checks ownership on retry, applies the existing Alembic migrations using the tenant role, verifies essential tables, and updates the registry to `awaiting_owner`. It **never** creates mock Clerk users, impersonates an owner, automatically activates a gym or drops a database on failure. Failures move to `provision_failed` and can be retried after investigation.

**Important limits before production:** PostgreSQL maintenance credentials and tenant isolation must be properly provisioned; an authenticated owner invitation/bootstrap and per-request routing are not yet built. Do not treat `awaiting_owner` as an activated or usable gym. The current CLI is intended for a carefully controlled local/operator environment, not an untrusted multi-user deployment or automated public provisioning.
