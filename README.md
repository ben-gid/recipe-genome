# recipe-genome

RAG over a recipe dataset with hybrid search: semantic + structured filters (dietary restrictions, cook time, ingredients-on-hand). React frontend with faceted search UI.

**Stack:** Weaviate · FastAPI · React + Vite · Claude

## Design notes

**Cleaning up the descriptions before embedding them.** When I audited the 522,517 recipes in the Food.com dataset, I found that a little over a third of the `Description` field was boilerplate — the same *"Make and share this &lt;Name&gt; recipe from Food.com"* stamped across roughly 196,000 recipes, with no content beyond the recipe name Weaviate was already storing separately. Embedding that text wouldn't teach the model anything; it would just drag ~196k unrelated recipes toward each other in vector space because they happen to share a template sentence. The other 62.7% of the field is real, human-written description — a median of 37 words, and by far the richest signal in the dataset for the things an ingredient list can't capture: how a dish is meant to feel, when you'd make it, what effort it takes. Rather than drop the field or throw out the affected recipes, I blank the boilerplate per row at insert time. Every recipe stays searchable; none of them carry noise into the embedding space.

**Keeping the embeddings honest.** Vectorization happens inside Weaviate itself, through its `text2vec-transformers` module (BAAI/bge-small-en-v1.5, 384 dimensions, running in a GPU-backed sidecar container) rather than on the client. That means the same model embeds a recipe at index time and a query at search time, so the two can never quietly drift apart — a real risk once more than one thing talks to the database and each has to load and agree on a model on its own.

I found this out the hard way. An early load run inserted every object and reported zero failures, and then every single search came back empty. The cause was a capitalization mismatch between `source_properties` and the schema I'd declared — Weaviate's auto-schema swallowed it silently and stored the records with no vectors at all. There's now a startup assertion that checks the vectorized fields, the schema, and the row mapping all agree before a load is allowed to start.

For search itself, I'm starting with Weaviate's built-in hybrid (BM25 + vector) instead of adding a reranker. Keyword matching genuinely matters here — ingredient names are exactly the kind of thing embeddings can blur together — and hybrid costs nothing extra to run. A reranker goes in later if the eval numbers say I need one, not before.

## Roadmap

The dataset is picked, cleaned, and searchable — Phase 1 is done. Everything after that is what's left, roughly in the order I plan to build it.

### Phase 1 — Pick and vectorize a dataset ✅

- [x] Pick a dataset — went with `untitledwebsite123/food-recipes` on Hugging Face, 522,517 recipes.
- [x] Understand it — audited the `Description` field and found over a third was boilerplate (see Design notes above).
- [x] Preprocess — parse the R-style list columns (ingredients, keywords, instructions) into real Python lists, parse ISO-8601 durations (cook/prep/total time) into `timedelta`s, blank the boilerplate descriptions.
- [x] Vectorize — build the Weaviate schema, load all 522k recipes through the `text2vec-transformers` service, and confirm hybrid queries return real hits against it, with tests covering the schema and load.

### Phase 2 — Search API and retrieval evaluation

- [ ] Build a `/search` endpoint in FastAPI — free-text query plus filters for calories, protein, rating floor, and ingredients on hand.
- [ ] Add a cook-time filter — `preprocess.py` already parses the ISO-8601 durations (`PT45M`, `PT24H45M`) into `timedelta`s; expose `total_time` as a filter on the `/search` endpoint.
- [ ] Build a retrieval eval harness — hold out a sample of recipes, query with each one's own description, and check whether it comes back. Report recall@10 and MRR.
- [ ] Compare BM25-only, vector-only, hybrid at a few alpha values, and hybrid plus a reranker — publish the numbers here and decide on the reranker from evidence, not guesswork.

### Phase 3 — React UI

- [ ] Set up React + TypeScript on Vite.
- [ ] Build the faceted search UI — dietary keywords, calorie/protein ranges, rating floor, cook time, and ingredients-on-hand as removable chips.
- [ ] Sync filter state to the URL so a search is shareable and back/forward actually works.
- [ ] Add a recipe detail view — ingredients, instructions, nutrition.

### Phase 4 — Agent loop with typed verification

- [ ] Write a hand-rolled tool loop against the Anthropic SDK — no orchestration framework, just call the model, check `stop_reason`, run whatever tools it asked for, feed the results back, repeat.
- [ ] Give it two tools: `search_recipes` (wraps Phase 2's search) and `check_plan` (checks a candidate week against calorie targets, pantry coverage, and allergens).
- [ ] Use Pydantic models to validate tool inputs and outputs, so a malformed call fails fast instead of quietly confusing the model.
- [ ] Bound the loop — a hard iteration cap, a tool-call budget, and failures returned as recoverable tool errors instead of crashes.
- [ ] Write scenario tests that assert a returned plan actually satisfies its constraints — under the calorie ceiling, no allergen violations, pantry coverage above some threshold.

### Phase 5 — Live agent trace

- [ ] Stream the planning endpoint as Server-Sent Events.
- [ ] Consume the stream in the browser with `EventSource` — no extra library needed.
- [ ] Render each search, each check, and each backtrack as it happens, ending on the finished week.

### Phase 6 — Deploy

- [ ] Get `docker compose up` to bring up Weaviate, the embedding sidecar, the API, and the UI in one shot.
- [ ] Add per-IP rate limiting and a hard spend cap before this goes anywhere public.
- [ ] Share a typed API contract with the frontend, generated from OpenAPI.
- [ ] Make indexing resumable, so a 522k-row load can survive getting interrupted partway through.
- [ ] Set up CI — tests and lint on every push.

### Later

Accounts and saved meal plans — a nice next step once the planner's worth coming back to, but not something I'm building yet.
