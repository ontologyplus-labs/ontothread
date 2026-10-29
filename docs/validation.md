# Local release validation

Validated October 27, 2026 on macOS with CPython 3.12.14 and Chromium 151.

- Fresh `pip install -e ".[dev]"` succeeded in a new virtual environment.
- The full suite passed: **243 tests, no skips**, including the nine dedicated
  PostgreSQL 17.6 / Neo4j 5.26.12 integration cases.
- Offline demo checks prohibited socket connections and verified deterministic
  seeding, three-hop paths, three citations, exact archival bytes, and accepted /
  rejected review decisions surviving reseeding.
- Automated Chromium acceptance passed for questions, paths, exact evidence,
  source search, accept/reject persistence, keyboard navigation, 390 px layout,
  missing migrations, empty corpus, failed requests, and unavailable optional
  model configuration. The browser made no external requests.
- A built wheel installed into a separate environment and ran migrations, demo,
  health, API explorer, and packaged HTML/CSS/JavaScript outside the source checkout.
- The tracked-source release audit passed. Original copied source hashes were
  rechecked against the preserved research workspace.

The suite emits one existing Starlette/httpx deprecation warning. Docker is not
installed on this host, so image build and Compose orchestration were not executed;
Compose syntax and Docker build inputs were inspected, and database integration
was verified with isolated native services. Python 3.13 and GitHub Actions execution
are configured in CI but have not been run here. No GitHub repository was published.

## OntoThread rebrand validation

The standalone checkout and Python distribution are now `ontothread`, presented
as **OntoThread by OntologyPlus**. The rebrand was validated with:

- **243 tests passed with no skips**, including PostgreSQL and Neo4j integration.
- The full offline Chromium acceptance workflow, plus inspection of the new
  branding at 1440 px, 1024 px, and 390 px without page or navigation overflow.
- A renamed wheel installed in a separate environment and exercised outside the
  checkout: both `ontothread` and `fig` commands, migrations, API metadata, UI
  assets, health, and the API explorer.
- A copy of the original release's demo database: seeding through both commands
  returned identical results and preserved every entity, document, text version,
  passage, claim revision, and evidence ID.
- Unchanged fixture/identity logic, configuration, API contract types, and MIT
  attribution, plus the tracked-source release audit.

Existing Docker, Python 3.13, and hosted-publication limitations above still apply.

## Real SEC demo validation — October 29, 2026

The default demo now loads the bundled `sec-demo-v1` snapshot: five real companies,
four SEC filing excerpts, five development-reviewed claims, and two pending proposals.
Synthetic fixtures require explicit CLI/UI opt-in. Earlier synthetic-demo validation
above records the previous release behavior.

- **249 tests passed, no skips**, including the nine isolated PostgreSQL/Neo4j checks.
  The default CLI demo test blocks socket connections and checks both command aliases.
- Re-exporting from the read-only research database and original archived SEC HTML
  reproduced the bundled snapshot byte-for-byte. Normalization, source hashes,
  exact quotes, and provenance offsets were verified.
- In-app browser checks covered the default real-data view, two-citation research,
  direct and three-hop paths, exact quotes, SEC source links, passage search and its
  empty state, cached rules extraction, explicit accept/reject decisions, decision
  history and reload persistence, keyboard activation, and 390 px layout without
  horizontal page overflow. Review actions used a disposable database. No browser
  warnings or errors were reported.
- The automated browser acceptance script was updated for real data and passed its
  JavaScript syntax check; its current version is configured in CI. The in-app
  browser checks above were run locally, rather than rerunning the standalone script.
- The rebuilt wheel was installed into a separate environment and exercised from
  an empty working directory: migrations, both CLI aliases, four real excerpt
  archives, original provenance, packaged assets/resources, health, API explorer,
  and the two-citation research answer all passed.
- The existing preview database was seeded without deleting earlier synthetic
  fixtures. Its open browser now defaults to NVIDIA and real SEC evidence; the
  test-fixture toggle remains unchecked.

The existing Starlette/httpx warning and Docker/Python 3.13/CI execution limitations
above still apply. The snapshot is historical, excerpt-only, and source-reviewed
by Codex during development; it is not an independent human annotation dataset.
