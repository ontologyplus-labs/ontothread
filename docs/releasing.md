# Release checklist

The local Git repository uses branch `main`. No GitHub remote is configured by default.
Use a clean checkout and Python 3.12+:

```sh
python -m pip install -e ".[dev]"
python -m pytest -m "not integration"
python scripts/audit_release.py
python -m pip wheel --no-deps --wheel-dir dist .
```

Run the dedicated native-service integration suite described in `CONTRIBUTING.md`.
Install the wheel into a fresh environment, run `fig migrate`, `fig demo`, and
`uvicorn fig.api:app --host 127.0.0.1 --port 8000` from an empty working directory.
Verify packaged assets, health, synthetic evidence, and the browser acceptance workflow.
Check Docker Compose startup, seeding, projection, and persistence when Docker is available.
Record completed checks and any unavailable environment checks in the release notes.

Before publication, inspect `git ls-files`, run the audit, commit the reviewed changes,
and build a tracked-source archive (never archive the whole working directory):

```sh
git archive --format=zip --prefix=financial-intelligence-graph/ --output=dist/financial-intelligence-graph-source.zip HEAD
```

Only after the destination owner and repository are known, create the GitHub repository,
add its URL as `origin`, push `main`, and publish the validated artifacts. Select MIT
when configuring the public project. Do not add personal data, API keys, source archives,
or reviewer returns to Git history. This source release is not a hosted service.
