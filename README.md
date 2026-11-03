# MyGym Fitness KE

MyGym Fitness KE is a responsive gym-management app for a single gym in Kenya. It is being built in five milestones; Milestone 1 currently provides secure staff sign-in, role-aware access, first-owner setup, and persisted gym settings.

## Architecture

- `artifacts/mygym-fitness-ke/` — React, TypeScript, Vite staff interface
- `backend/app/` — FastAPI API, Pydantic schemas, SQLAlchemy models, and business logic
- `backend/alembic/` — PostgreSQL schema migrations
- `artifacts/api-server/` — Express service used for the Clerk Frontend API proxy
- `lib/api-spec/openapi.yaml` — API contract source of truth
- `lib/api-client-react/` — generated TanStack Query client and hooks

## Development

The managed Replit workflows start the web app, Express proxy, and FastAPI service. For local commands:

```sh
pnpm --filter @workspace/mygym-fitness-ke run dev
pnpm --filter @workspace/api-server run dev
uv run uvicorn backend.app.main:app --app-dir . --host 0.0.0.0 --port 8082
```

Apply development database migrations and run checks with:

```sh
uv run alembic -c backend/alembic.ini upgrade head
uv run pytest backend/tests -q
pnpm --filter @workspace/api-spec run codegen
pnpm run typecheck
```

## Configuration

Replit supplies PostgreSQL and the Clerk keys. Set `INITIAL_OWNER_EMAIL` to the verified email of the first owner account before using the owner-bootstrap action. The app never makes an arbitrary first sign-in an owner.

Use Kenyan shillings (`KES`) and `Africa/Nairobi`. Peak-access windows intentionally remain unconfigured until the owner sets them in membership-plan setup. M-Pesa is staff-entered only; WhatsApp sending is not connected.

## Milestones

1. Foundation: authentication, roles, navigation, gym settings.
2. Gym operations: members, plans, subscriptions, payments, QR attendance.
3. Fitness: assessments, questionnaires, exercise library, trainer-approved plans.
4. Member portal and events: member access, workouts, progress, bookings.
5. Engagement and release readiness: persistent reminders, follow-up, reporting, audit and cross-role validation.
