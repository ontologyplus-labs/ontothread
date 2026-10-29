# Real SEC demo snapshot

`ontothread demo` loads **sec-demo-v1**, bundled in the Python package, without
network requests or model calls. It contains five real companies, four selected
filing passages, five development-reviewed manufacturing claims, and two rule-based
proposals from a later filing that still require an explicit user decision.

| Issuer | Filing | Filed | Included use |
| --- | --- | --- | --- |
| NVIDIA | [2025 10-K](https://www.sec.gov/Archives/edgar/data/1045810/000104581025000023/nvda-20250126.htm) | February 26, 2025 | Reviewed manufacturing claims to TSMC and Samsung |
| AMD | [2025 10-K](https://www.sec.gov/Archives/edgar/data/2488/000000248825000012/amd-20241228.htm) | February 5, 2025 | Reviewed manufacturing claims to TSMC and Samsung |
| Broadcom | [2024 10-K](https://www.sec.gov/Archives/edgar/data/1730168/000173016824000139/avgo-20241103.htm) | December 20, 2024 | Reviewed manufacturing claim to TSMC |
| NVIDIA | [2026 10-K](https://www.sec.gov/Archives/edgar/data/1045810/000104581026000021/nvda-20260125.htm) | February 25, 2026 | Two proposals for an explicit review exercise |

The snapshot is historical. It does not establish present-day relationships,
financial materiality, complete filing coverage, or the absence of other connections.
The retained claims were source-reviewed by Codex during development, not independently
annotated by humans. Reviewer identities and original source record IDs remain in
the snapshot manifest. No sealed reviewer returns are used.

## Provenance and archive scope

Each excerpt was checked against the original archived SEC HTML, its SHA-256, and
a fresh run of the pinned `html-blocks-v1` normalizer. Original passage offsets and
every reviewed quote were verified. The bundled packet has a canonical SHA-256;
loading rejects a changed packet, invalid text hashes, offsets, or quote mismatches.

For seeded documents, `content_scope=excerpt`. `content_hash` identifies the selected
excerpt bytes actually archived. `excerpt_origin` preserves the complete original
filing hash, normalized-text hash, parser version, document/text IDs, and offsets.
The UI labels selected excerpts and links to the complete SEC filing. Full original
HTML is not redistributed in the package. Full-ingestion document IDs are kept distinct.

## Walkthrough

1. Run `ontothread migrate`, then `ontothread demo`; start the API and refresh.
2. With NVIDIA selected, ask “Show paths between NVIDIA and Broadcom.” Inspect the
   two-hop path through TSMC and the filing evidence supporting each edge.
3. Choose Samsung as the path target and allow three hops. A three-hop path through
   TSMC and AMD complements the direct NVIDIA-to-Samsung disclosure.
4. Search the later NVIDIA excerpt for `manufacturing` or `foundries`.
5. Inspect the pending TSMC and Samsung proposals. Resolve TSMC to the existing
   canonical company before accepting, so its expanded source name does not create
   an accidental duplicate identity. Decisions survive repeated demo seeding.

For testing accept/reject mechanics, use a disposable database and identify any
rejection as a workflow exercise, not a new source assessment. Synthetic unit-test
fixtures remain available through `ontothread demo --synthetic` and `seed-fixture`;
they are never automatically substituted when real data is missing.

## Rebuild from the preserved research archive

The builder opens the research database read-only and checks every referenced raw
source hash and normalized excerpt before exporting only the selected public fields:

```sh
python scripts/build_sec_demo.py --database /path/to/development.sqlite3 --archive /path/to/archive --output /tmp/sec-demo-verified.json
```

The required original source claim and passage IDs are declared in the builder.
The output must not already exist. Compare it with `src/fig/resources/sec-demo-v1.json`.
Changing the selected dataset requires a new reviewed snapshot version; never replace
an existing version silently. No credentials or machine-specific paths are exported.
