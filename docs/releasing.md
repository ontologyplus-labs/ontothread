# Releasing OntoThread

The repository and Python distribution are named `ontothread`.
The GitHub destination is `ontologyplus-labs/ontothread`, presented as
**OntoThread by OntologyPlus**. The local Git repository uses branch `main`.
Use a clean checkout and Python 3.12+:

```sh
python -m pip install -e ".[dev]"
python -m pytest -m "not integration"
python scripts/audit_release.py
python -m pip wheel --no-deps --wheel-dir dist .
```

Run the dedicated native-service integration suite described in `CONTRIBUTING.md`.
Install the wheel into a fresh environment, run `ontothread migrate`, `ontothread demo`, and
`uvicorn fig.api:app --host 127.0.0.1 --port 8000` from an empty working directory.
Verify the wheel includes both `LICENSE` and `DATA_NOTICE.md` alongside its
bundled SEC snapshot. Check excerpt provenance, packaged assets, health, and the
browser acceptance workflow. Both `ontothread demo` and the legacy `fig demo`
load real SEC excerpts; `demo --synthetic` is the explicit test-only alternative.
Check Docker Compose startup, seeding, projection, and persistence when Docker is available.
Record completed checks and any unavailable environment checks in the release notes.

Before publication, inspect `git ls-files`, run the audit, commit the reviewed changes,
and build a tracked-source archive (never archive the whole working directory):

```sh
git archive --format=zip --prefix=ontothread/ --output=dist/ontothread-source.zip HEAD
```

Create the repository privately under `ontologyplus-labs` and push the reviewed
history to `https://github.com/ontologyplus-labs/ontothread.git`. Review every
existing commit as well as the release tree for private material. Run the existing
Linux workflow, including both Python versions, database integration, Compose,
and browser acceptance. Record results for the exact reviewed commit.

Present that commit and [the release notes](releases/v0.1.0.md) for release approval.
After approval, make the repository public, tag that commit `v0.1.0`, and publish
the wheel and tracked-source archive. Verify the public clone and offline demo.
The existing MIT license and data notice ship with both artifacts. Keep personal
data, API keys, full filing archives, and reviewer returns outside Git history.

Prepare the Substack repository link and LinkedIn follow-up for separate review.
The README links back to the published research essay.
