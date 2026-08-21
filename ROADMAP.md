# Roadmap

The build order, and why each piece is sequenced where it is. [README](README.md) covers the architecture and the reasoning behind the design.

Backend and frontend follow [structure.md](structure.md)'s layout — each its own project, wired only by Docker Compose and a generated OpenAPI client. Where this project deviates from that pattern (no ORM, no auth, Weaviate instead of RDS), the reasoning lives in [CLAUDE.md](CLAUDE.md#deviations-from-structuremd).

---

## Phase 1 — Pick and vectorize a dataset

- [x] **Pick a dataset** — `untitledwebsite123/food-recipes` on Hugging Face. 522,517 recipes with nutrition, timings, ratings, and free-text descriptions. The nutrition columns are what make structured filtering worth building; most recipe datasets don't carry them.
- [x] **Audit it** — a little over a third of the `Description` field is one repeated template sentence. That finding drives the blanking rule (see [README § Design notes](README.md#design-notes)).
- [x] **Preprocess** — the dataset stores several columns as *R source text*: `c("flour", "sugar")` for lists, ISO-8601 strings for durations. `parse()` turns the former into Python lists, `parse_duration()` the latter into `timedelta`s. The two fail differently on purpose: `parse()` returns unparseable text as-is (a weird ingredient string is still searchable), `parse_duration()` raises (a silently wrong cook time would corrupt a filter).
- [x] **Vectorize** — build the schema, load all 522k objects through `text2vec-transformers`, assert the schema/mapping invariant before the load is allowed to start.
- [x] **Test the parsing rules** — tests over `preprocess.py` and `vectorize.py` that document *why* each rule exists rather than just asserting the output.

**Deliberately out of scope here:** resumable indexing. A full load is a single long run; if it dies at 400k, it restarts from zero. UUIDs are `generate_uuid5(RecipeId)`, so a reload is idempotent per recipe and re-running is safe — just slow. Phase 6 fixes it.

---

## Phase 2 — Search API and retrieval evaluation

- [x] **Stand up the FastAPI app** — lifespan-managed Weaviate client, `/health` reporting client state.
- [x] **Write the hybrid query and filter builder** — `search.py` stays FastAPI-free; `HTTPException` lives in the route.
- [x] **Mount the `/search` router.**
- [ ] **Finish the filter surface** — calories, protein, rating floor, cook time, and ingredients-on-hand. The last one is the interesting one: it's a set-overlap question, not a range, so it needs `ContainsAny` over the `ingredients` array rather than a numeric comparison.
- [ ] **Decide what a filtered-out `None` means.** A recipe with no rating is excluded by a `rating >= 4` filter, because Weaviate won't match a missing property. That's correct for rating and wrong for cook time — "no cook time recorded" is not "takes forever." Needs a deliberate answer per field, not a default.
- [ ] **Build a retrieval eval harness** — hold out a sample of recipes, query with each one's own description, check whether it comes back. Report recall@10 and MRR. This is the gate for every retrieval decision that follows; without numbers, tuning alpha is guesswork.
- [ ] **Compare BM25-only, vector-only, hybrid across alpha values, and hybrid + reranker.** Publish the numbers in the README. `alpha=0.75` is an inherited default, not a measured choice.
- [ ] **Decide on the reranker from the evidence.** If hybrid alone hits the recall target, no reranker ships.

**Acceptance:** `/search` returns ranked, filtered results against the live 522k collection, and the eval harness produces a recall@10 number for at least three retrieval configurations.

---

## Phase 3 — React UI

- [ ] **Scaffold `frontend/`** — React + TypeScript on Vite, own `package.json`, [structure.md §4](structure.md)'s layout: file-based TanStack Router, feature-grouped `components/`, vendored shadcn/ui. Minus the auth split — no `routes/_layout.tsx`, no `useAuth.ts`, everything is public.
- [ ] **Wire the OpenAPI codegen loop** ([structure.md §6](structure.md)) — generate `frontend/src/client/` from the backend schema. The step is manual and easy to forget: re-run it after every route or model change, and let `tsc` catch the call sites that broke.
- [ ] **Build the faceted search UI** — dietary keywords, calorie and protein ranges, rating floor, cook time, and ingredients-on-hand as removable chips.
- [ ] **Sync filter state to the URL** so a search is shareable and back/forward behaves.
- [ ] **Add a recipe detail view** — ingredients, instructions, nutrition.

**Acceptance:** a search with three filters applied can be shared as a URL that reproduces the same result set.

---

## Phase 4 — Agent loop with typed verification

The point of this phase: an LLM that plans a week of meals is easy to demo and hard to trust. Verification is what separates the two.

- [ ] **Hand-roll the tool loop against the Anthropic SDK** — call the model, check `stop_reason`, run the tools it asked for, feed results back, repeat. No orchestration framework; the loop is thirty lines and owning it means being able to debug it.
- [ ] **Give it two tools** — `search_recipes` (wraps Phase 2's search) and `check_plan` (checks a candidate week against calorie targets, pantry coverage, and allergens).
- [ ] **Validate tool inputs and outputs with Pydantic**, so a malformed call fails fast instead of quietly confusing the model.
- [ ] **Bound the loop** — hard iteration cap, tool-call budget, and failures returned as recoverable tool errors rather than exceptions that kill the request.
- [ ] **Write scenario tests that assert the returned plan satisfies its constraints** — under the calorie ceiling, no allergen violations, pantry coverage above a threshold. This is the phase's real deliverable: the checker, not the planner.

**Acceptance:** a scenario test suite where every passing plan is provably within its stated constraints.

---

## Phase 5 — Live agent trace

- [ ] **Stream the planning endpoint as Server-Sent Events.**
- [ ] **Consume it with `EventSource`** — the browser already does this; no library needed.
- [ ] **Render each search, each check, and each backtrack as it happens**, ending on the finished week. The backtracks are the interesting part — a plan that failed `check_plan` and got revised is the visible proof the verification loop is real.

---

## Phase 6 — Deploy

- [ ] **Two-stage `backend/Dockerfile`** ([structure.md §8](structure.md)) — stage 1 builds the frontend, stage 2 copies the static output into the Python image and FastAPI serves it. One container, one process, no CORS in prod.
- [ ] **One-shot `docker compose up`** bringing up Weaviate, the embedding sidecar, the API, and the UI.
- [ ] **Per-IP rate limiting and a hard spend cap** before anything is public. The agent loop calls a paid API in a loop; this is not optional.
- [ ] **Make indexing resumable** so a 522k-row load survives an interruption.
- [ ] **CI** — tests and lint on every push.
- [ ] **Decide where Weaviate lives.** This is the one real deviation from structure.md's deploy table: Weaviate is not RDS. No managed vector DB fits Fargate cheaply with a GPU `text2vec-transformers` sidecar attached, so the choice is self-hosting on a GPU EC2 instance (the same `docker-compose.yaml` as local dev) or moving to Weaviate Cloud and dropping self-hosting entirely.
- [ ] **Deploy to AWS** ([structure.md §9](structure.md)) — ECS Fargate or App Runner behind ALB/ACM, secrets via SSM or Secrets Manager, Route 53 for the domain.

---

## Later

Accounts and saved meal plans. Worth building once the planner is good enough to come back to — which is a Phase 4 question, not a Phase 2 one. Adding auth earlier means carrying `core/security.py`, JWT handling, and a user store through four phases that don't need them.
