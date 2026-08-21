# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync                          # install pipeline deps (Python >=3.14, uv-managed .venv)
docker compose up -d             # Weaviate + GPU transformers sidecar (needed by vectorize.py and the API)
uv run src/preprocess.py         # download + parse dataset -> data/parsed-recipes (gitignored)
uv run src/vectorize.py          # (re)create the Recipes collection and load 522k objects
uv run pytest                    # all pipeline tests
uv run pytest tests/test_vectorize.py::test_config_property_types   # single test

uv sync --project backend                                    # install API deps, separate venv
uv run --project backend uvicorn app.api.main:app --reload    # run the search API
uv run --project backend pytest                                # backend tests
```

`pythonpath = ["src"]` in [pyproject.toml](pyproject.toml) is what lets tests do `import preprocess` / `import vectorize`. [backend/pyproject.toml](backend/pyproject.toml) sets `pythonpath = ["."]` the same way, so `backend/` tests can `import app.api.main` etc.

`tqdm` and `httpx` are imported by [src/vectorize.py](src/vectorize.py) and [tests/test_vectorize.py](tests/test_vectorize.py) but only arrive transitively via `datasets`/`weaviate-client` — declare them if either upstream drops them.

## Architecture

Two independent projects, each with its own `pyproject.toml`/venv — see [README §How it fits together](README.md#how-it-fits-together) for the full layout and rationale. Neither imports the other; `backend/` only reaches Weaviate over the network.

**1. Offline pipeline (root project, `src/`)** — nothing here runs at request time.

- **[src/preprocess.py](src/preprocess.py)** — pulls `untitledwebsite123/food-recipes` from HF and normalizes the columns the dataset stores as *R source text*: `c("flour", "sugar")` vectors via `parse()`, ISO-8601 durations (`PT24H45M`, and a few corrupted `PT-30M`) via `parse_duration()`. Both fail-soft vs. fail-loud deliberately — `parse()` returns unparseable text as-is, `parse_duration()` raises. Output is saved with `save_to_disk` to `data/parsed-recipes`.
- **[src/vectorize.py](src/vectorize.py)** — drops and rebuilds the `Recipes` collection, then batch-loads it. Embedding happens *server-side* in Weaviate's `text2vec-transformers` module (BAAI/bge-small-en-v1.5, 384-dim), never on the client, so index-time and query-time embeddings can't drift.

**2. Search API (`backend/`, [Phase 2](ROADMAP.md#phase-2--search-api-and-retrieval-evaluation) — in progress)**

- **[backend/app/api/main.py](backend/app/api/main.py)** — `FastAPI()` instantiation, the lifespan that opens/closes the Weaviate client, the operation-id function (carried over from [structure.md](structure.md), keeps generated frontend client method names clean), router mounts. There is no `app/main.py`.
- **[backend/app/core/config.py](backend/app/core/config.py)** — `AppSettings(BaseSettings)`, env-driven, plus a module-level `state` singleton the routes import directly (no `Depends()` needed yet — nothing per-request to inject).
- **[backend/app/api/search.py](backend/app/api/search.py)** — the hybrid query and `_build_filters()`. Stays FastAPI-free: `HTTPException` lives in the route, not here.
- **[backend/app/models.py](backend/app/models.py)** / **[backend/app/api/routes/recipes.py](backend/app/api/routes/recipes.py)** — the `/search` schema and handler. Both import cleanly now, but `recipes.router` is still not mounted in `api/main.py` — searching requires wiring that up.

Imports inside `backend/` are absolute (`from app.core.config import ...`). Relative ones broke when `routes/` moved under `api/`, since `..` now resolves to `app.api`.

### Deviations from structure.md

[structure.md](structure.md) is the generic pattern reference; this project follows it except where noted —
don't re-derive the parts that carry over unchanged (§1 repo layout, §2's operation-ID function, §5 env
overlay pattern, §6 codegen loop, §8 single-deployable-unit build), read structure.md directly for those.

- **§2/§3 (SQLModel, `crud.py`, Alembic, auth) — none of it applies.** Weaviate is the only datastore and its
  schema is owned by [src/vectorize.py](src/vectorize.py), not this API — there's no relational schema to put
  in `models.py` or migrate. Nothing on the roadmap needs a user yet, so no `core/security.py`/JWT/`deps.py`.
  `search.py` is this project's `crud.py` — Weaviate query functions, called by thin route handlers.
- **§2's `app/main.py` + `app/api/main.py` split — collapsed into one file.** Two routers total, so
  `app/api/main.py` is both the `FastAPI()` instantiation and the mount point. Split them if the router
  count grows enough to make it noisy.
- **§4 (frontend, Phase 3) — drop the auth split.** Keep TanStack Query / `react-hook-form`+`zod` / Tailwind
  conventions; no `routes/_layout.tsx` authenticated-shell split, no `useAuth.ts` — there's no login to gate.
- **§9 (AWS deploy, Phase 6) — swap the RDS row for Weaviate.** No managed vector DB fits ECS Fargate cheaply
  with a GPU `text2vec-transformers` sidecar attached — either self-host on a GPU EC2 instance (same
  `docker-compose.yaml` as local dev) or move to Weaviate Cloud (WCS) and drop self-hosting it entirely. Also
  drop the Mailpit/Adminer rows — no email, no relational DB to browse.

### The schema/mapping invariant

Three things must agree, and Weaviate's auto-schema will silently store un-vectorized objects if they don't (this actually happened — every insert "succeeded", every search returned empty):

- `config()`'s `vec_fields` ⊆ `config()`'s `properties` — asserted inside `config()`.
- `to_props()`'s keys == `properties` names — asserted in `main()` against row 0, and offline in `test_to_props_keys_match_schema_exactly`.
- `RecipeProps`'s keys ⊆ `properties` names — **not asserted anywhere**, because `backend/` can't import `src/`. A typo here fails at request time, not at load time.

**Adding or renaming a field means touching `to_props()`, `properties`, and `test_config_property_types` together** — plus `RecipeProps` if the field is one `/search` returns. Case matters: the original bug was a capitalization mismatch between `source_properties` and the schema.

### Weaviate client gotchas (backend)

- **Typed properties must be a `TypedDict`, not a dataclass.** `collections.get("Recipes", RecipeProps)`
  raises `WeaviateInvalidInputError` for anything else. The TypedDict does double duty: it propagates the
  generic *and* acts as the `return_properties` selector, so `ingredients`/`keywords`/`description` stop
  crossing the wire without a second field list to keep in sync.
- **`obj.properties` is a `Mapping` at runtime even when typed.** The TypedDict is static typing only —
  `obj.properties["name"]`, never `obj.properties.name`.
- **`use_async_with_local()` is sync and returns an *unconnected* client.** Awaiting it is a type error;
  the awaitable is `await client.connect()`. `AppState.load`/`clear` own connect and close, driven by the
  lifespan — a client that is merely non-`None` is not necessarily usable.

### Conventions that carry meaning

- `None` is never defaulted to `0` for numbers or durations — an unrated recipe stays unrated, a missing cook time is not "instant". Text fields *are* defaulted to `""` so inserts don't blow up.
- `to_props()` blanks any description containing `food.com`: ~196k rows are the same *"Make and share this <Name> recipe from Food.com"* boilerplate, which would pull unrelated recipes together in vector space. The row stays searchable; only the field is emptied.
- UUIDs are `generate_uuid5(RecipeId)`, so a reload is idempotent per recipe.

## Tests

Offline only — `main()` in both modules is left to integration testing. Tests document *why* each behavior exists (including known-and-accepted false positives, e.g. the `\bNA\b` substitution: 298,703 genuine hits vs. 1 bad one). Keep that style: when you change a parsing rule, update the docstring's reasoning, not just the assertion.
