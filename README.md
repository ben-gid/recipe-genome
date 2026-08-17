# recipe-genome
RAG over a recipe dataset with hybrid search: semantic + structured filters (dietary restrictions, cook time, ingredients-on-hand). React frontend with faceted search UI.

**Stack:** Weaviate · FastAPI · React + Vite · Claude

## Design notes

**Embedding quality is a data problem before it's a model problem.** Auditing the 522,517-recipe
Food.com dataset showed that 37.5% of `Description` values are templated boilerplate — *"Make and
share this &lt;Name&gt; recipe from Food.com."* — whose only real content is the recipe name, already
stored separately. Embedding it would have pulled ~196k unrelated recipes toward each other in
vector space. The remaining 62.7% are genuine, human-written, and median 37 words: the richest
semantic signal available, capturing effort, occasion, and texture that ingredient lists can't.
Rather than drop the field or delete the affected recipes, boilerplate is blanked per row at insert
time — every recipe stays searchable, no recipe carries noise.

**Vectorization runs inside the database, not the client.** Weaviate's `text2vec-transformers`
module (BAAI/bge-small-en-v1.5, 384-dim, GPU-backed sidecar container) embeds at both index and query
time, so the two can't silently diverge — a real risk when every consumer of the DB has to load
and agree on a model itself. This choice was validated the hard way: an early run inserted all
objects successfully and reported zero failures, yet every search returned empty. The cause was a
capitalization mismatch between `source_properties` and the declared schema, which Weaviate's
auto-schema accepts silently, storing records with no vectors at all. Startup assertions now
verify that the vectorized fields, the schema, and the row mapping all agree before a load begins.
Search itself starts with built-in hybrid (BM25 + vector) rather than a reranker — keyword matching
genuinely matters for ingredient names, and it costs no extra infrastructure until measurement
says otherwise.

## Roadmap

Retrieval is built; everything below is planned. Phase 1 is the credential that separates a RAG
project from a RAG demo, Phase 3 is the reason an agent exists here at all, and Phases 2 and 4 are
where it becomes a product someone can use.

### Phase 1 — Search API and retrieval evaluation

- **`/search` endpoint** (FastAPI): free-text query plus structured filters — calories, protein,
  rating floor, cook time, and ingredient include/exclude. A thin wrapper over the hybrid query
  the collection already supports.
- **Cook-time filter, end to end.** The source data stores times as ISO-8601 durations (`PT45M`,
  `PT24H45M`). A scan of all 522,517 rows found only five distinct shapes and no day components,
  so one regex covers the corpus; the three malformed negative values (`PT-30M`) fall into the same
  path as missing data rather than earning a special case. Only `TotalTime` gets exposed — it is
  what "ready in 30 minutes" actually means, and it is populated on every row but one, where
  `CookTime` is missing on 15.8%. Parsing lives beside the existing R-list parser rather than
  inside it, since a duration returns a scalar and the list parser's contract is a list.
- **Evaluation harness — known-item retrieval, no manual labeling.** Hold out a sample of recipes,
  use each one's human-written description as the query, and measure whether that specific recipe
  comes back. Report **recall@10 and MRR** across BM25 only, vector only, hybrid across a sweep of
  alpha values, and hybrid plus a reranker.
- **Publish the numbers here.** A measured comparison is worth more than any claim about the
  retrieval design, and it turns the reranker question into a decision with evidence behind it.

### Phase 2 — Faceted search UI

- React + TypeScript on Vite.
- Facets for dietary keywords, calorie and protein ranges, rating floor, cook time, and
  ingredients-on-hand as removable chips.
- Filter state synced to the URL, so a search is shareable and the back button behaves.
- Debounced querying, virtualized results, and a recipe detail view with ingredients,
  instructions, and nutrition.

### Phase 3 — Meal-planning agent

Single-shot retrieval answers "find me a chicken recipe." It cannot answer:

> *Five dinners under 600 calories that use up the cilantro and chicken I already have, no shellfish.*

That needs repeated searching, arithmetic across the whole candidate set, and backtracking when a
constraint fails — so the agent is here because the task requires one, not as decoration.

- **A hand-rolled tool loop** on the Anthropic SDK, no orchestration framework: call the model,
  inspect `stop_reason`, execute any requested tools, append the results, repeat until it stops.
  The loop is the thing being demonstrated, so it stays legible rather than delegated.
- **Two tools, not ten.**
  - `search_recipes(...)` — Phase 1's search, returning a compact projection rather than full
    recipe bodies. A dozen searches of untrimmed results would exhaust the context on its own.
  - `check_plan(...)` — per-day and total nutrition, pantry coverage, ingredients used only once,
    and allergen violations, returned as structured failures for the agent to repair.
- **The verifier is deterministic Python, not a second model.** Calorie totals and allergen
  matching are arithmetic and set membership; a language model checking them would be slower,
  costlier, and less trustworthy on exactly the question where being wrong matters most. The agent
  searches and repairs; the code rules on facts.
- Bounded by a hard iteration cap and a per-request tool-call budget, with tool failures returned
  as errors the agent can recover from instead of stalling.
- **Scenario tests** asserting that returned plans actually satisfy their constraints — under the
  calorie ceiling, zero allergen violations, pantry coverage above threshold. Results published
  here alongside the retrieval numbers.

### Phase 4 — Live agent trace

- The planning endpoint streams Server-Sent Events; the browser consumes them with native
  `EventSource`.
- Each search the agent runs, each constraint check, and each backtrack renders as it happens,
  followed by the finished week.
- Watching the agent work is both the clearest explanation of what it does and the most
  interesting frontend problem in the project.

### Phase 5 — Deploy and operate

- `docker compose up` brings up Weaviate, the embedding sidecar, the API, and the UI.
- Per-IP rate limiting and a hard spend cap — a public endpoint that costs money per visitor needs
  both before it goes live.
- Typed API contract shared with the frontend, generated from OpenAPI.
- Resumable indexing, so a half-million-row load survives an interruption.
- CI running tests and lint on push.

### Later

Accounts and saved meal plans — a natural extension once the planner is worth returning to, but
not part of the work above.
