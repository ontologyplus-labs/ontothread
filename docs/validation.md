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
