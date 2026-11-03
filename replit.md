# MyGym Fitness KE

Gym management and member engagement for a single gym in Kenya, built around simple, dependable daily operations.

## Run & Operate

- `pnpm --filter @workspace/mygym-fitness-ke run dev` — run the web app through its managed workflow
- `pnpm --filter @workspace/api-server run dev` — run the Express Clerk proxy edge
- `uv run alembic -c backend/alembic.ini upgrade head` — apply development schema migrations
- `uv run pytest backend/tests -q` — run backend tests
- `pnpm run typecheck` — typecheck shared libraries and workspace packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec
- Required platform environment: `DATABASE_URL`, `CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, `VITE_CLERK_PUBLISHABLE_KEY`
- Set `INITIAL_OWNER_EMAIL` before using the first-owner bootstrap flow; it must be a verified Clerk email.

## Stack

- Frontend: React, TypeScript, Vite, Tailwind CSS, wouter, TanStack Query, Clerk
- Business API: Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2.x
- Database: PostgreSQL with Alembic migrations
- Express 5 service: Clerk Frontend API proxy only
- API contracts: OpenAPI in `lib/api-spec/openapi.yaml`; Orval generates hooks and schemas
- Workspace: pnpm monorepo; Python dependencies are managed from root `pyproject.toml`

## Where things live

- `artifacts/mygym-fitness-ke/src/` — web app and shared staff shell
- `backend/app/api/routes/` — FastAPI routes
- `backend/app/models/` — SQLAlchemy models
- `backend/alembic/` — database migrations
- `lib/api-spec/openapi.yaml` — API contract source of truth
- `artifacts/api-server/` — Express Clerk proxy service
- `artifacts/api-server/.replit-artifact/artifact.toml` — proxy and FastAPI service routing

## Architecture decisions

- Business endpoints and role checks live in FastAPI; Express only serves Clerk's production browser proxy.
- Staff roles are application database records, not client-controlled or inferred from Clerk metadata.
- The first owner is bootstrapped only when the signed-in Clerk account has a verified `INITIAL_OWNER_EMAIL`; first sign-in does not equal owner.
- Gym settings start in `Africa/Nairobi` and `KES`; peak-access hours remain unconfigured until the owner confirms them in membership-plan setup.
- Development schema changes use Alembic; production schema changes for the managed database follow Replit's publish-time database workflow.

## Product

Milestone 1 provides Clerk staff sign-in, role-aware navigation, a secure owner bootstrap flow, and persisted gym settings with audit logging. Later milestones add memberships, payments, attendance, fitness plans, member access, events, and engagement workflows.

## User preferences

- Use Kenyan shillings (KES) and the `Africa/Nairobi` timezone.
- Do not store member profile photographs; use initials avatars.
- Keep the system affordable, simple, responsive, and operationally focused; do not claim M-Pesa or WhatsApp integrations are connected.

## Gotchas

- The initial owner bootstrap returns 503 until `INITIAL_OWNER_EMAIL` is configured; it never grants owner to an arbitrary first account.
- Run API code generation after changing `lib/api-spec/openapi.yaml`.
- The FastAPI service uses its managed `PORT`; its app directory is the repository root relative to the API artifact workflow.

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
