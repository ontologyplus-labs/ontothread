# Financial research with OntoThread

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
| `FIG_NEO4J_URI`, `FIG_NEO4J_USER`, `FIG_NEO4J_PASSWORD` | Used by `ontothread project` |

No model is selected or called automatically. The browser reads only a boolean
configuration status from `/v1/extraction/configuration`, never secret values.
Optional embedding reranking is available through the API with `use_embeddings=true`;
it requires model credentials and can incur provider charges.

## Workflow

1. Run `ontothread migrate` and `ontothread demo`, or ingest a bounded SEC filing set with the CLI.
2. Refresh the workspace. The default demo shows real NVIDIA, AMD, Broadcom, TSMC,
   and Samsung records. Synthetic test fixtures require an explicit checkbox.
3. Choose a company and explore accepted relationships or paths of one to three hops.
4. Ask a supported question naming registered companies. The deterministic planner
   returns evidence, its bounded plan, and limitations; it is not an unrestricted chatbot.
5. Search a filing, then inspect its exact passage and original source link.
6. Find candidates with the rule extractor or explicitly selected model extractor.
   Inspect direction, identity, and the quote; provide a reviewer identity to accept
   or reject. Only acceptance adds an eligible claim to the graph.
7. Run `ontothread project` after claim changes if you use Neo4j.

`ontothread demo` seeds the real, offline SEC excerpt snapshot and preserves existing
review decisions. Claims retain their original `codex:historical-source-review`
attribution; they are development reviews, not independent human labels. Source
metadata distinguishes excerpt bytes from the original complete filing and includes
both hashes and original normalized-text offsets. See [real demo provenance](real-demo.md).

`ontothread seed-fixture` retains the minimal original test fixture;
`ontothread demo --synthetic` explicitly loads the fictional walkthrough. Previously
seeded synthetic records are retained, but remain hidden unless opted in.

## Recovery

- **Database unavailable / migrations missing:** check the database URL and run
  `ontothread migrate` using the same configuration as the API, then select Retry connection.
- **Empty corpus:** run `ontothread demo` or ingest filings, then Refresh data.
- **Model option disabled:** configure both required variables and restart the API.
  Rule extraction remains available without either variable.
- **No supported answer:** check registered names, accepted claims, and hop limits.
  Missing coverage does not prove that a real-world relationship is absent.
- **SEC ingestion failure:** correct the contact setting or retry transient failures
  later. The client respects its bounded retries and does not bypass access denials.

Stop the Python server with Ctrl-C. Preserve the local database and archive together;
run migrations before reopening a workspace after upgrading. Shared network deployment
requires an additional authenticated deployment design and is outside this release.

## Compatibility after the rename

Install the Python distribution as `ontothread` and use the `ontothread` command.
The `fig` command remains an alias with the same arguments and behavior. Python
imports such as `from fig.api import create_app`, the `fig.api:app` server target,
and all `FIG_*` settings remain supported. See [branding and compatibility](branding.md).
