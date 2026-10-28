# Configuration and research workflow

## Local settings

Run commands from the repository root. The CLI and API read `.env` from the current
working directory; explicitly exported environment variables take precedence.
Use `.env.example` for Python or `.env.compose.example` for Docker Compose.
Do not mix the Python database URL with Docker-internal service names.

| Setting | Default / purpose |
| --- | --- |
| `FIG_DATABASE_URL` | `sqlite:///data/fixture.sqlite3`; use a PostgreSQL URL for integration |
| `FIG_ARCHIVE_DIR` | `data/archive`; retain alongside the database |
| `SEC_USER_AGENT` | Empty; set application name and real contact before ingestion |
| `FIG_SEC_CACHE_DIR` | `data/sec-cache`; coordinates local SEC request limits |
| `OPENAI_API_KEY`, `FIG_LLM_MODEL` | Both required only for explicitly selected model extraction |
| `FIG_NEO4J_URI`, `FIG_NEO4J_USER`, `FIG_NEO4J_PASSWORD` | Used by `fig project` |

No model is selected or called automatically. The browser reads only a boolean
configuration status from `/v1/extraction/configuration`, never secret values.
Optional embedding reranking is available through the API with `use_embeddings=true`;
it requires model credentials and can incur provider charges.

## Workflow

1. Run `fig migrate` and `fig demo`, or ingest a bounded SEC filing set with the CLI.
2. Refresh the workspace. Demo-only installations automatically display fictional
   companies; once real companies exist, synthetic data is opt-in.
3. Choose a company and explore accepted relationships or paths of one to three hops.
4. Ask a supported question naming registered companies. The deterministic planner
   returns evidence, its bounded plan, and limitations; it is not an unrestricted chatbot.
5. Search a filing, then inspect its exact passage and original source link.
6. Find candidates with the rule extractor or explicitly selected model extractor.
   Inspect direction, identity, and the quote; provide a reviewer identity to accept
   or reject. Only acceptance adds an eligible claim to the graph.
7. Run `fig project` after claim changes if you use Neo4j.

`fig seed-fixture` retains the minimal original test fixture. `fig demo` seeds the
richer fictional walkthrough with deterministic IDs and preserves existing decisions.
Demo claims are reviewed by `synthetic-demo-author`, not a real analyst.

## Recovery

- **Database unavailable / migrations missing:** check the database URL and run
  `fig migrate` using the same configuration as the API, then select Retry connection.
- **Empty corpus:** run `fig demo` or ingest filings, then Refresh data.
- **Model option disabled:** configure both required variables and restart the API.
  Rule extraction remains available without either variable.
- **No supported answer:** check registered names, accepted claims, and hop limits.
  Missing coverage does not prove that a real-world relationship is absent.
- **SEC ingestion failure:** correct the contact setting or retry transient failures
  later. The client respects its bounded retries and does not bypass access denials.

Stop the Python server with Ctrl-C. Preserve the local database and archive together;
run migrations before reopening a workspace after upgrading. Shared network deployment
requires an additional authenticated deployment design and is outside this release.
