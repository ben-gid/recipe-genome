# recipe-genome
RAG over a recipe dataset with hybrid search: semantic + structured filters (dietary restrictions, cook time, ingredients-on-hand). React frontend with faceted search UI.

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
module (all-MiniLM-L6-v2, 384-dim, GPU-backed sidecar container) embeds at both index and query
time, so the two can't silently diverge — a real risk when every consumer of the DB has to load
and agree on a model itself. This choice was validated the hard way: an early run inserted all
objects successfully and reported zero failures, yet every search returned empty. The cause was a
capitalization mismatch between `source_properties` and the declared schema, which Weaviate's
auto-schema accepts silently, storing records with no vectors at all. Startup assertions now
verify that the vectorized fields, the schema, and the row mapping all agree before a load begins.
Search itself starts with built-in hybrid (BM25 + vector) rather than a reranker — keyword matching
genuinely matters for ingredient names, and it costs no extra infrastructure until measurement
says otherwise.
