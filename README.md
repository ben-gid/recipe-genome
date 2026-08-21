# recipe-genome

RAG over 522,517 recipes with hybrid search: semantic similarity plus structured filters (dietary keywords, cook time, calories, ingredients on hand). A React faceted-search UI on top, and an agent that plans a week of meals against constraints it can actually verify.

**Stack:** Weaviate · FastAPI · React + Vite · Claude · AWS (deploy target)

## Status

**Built** — the offline pipeline. 522k recipes parsed, cleaned, embedded, and queryable in Weaviate, with 94 tests over the parsing rules.

**In progress** — the search API. FastAPI app, hybrid query, and range filters exist; the eval harness that decides how retrieval gets tuned does not.

**Not started** — the React UI, the agent loop, the deploy.

[ROADMAP.md](ROADMAP.md) has the phase-by-phase detail and the acceptance criteria for each.

## Design philosophy

Three ideas drive most of the decisions in this repo.

**Embedding-time correctness is worth more than query-time cleverness.** A bad vector cannot be rescued by a better search. Most of the effort so far has gone into what goes *into* the index — auditing the text, blanking the noise, asserting the schema agrees with the mapping — rather than into tuning what comes out.

**Measure before adding a component.** A reranker, a bigger embedding model, a query rewriter: each is a plausible improvement and none of them ship before an eval harness says the current setup falls short. The alternative is a pipeline of parts nobody can justify removing.

**An agent's output is only as trustworthy as its verifier.** The meal planner in Phase 4 is not the hard part — a model will happily produce seven days of dinners. The hard part is `check_plan`, the typed checker that decides whether those dinners actually fit under the calorie ceiling and avoid the allergens. The plan is a suggestion; the checker is the product.

## How it fits together

Two independent projects and a database, with no shared code between them.

```
src/          Offline pipeline — runs on demand, never at request time
  preprocess.py   HF dataset -> parsed columns -> data/parsed-recipes
  vectorize.py    parsed recipes -> the Recipes collection in Weaviate
backend/      Search API — its own pyproject.toml, its own venv
  app/api/        FastAPI app, routes, and the Weaviate query layer
  app/models.py   request/response schemas
tests/        Pipeline tests (the backend has its own tests/)
docker-compose.yaml   Weaviate + the GPU embedding sidecar
```

`src/` and `backend/` never import each other. The pipeline's job ends when the data is in Weaviate; the API's job starts there, and it reaches the database over the network like any other client. That boundary is what lets a 522k-row reload happen without touching the API, and the API deploy happen without carrying `datasets` and its dependency tree into the image.

The one thing that crosses the boundary is the schema, and it crosses implicitly — the property names `vectorize.py` writes are the names `backend/` reads. Nothing enforces that agreement, which is exactly why it's written down in [CLAUDE.md](CLAUDE.md#the-schemamapping-invariant).

## Design notes

**Cleaning up the descriptions before embedding them.** When I audited the 522,517 recipes in the Food.com dataset, I found that a little over a third of the `Description` field was boilerplate — the same *"Make and share this &lt;Name&gt; recipe from Food.com"* stamped across roughly 196,000 recipes, with no content beyond the recipe name Weaviate was already storing separately. Embedding that text wouldn't teach the model anything; it would just drag ~196k unrelated recipes toward each other in vector space because they happen to share a template sentence. The other 62.7% of the field is real, human-written description — a median of 37 words, and by far the richest signal in the dataset for the things an ingredient list can't capture: how a dish is meant to feel, when you'd make it, what effort it takes. Rather than drop the field or throw out the affected recipes, I blank the boilerplate per row at insert time. Every recipe stays searchable; none of them carry noise into the embedding space.

**Keeping the embeddings honest.** Vectorization happens inside Weaviate itself, through its `text2vec-transformers` module (BAAI/bge-small-en-v1.5, 384 dimensions, running in a GPU-backed sidecar container) rather than on the client. That means the same model embeds a recipe at index time and a query at search time, so the two can never quietly drift apart — a real risk once more than one thing talks to the database and each has to load and agree on a model on its own.

I found this out the hard way. An early load run inserted every object and reported zero failures, and then every single search came back empty. The cause was a capitalization mismatch between `source_properties` and the schema I'd declared — Weaviate's auto-schema swallowed it silently and stored the records with no vectors at all. There's now a startup assertion that checks the vectorized fields, the schema, and the row mapping all agree before a load is allowed to start.

**Starting with hybrid, not a reranker.** For search itself, I'm starting with Weaviate's built-in hybrid (BM25 + vector) instead of adding a reranker. Keyword matching genuinely matters here — ingredient names are exactly the kind of thing embeddings blur together — and hybrid costs nothing extra to run. A reranker goes in later if the eval numbers say I need one, not before.

**Failing loud where a wrong answer is worse than no answer.** The two parsers in `preprocess.py` handle bad input differently on purpose. `parse()` returns unparseable text as-is: a weird ingredient string is still worth indexing. `parse_duration()` raises: a cook time that parses to the wrong number would silently corrupt every time-based filter downstream, and a crash during preprocessing is far cheaper than that. The same instinct shows up in how `None` is treated — an unrated recipe stays unrated, and a missing cook time is never quietly rounded to "instant."

## Quick start

Needs [uv](https://docs.astral.sh/uv/), Docker, and an NVIDIA GPU for the embedding sidecar.

```bash
uv sync                  # pipeline deps
docker compose up -d     # Weaviate + the GPU transformers sidecar
uv run src/preprocess.py # download and parse the dataset (~10 min)
uv run src/vectorize.py  # build the schema and load 522k objects (slow — GPU-bound)
uv run pytest            # pipeline tests

uv sync --project backend                                  # API deps, separate venv
uv run --project backend uvicorn app.api.main:app --reload # the search API
```

## Where things are written down

- **[ROADMAP.md](ROADMAP.md)** — what's next, in build order, with acceptance criteria per phase.
- **[CLAUDE.md](CLAUDE.md)** — the working notes: invariants, gotchas, and the conventions that carry meaning. Written for Claude Code, useful to anyone editing the code.
- **[structure.md](structure.md)** — the generic FastAPI + React layout this project follows, distilled from the official full-stack template.
