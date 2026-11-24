# OntoThread

**An evidence-backed financial intelligence graph by OntologyPlus.**

OntoThread turns SEC filings into reviewed relationships and evolving knowledge
graphs. Researchers can explore connections, inspect exact source evidence, and
trace how claims and ontologies change over time.

[Read the research essay](https://ontologyplus.substack.com/p/the-companies-behind-the-companies)
for the investing question, the shared-foundry example, and the design behind OntoThread.

[Read the TSMC case study](docs/tsmc-ontology-case-study.md) for a real example of
how a filing led to a new relationship type and a query the graph could answer.

## What OntoThread does

- Archive source documents and retain immutable text, passages, and exact quotes.
- Extract relationship proposals and require explicit review before graph inclusion.
- Explore company relationships, bounded one-to-three-hop paths, and supported research questions.
- Inspect ontology versions and audited schema changes while preserving historical queries.

The first release is a self-hosted research tool focused on finance and SEC filings.
Disclosed relationships do not establish financial materiality. OntologyPlus is the
umbrella brand; OntoThread is this product and repository.

## Quick start

Clone the repository, then choose either setup below.

```sh
git clone https://github.com/ontologyplus-labs/ontothread.git
cd ontothread
```

### Python and SQLite

Requires Python 3.12 or newer. Commands below use a macOS/Linux shell; on Windows,
activate the environment with `.venv\Scripts\Activate.ps1` instead.

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
ontothread migrate
ontothread demo
uvicorn fig.api:app --host 127.0.0.1 --port 8000
```

Open [the research workspace](http://127.0.0.1:8000/) or
[the API explorer](http://127.0.0.1:8000/docs).

**The default demo uses real SEC evidence:** four selected filing excerpts from
NVIDIA, AMD, and Broadcom, five reviewed manufacturing relationships involving
TSMC and Samsung, and two proposals from a later NVIDIA filing for explicit review.
It runs offline with no SEC requests, model calls, or API keys. Repeat
`ontothread demo` safely without resetting review decisions.

Start with NVIDIA and “Show paths between NVIDIA and Broadcom,” then inspect the
TSMC connection and its exact quotes. The path explorer also supports a three-hop
route from NVIDIA through TSMC and AMD to Samsung. These paths preserve each
claim's direction; they do not assert a direct relationship between every company.

This is a **historical excerpt snapshot**, using disclosures filed December 2024–
February 2026, not complete filings or live company coverage. Original filing links,
hashes, normalized-text offsets, and development reviewer attribution are retained.
The source reviews were performed by Codex during development, not independent
human annotators. See [the real demo manifest and provenance](docs/real-demo.md).

Synthetic data is available explicitly for tests with `ontothread demo --synthetic`
or the minimal `ontothread seed-fixture`; it is hidden in the UI by default.

No `.env` is required. Defaults use `data/fixture.sqlite3` and `data/archive`.
For optional settings, copy `.env.example` to `.env`. Explicit environment variables
take precedence. For pinned development dependencies on macOS/Linux, install
`requirements.lock` before `python -m pip install --no-deps --no-build-isolation -e .`.

### Docker Compose with PostgreSQL and Neo4j

Requires Docker with Compose. Run from the repository root:

```sh
cp .env.compose.example .env
docker compose up --build -d --wait
docker compose exec api ontothread demo
docker compose exec api ontothread project
```

Open [the workspace](http://127.0.0.1:8000/) and
[Neo4j Browser](http://127.0.0.1:7474/). Local Neo4j credentials are `neo4j` and
`fig_local_password`, unless changed in `.env`. Startup runs migrations and checks
service readiness. `docker compose down` then `docker compose up -d --wait` preserves
work in named database volumes and the local archive directory.

The application reads authoritative relational claims. Neo4j is an explicitly
updated projection; run `ontothread project` after accepting new claims.

## From filings to reviewed relationships

Set `SEC_USER_AGENT` in `.env` to your application name and real contact email.
Then, in the Python environment:

```sh
ontothread ingest-sec --cik 1045810
# Or select a bounded set of supported forms:
ontothread ingest-filings --cik 1045810 --forms 10-K,10-Q --filing-limit 3
```

With Compose, prefix each command with `docker compose exec api` and restart
`api` after editing `.env` so the container receives updated configuration.
Refresh the browser after ingestion. Find candidates in source passages, inspect
company identity and relationship direction, and accept or reject with a reviewer
identity. Only reviewed acceptance adds an eligible graph relationship.

The default rule extractor requires no model configuration. Optional OpenAI extraction
requires `OPENAI_API_KEY` and `FIG_LLM_MODEL` in server configuration. Explicitly selecting
it can incur provider charges. Keys are never entered in the browser.

## Research questions and source evidence

Choose a company to inspect accepted relationships, find paths, search its filings,
and open exact supporting quotes. Supported research questions return bounded paths,
citations, limitations, and an inspectable query plan. Missing coverage is not evidence
that a relationship does not exist. See [Financial research with OntoThread](docs/usage.md).

## Ontology evolution

Versioned finance ontologies define allowed entity and relationship types. Evidence-linked
proposals, review decisions, schema versions, and selective reprocessing retain an audit
history. Historical identity, knowledge, and validity cutoffs preserve earlier views.
The [architecture guide](docs/architecture.md) describes the underlying contracts.

## Keeping relationships current

Use the CLI to ingest successive filings, compare their passages in the browser,
and review candidates against their exact source quotes. Relationship histories
and recorded correction, supersession, retraction, and conflict decisions retain
the evidence and review timeline. API queries support publication, knowledge,
effective-date, and identity cutoffs.

Scheduled filing monitoring and automatic flags for omitted disclosures are planned
extensions. The current workflow starts with CLI ingestion and explicit review.
Silence in a later filing leaves the last supported disclosure in the record;
establishing an end date requires supporting evidence.

## CLI, Python library, and API

The Python distribution and preferred CLI are named `ontothread`. For compatibility,
`fig` remains a CLI alias, the Python import package stays `fig`, and `FIG_*` settings
and existing `/v1` routes keep their meanings. For example:

```python
from pathlib import Path
from fig.api import create_app
from fig.config import Settings

app = create_app(Settings("sqlite:///data/fixture.sqlite3", Path("data/archive")))
```

The API explorer is served at `/docs`, with the OpenAPI schema at `/openapi.json`.
The browser UI is packaged with the API and requires no separate frontend build.
See [branding and compatibility](docs/branding.md) for migration from the former name.

## Validation and limitations

```sh
python -m pytest -m "not integration"
python scripts/audit_release.py
```

[Contributing](CONTRIBUTING.md) covers dedicated integration checks, packaging, and browser
acceptance. [Research fixtures](evaluation/README.md) describes the selected regression
dataset; private reviewer returns and the original research archive are not distributed.
[Release instructions](docs/releasing.md) cover source archives and publication, and
[validation notes](docs/validation.md) record checks actually run.

All services bind to loopback. The application currently has no authentication.
Shared hosting, accounts, billing, and arbitrary document domains are outside this
release. Code is available under the [MIT license](LICENSE); retained SEC excerpts
keep their source attribution as described in [DATA_NOTICE.md](DATA_NOTICE.md).
