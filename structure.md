# Project Structure Reference

## Where this file came from

Claude Code generated this by reading [fastapi/full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template)
— the official FastAPI full-stack template — and distilling its layout into rules. The template is a
working repo with a concrete domain (items and users, Postgres, JWT auth); this file is that repo's
*shape* with the domain stripped out, so it applies to a project about something else entirely.

One instruction shaped the output beyond that: **target AWS, not FastAPI Cloud.** The template deploys
to FastAPI Cloud or a Traefik-fronted Docker host; §9 translates that shape into ECS/ALB/ECR instead.
That section is the one part with no direct counterpart upstream.

Two things follow from being generated rather than hand-written:

- **The template is upstream.** When this file and the template disagree, the template is right and this
  file is stale. Go read the source repo — and treat anything here that the template doesn't corroborate
  as a summary that may have drifted, not as an authority.
- **It describes the pattern, not this project.** Sections here assume an ORM, migrations, and auth
  because the template has them. recipe-genome has none of those — Weaviate is the only datastore,
  there are no users, and the schema is owned by the offline pipeline rather than the API. Every place
  this project departs from the pattern is reasoned through in
  [CLAUDE.md § Deviations from structure.md](CLAUDE.md#deviations-from-structuremd). Read the deviations
  before applying a rule from here to this repo.

Hand this file to Claude Code at the start of a *new* project as the architectural contract to follow,
and apply the same shape to whatever that project's actual resources are.

---

## 1. Repo layout

```
backend/     FastAPI app — own pyproject.toml, own dependency lockfile, own venv
frontend/    React + Vite app — own package.json
packages/*   optional shared workspace packages (e.g. email templates)
compose.yml, compose.override.yml, compose.deploy.yml   Docker orchestration
```

Rule: **backend and frontend are independent projects** with independent tooling
(Python/uv vs. Node/bun). Neither's build should require the other's toolchain installed.
They're only wired together by Docker Compose (local dev / self-host) and by one generated
API client (see §6). Don't reach for a shared build tool or monorepo bundler to connect them —
that's exactly what the codegen step exists to avoid.

Root `package.json` uses **workspaces** (`frontend`, `packages/*`) purely for JS tooling —
this is not where Python lives.

---

## 2. Backend layering — `backend/app/`

```
main.py              FastAPI() instantiation only — no route logic here
api/
  main.py            mounts every router: api_router.include_router(...)
  deps.py            shared FastAPI dependencies (DB session, current user)
  routes/
    <resource>.py     one file per resource, one APIRouter per file
core/
  config.py          Settings(BaseSettings) — all runtime config, env-driven
  db.py              engine/session setup
  security.py        password hashing, JWT encode/decode
models.py             SQLModel classes — ORM model AND Pydantic schema, one file
crud.py                DB read/write functions, no HTTP concerns
alembic/               versioned migrations (never auto-create tables)
```

**Rule — adding a new resource always touches the same four places, in this order:**
1. `models.py` — add the SQLModel table + its `*Create` / `*Public` / `*Update` variants
2. `crud.py` — add the DB functions operating on it
3. `api/routes/<resource>.py` — new `APIRouter(prefix="/<resource>", tags=["<resource>"])`,
   thin handlers that call `crud.py`, not raw SQL
4. `api/main.py` — `api_router.include_router(<resource>.router)`
5. `alembic revision --autogenerate` — new migration for the schema change

Routes stay thin (validate input, call crud, return). Business logic lives in `crud.py` or a
`services/` module if it grows past simple CRUD — that split is what keeps handlers testable
without spinning up HTTP.

**Non-obvious: the operation-ID function.** In `main.py`:
```python
def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"

app = FastAPI(generate_unique_id_function=custom_generate_unique_id, ...)
```
Without this, FastAPI's default operation IDs are unstable and produce ugly generated
TypeScript method names. This function is *why* the generated client ends up with clean
names like `ItemsService.readItems()` instead of `items_read_items_api_v1_items__get`.
**Carry this into the new project verbatim.** The router `tags=[...]` value becomes the
generated TS class name — name resources accordingly (singular concept, plural tag is fine:
`tags=["items"]` → `ItemsService`).

**Config (`core/config.py`):** one `Settings(BaseSettings)` class, all env vars declared as
typed fields (not scattered `os.environ.get()` calls), validated at import time — a missing
or malformed env var crashes on startup, not mid-request. Includes a guard that refuses
placeholder secrets (`"changethis"`) outside development:
```python
if value == "changethis":
    if self.ENV == "development": warnings.warn(...)
    else: raise ValueError(...)
```
Carry this pattern — it's a cheap, real safety net against deploying with default secrets.

**Auth pattern:** JWT bearer tokens. `core/security.py` handles hashing (passlib/bcrypt-style)
and JWT encode/decode. `api/deps.py` exposes typed dependencies (`SessionDep`, `CurrentUser`)
injected via `Depends(...)` / `Annotated` — routes declare `current_user: CurrentUser` as a
parameter and get an authenticated, typed user with zero boilerplate per route.

---

## 3. Database & migrations

- SQLModel tables in `models.py` double as request/response schemas (`ItemCreate`,
  `ItemPublic`, `ItemUpdate` inherit from a shared base) — **do not** hand-maintain a
  separate Pydantic schema layer on top of the ORM models; that duplication is what SQLModel
  exists to remove.
- Alembic owns schema changes. Never rely on `SQLModel.metadata.create_all()` outside tests —
  every schema change is a committed, reviewable migration file.
- `backend_pre_start.py` / `prestart.sh`-style script waits for the DB to be reachable and
  runs migrations before the app starts — needed because in Compose/ECS the DB container
  may not be ready the instant the app container starts.

---

## 4. Frontend architecture — `frontend/src/`

```
client/          AUTO-GENERATED — never hand-edit (see §6)
routes/          file-based routes (TanStack Router) — filename = URL path
components/
  <Feature>/     one folder per feature/domain area, not one flat components/ dump
  ui/            shadcn/ui primitives (owned/vendored, not a node_modules black box)
hooks/           useAuth.ts, useCustomToast.ts, etc. — cross-cutting client logic
lib/utils.ts     small shared helpers (e.g. cn() for Tailwind class merging)
main.tsx         router + query client setup
```

**Rules:**
- **Routing**: TanStack Router, file-based. A new page = a new file under `routes/`, not a
  manually maintained route table. `routes/_layout.tsx` = authenticated shell; routes outside
  it (login, signup, password reset) are public.
- **Server state**: TanStack Query only. Don't hold API data in `useState`/Context — mutations
  go through `useMutation`, reads through `useQuery`, cache invalidation via `queryClient`.
  Client-only UI state (modal open/closed, form draft) stays local.
- **Forms**: `react-hook-form` + `zod` schema + `zodResolver`. Zod validates the form; it does
  **not** duplicate the API contract — that's what the generated types are for.
- **Components**: grouped by feature (`components/Items/`, `components/Admin/`), not by
  technical type (no `components/buttons/`, `components/modals/`). shadcn/ui primitives live
  in `components/ui/` and are vendored source, not a dependency — expect to edit them directly.
- **Styling**: Tailwind CSS utility classes; no CSS-in-JS, no separate stylesheet per component.

---

## 5. Environment & config

- One root `.env` for shared/backend values (`SECRET_KEY`, `DATABASE_URL`, `FIRST_SUPERUSER`,
  SMTP vars) — read by `core/config.py` via `env_file="../.env"`.
- `frontend/.env` for frontend-only build-time values (`VITE_API_URL` etc.).
- `compose.override.yml` is auto-loaded by `docker compose` locally on top of `compose.yml`
  and adds dev-only things: exposed ports, `--reload`/watch mode, Traefik dashboard.
  `compose.deploy.yml` is the deploy-time overlay (see §7). This override-file pattern —
  one base file + environment-specific overlays — is worth keeping even if the target isn't
  Docker Compose in prod: keep a base config and layer environment-specific values, don't
  branch config with `if env == "prod"` scattered through code.

---

## 6. The OpenAPI codegen loop — the core cross-stack contract

This is the mechanism that keeps backend and frontend from drifting apart. Reproduce it exactly.

1. Backend defines routes with typed Pydantic/SQLModel request/response models. FastAPI
   auto-derives the OpenAPI schema — nothing written by hand.
2. A script generates `openapi.json` **by importing the FastAPI app in-process** (not by
   curling a running server):
   ```bash
   uv run python -c "import app.main, json; print(json.dumps(app.main.app.openapi()))" > openapi.json
   ```
3. `@hey-api/openapi-ts` (config in `frontend/openapi-ts.config.ts`) consumes that JSON and
   generates three files into `frontend/src/client/`:
   - `types.gen.ts` — every request/response shape
   - `sdk.gen.ts` — one class per router tag, one static method per route
   - `client.gen.ts` — the configured HTTP client instance
4. Frontend code imports from `@/client` and never writes a manual `fetch`/`axios` call to the
   backend.

**Non-obvious but essential: this step is manual, not watched.** After changing a backend
route or model, you must re-run the generate script before the frontend sees the new shape.
Nothing regenerates automatically on file save. Put the exact command in the new project's
README/CLAUDE.md so this doesn't get forgotten:
```bash
./scripts/generate-client.sh
```
This is also the fastest way to catch a breaking backend change: regenerate, then `tsc`/build
the frontend — every call site using the old shape becomes a compile error immediately.

---

## 7. Testing conventions

- **Backend**: pytest, structure mirrors `app/`: `tests/api/routes/test_<resource>.py`,
  `tests/crud/test_<resource>.py`, plus `tests/utils/` for shared fixtures/factories and a
  `conftest.py` for pytest fixtures (test client, DB session).
- **Frontend**: Playwright for e2e (`frontend/tests/`), driving the real UI against a real
  (test) backend — not mocked API calls. Good for auth flows and critical paths; don't try to
  unit-test every component through it.

---

## 8. Single-deployable-unit build

The backend `Dockerfile` is a **two-stage build**: stage 1 builds the frontend
(`bun run build`), stage 2 copies the built static frontend into the Python image and FastAPI
serves it directly (`app.frontend("/", directory=FRONTEND_DIR)` — a StaticFiles-style mount).

Result: **one container image, one process, both frontend and API on the same origin.**
No CORS between them in production, no separate frontend hosting/CDN to manage. Keep this
pattern unless there's a specific reason to split them (e.g. a CDN-fronted frontend at scale) —
splitting adds a second deployable, a second set of environment variables, and a CORS
configuration surface for no benefit at typical scale.

---

## 9. Deploying to AWS

The repo's own reference deploy target is a single Docker host running `docker compose`
behind Traefik (see `compose.deploy.yml`) — fine for a VM, not what you want on AWS.
Translate the same shape into AWS-native pieces:

| Local/self-host piece | AWS equivalent |
|---|---|
| `docker build` (backend image) | Build in CI, push to **ECR** |
| `docker compose up` running the image | **ECS Fargate** service (or App Runner for the simplest path) running that ECR image |
| Traefik (reverse proxy + TLS) | **ALB** (Application Load Balancer) + **ACM** for TLS certs, targeting the ECS service |
| `db` container + volume | **RDS Postgres** — do not run Postgres in a container in prod; use the managed instance, point `DATABASE_URL` at its endpoint |
| `.env` file | **SSM Parameter Store** or **Secrets Manager** — inject as ECS task-definition secrets, never bake into the image |
| Mailpit (dev-only email catcher) | real SMTP provider (SES) in prod — Mailpit stays dev-only |
| Domain routing | **Route 53** → ALB, ACM cert validated via Route 53 |
| Adminer (dev DB browser) | drop in prod, or restrict to a bastion/VPN-only path |

**CI/CD shape to replicate** (this repo's `deploy-docker-compose.yml` is the template — same
idea, different target):
```
on: push to main (or workflow_dispatch)
  → build image
  → push to ECR
  → run migrations (one-off ECS task or `aws ecs run-task` invoking the same image with
     `alembic upgrade head` as the command)
  → update ECS service to the new image tag (aws ecs update-service --force-new-deployment,
     or a proper CD tool)
```
Keep the pattern of **running migrations as a separate step before the app starts serving**,
same as `backend_pre_start.py` does locally — don't let ECS roll a new task that queries a
schema that hasn't migrated yet.

**Secrets**: the config guard in §2 (`"changethis"` rejection) matters more here than
locally — make sure `SECRET_KEY`, `POSTGRES_PASSWORD`, `FIRST_SUPERUSER_PASSWORD` come from
Secrets Manager/SSM at deploy time, never committed, never left as the template defaults.

**What NOT to carry over**: FastAPI Cloud-specific deploy config, Traefik's Docker-label-based
routing (ALB uses target groups instead), and the self-hosted `compose.deploy.yml` overlay
itself — those are alternatives to, not components of, the AWS path.

---

## 10. Non-obvious gotchas to remember

- Regenerating the API client is a **manual step** (§6) — easy to forget, causes silent
  frontend/backend drift until a build breaks.
- `models.py` SQLModel classes are both DB schema and API schema — a change here is
  simultaneously a migration need (§3) *and* a client regen need (§6).
- The custom operation-ID function (§2) is small but load-bearing — losing it degrades every
  generated method name.
- The frontend is built *into* the backend image (§8) — there is no standalone "frontend
  container" in production; don't design AWS infra assuming two separate services.
- Migrations must run before the new app version starts serving traffic (§9) — sequence this
  explicitly in CI/CD, ECS won't do it for you.
- Config validation happens at process startup (`Settings()` instantiation) — a bad/missing
  env var is a fast, loud crash on boot, not a mysterious 500 later. Keep that property.
