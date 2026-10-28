# Retained regression fixtures

This directory is a small, selected dependency set for the inherited tests:

- `nvidia-pilot.json` and `multi-issuer-heldout-v1.json`: source-attributed development
  extraction examples used by deterministic scoring and mocked provider tests.
- `followup/schema-development-v1`: candidate definitions, selected public passages,
  proposed schema/semantics, a baseline catalog, and **blank** review-response template.
- `expanded/distribution/reviewer-1` and `reviewer-2`: **blank assignment templates**
  and their public source excerpts, used by review-intake validation.
- `expanded/finalized/retrospective-v1/references.json`: development reference cases
  used to verify graph-derived diagnostics. These are not private reviewer returns.

The provenance manifest `docs/research-fixtures.json` lists original copied files
and their source SHA-256 hashes before platform edits. Personal reviewer returns,
completed annotations, model-response caches, full source downloads, manuscript drafts,
and machine-specific experiment runners are excluded. The three retained legacy script
names preserve test imports; acquisition/scoring entry points requiring excluded private
runs were removed where only pure helpers are needed.

These fixtures support regression checks, not claims of independent benchmark accuracy.
The browser demo is fictional and does not ingest any of these SEC excerpts.
See `DATA_NOTICE.md` for attribution boundaries.
