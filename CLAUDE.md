# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync                          # install deps (Python >=3.14, uv-managed .venv)
docker compose up -d             # Weaviate + GPU transformers sidecar (needed by vectorize.py)
uv run src/preprocess.py         # download + parse dataset -> data/parsed-recipes (gitignored)
uv run src/vectorize.py          # (re)create the Recipes collection and load 522k objects
uv run pytest                    # all tests
uv run pytest tests/test_vectorize.py::test_config_property_types   # single test
```

`pythonpath = ["src"]` in [pyproject.toml](pyproject.toml) is what lets tests do `import preprocess` / `import vectorize`.

`tqdm` and `httpx` are imported by [src/vectorize.py](src/vectorize.py) and [tests/test_vectorize.py](tests/test_vectorize.py) but only arrive transitively via `datasets`/`weaviate-client` — declare them if either upstream drops them.

## Architecture

Two-stage offline pipeline; nothing runs at request time yet (the API is Phase 2 in the [README](README.md) roadmap).

1. **[src/preprocess.py](src/preprocess.py)** — pulls `untitledwebsite123/food-recipes` from HF and normalizes the columns the dataset stores as *R source text*: `c("flour", "sugar")` vectors via `parse()`, ISO-8601 durations (`PT24H45M`, and a few corrupted `PT-30M`) via `parse_duration()`. Both fail-soft vs. fail-loud deliberately — `parse()` returns unparseable text as-is, `parse_duration()` raises. Output is saved with `save_to_disk` to `data/parsed-recipes`.
2. **[src/vectorize.py](src/vectorize.py)** — drops and rebuilds the `Recipes` collection, then batch-loads it. Embedding happens *server-side* in Weaviate's `text2vec-transformers` module (BAAI/bge-small-en-v1.5, 384-dim), never on the client, so index-time and query-time embeddings can't drift.

### The schema/mapping invariant

Three things must agree, and Weaviate's auto-schema will silently store un-vectorized objects if they don't (this actually happened — every insert "succeeded", every search returned empty):

- `config()`'s `vec_fields` ⊆ `config()`'s `properties` — asserted inside `config()`.
- `to_props()`'s keys == `properties` names — asserted in `main()` against row 0, and offline in `test_to_props_keys_match_schema_exactly`.

**Adding or renaming a field means touching `to_props()`, `properties`, and `test_config_property_types` together.** Case matters: the original bug was a capitalization mismatch between `source_properties` and the schema.

### Conventions that carry meaning

- `None` is never defaulted to `0` for numbers or durations — an unrated recipe stays unrated, a missing cook time is not "instant". Text fields *are* defaulted to `""` so inserts don't blow up.
- `to_props()` blanks any description containing `food.com`: ~196k rows are the same *"Make and share this <Name> recipe from Food.com"* boilerplate, which would pull unrelated recipes together in vector space. The row stays searchable; only the field is emptied.
- UUIDs are `generate_uuid5(RecipeId)`, so a reload is idempotent per recipe.

## Tests

Offline only — `main()` in both modules is left to integration testing. Tests document *why* each behavior exists (including known-and-accepted false positives, e.g. the `\bNA\b` substitution: 298,703 genuine hits vs. 1 bad one). Keep that style: when you change a parsing rule, update the docstring's reasoning, not just the assertion.
