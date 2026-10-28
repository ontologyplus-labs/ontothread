# Financial Intelligence Graph

A self-hosted research platform for building and inspecting evidence-backed
relationships from SEC filings. Run a synthetic demo locally, ingest filings
through the CLI, then research and review claims in your browser.

The platform includes a Python library, `fig` CLI, FastAPI API, and browser UI.
Every accepted relationship retains its exact quote, source provenance, reviewer,
and ontology version. Graph traversal supports one to three hops. This is a
research tool; disclosed relationships do not establish financial materiality.

## Quick start: Python and SQLite

Requires Python 3.12 or newer. Commands below use a macOS/Linux shell; on Windows,
activate the environment with `.venv\Scripts\Activate.ps1` instead.

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
fig migrate
fig demo
uvicorn fig.api:app --host 127.0.0.1 --port 8000
```

Open [the research workspace](http://127.0.0.1:8000/) or
[the API explorer](http://127.0.0.1:8000/docs).

**The demo is offline and synthetic:** four fictional companies, a three-edge
chain, and two proposals you can extract and review. It uses no SEC requests,
model calls, or API keys. Repeat `fig demo` safely without resetting review decisions.
Use “Example Designer” and the suggested question to start; search for
`manufacturing` or find candidates using `foundries`.

No `.env` is required. Defaults use `data/fixture.sqlite3` and `data/archive`.
For optional settings, copy `.env.example` to `.env`. Explicit environment
variables take precedence. For fully pinned development dependencies on
macOS/Linux, install `requirements.lock` before installing the package with
`python -m pip install --no-deps --no-build-isolation -e .`.

## Docker Compose: PostgreSQL and Neo4j

Requires Docker with Compose. Run from the repository root:

```sh
cp .env.compose.example .env
docker compose up --build -d --wait
docker compose exec api fig demo
docker compose exec api fig project
```

Open [the workspace](http://127.0.0.1:8000/) and
[Neo4j Browser](http://127.0.0.1:7474/). Local Neo4j credentials are `neo4j` and
`fig_local_password`, unless changed in `.env`. Application startup runs migrations;
service health checks wait for database readiness. Restart with
`docker compose down` and `docker compose up -d --wait`; named database volumes
and the local archive directory preserve your work.

The application reads authoritative relational claims. Neo4j is an explicitly
updated projection: run `fig project` again after accepting new claims.

## Load real SEC filings

Set `SEC_USER_AGENT` in `.env` to your application name and real contact email.
Then, in the Python environment:

```sh
fig ingest-sec --cik 1045810
# Or select a bounded set of supported forms:
fig ingest-filings --cik 1045810 --forms 10-K,10-Q --filing-limit 3
```

With Compose, prefix each command with `docker compose exec api` and restart
`api` after changing `.env` so the container receives updated configuration.
Refresh the browser when ingestion finishes. Ingested text does not become an
accepted graph relationship until a candidate receives an explicit review.

The default rule extractor needs no model configuration. Optional OpenAI extraction
requires `OPENAI_API_KEY` and `FIG_LLM_MODEL` in local configuration; selecting it
explicitly can incur provider charges. Keys stay on the server and are never entered
in the browser. See [configuration and workflows](docs/usage.md).

## Develop and reuse

```sh
python -m pytest -m "not integration"
python scripts/audit_release.py
```

[Contributing](CONTRIBUTING.md) explains integration checks, packaging, and browser
verification. [Architecture](docs/architecture.md) describes the library and API.
[Research fixtures](evaluation/README.md) explains the small retained test dataset;
the original research workspace and private reviewer returns are not distributed.
[Release instructions](docs/releasing.md) cover local builds and GitHub publication.

All services bind to loopback. Shared hosting, accounts, billing, and arbitrary
document domains are outside this first release. The application currently has
no authentication. Code is available under the [MIT license](LICENSE); retained
SEC excerpts keep their source attribution and are described separately in
[DATA_NOTICE.md](DATA_NOTICE.md).
