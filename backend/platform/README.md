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
