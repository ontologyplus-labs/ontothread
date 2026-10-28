# Contributing to OntoThread

Use Python 3.12+, create a virtual environment, and install `python -m pip install -e ".[dev]"`.
Keep changes to evidence provenance, explicit review, ontology versions, and historical
cutoffs covered by tests. Update both authoring migrations/ontologies and their
packaged copies in `src/fig/resources` when adding a new version. Do not rewrite
applied migrations or existing immutable source records.

## Checks

```sh
python -m pytest -m "not integration"
python scripts/audit_release.py
python -m pip wheel --no-deps --wheel-dir dist .
```

The suite mocks model and SEC transports. It needs no credentials and makes no
paid calls. Never load a personal `.env` into a test run. Integration tests require
dedicated disposable PostgreSQL and Neo4j services:

```sh
export FIG_TEST_DATABASE_URL=postgresql://fig:fig_local@127.0.0.1:5432/fig_test
export FIG_TEST_NEO4J_URI=bolt://127.0.0.1:7687
export FIG_TEST_NEO4J_PASSWORD=fig_local_password
python -m pytest -m integration
```

Create `fig_test` first. Do not point these variables at the application database.
CI creates disposable services, waits for both, and runs the native integration suite.

## Browser acceptance

On a fresh demo installation, check the first-run guide and synthetic badge, ask
for paths from Example Designer to Example Customer, find a three-hop path, open
an exact quote, and search `manufacturing`. Extract proposals using `foundries`,
accept one and reject the other with a reviewer identity, then inspect their history.
Refresh and confirm the decisions persist. Check an empty database, an unmigrated
database, missing optional model configuration, and a failed request with retry.

Repeat at desktop and 390 px width. Use Tab/Enter to navigate section links, graph
edges, source results, and review controls. The page must not overflow horizontally;
the relationship map may scroll within its own region.

For automated browser acceptance, optionally install Node.js 22+, run `npm ci` and
`npx playwright install chromium`, then `npm run test:browser` against a fresh
running demo. Set `FIG_BASE_URL` to use a port other than 8000. This check accepts
and rejects fictional proposals, so use a disposable demo database. Screenshots
are written to ignored `test-results/`. Node is only needed for these checks.

## Contributions and releases

Submit focused changes with a description and the checks run. Never include `.env`,
source archives, databases, private reviewer returns, or model-response caches.
Contributions are distributed under the MIT license. See `docs/releasing.md` for
release packaging and validation.

## Naming and compatibility

Use **OntoThread** for the product and **OntologyPlus** for the umbrella brand.
Financial intelligence graph describes the current capability. Keep `fig` imports,
`FIG_*` configuration, `/v1` contracts, and persisted identity namespaces compatible.
Historical source names and contributor attribution remain intact; see `docs/branding.md`.
