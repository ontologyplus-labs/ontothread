# OntoThread architecture

The `ontothread` distribution retains the `fig` import package for compatibility.
`fig.cli` supplies the preferred `ontothread` command and the legacy `fig` alias.
`fig.api:create_app` exposes the existing `/v1` contracts and serves
packaged HTML, CSS, and JavaScript from the same process. No frontend build is needed.
The OpenAPI schema at `/openapi.json` and interactive `/docs` describe request types.

The relational store is authoritative: SQLite is the lightweight local adapter;
PostgreSQL is the integration/deployment database. Immutable source bytes are archived
by hash. Normalized text, passage offsets, quotes, review decisions, ontology versions,
and relationship lifecycle events retain their provenance. Explicit review is required
before extracted proposals enter eligible graph traversal. Quote integrity alone does
not establish semantic entailment.

Committed claims and projection outbox events share a relational transaction. The
explicit projector updates Neo4j and acknowledges delivery after graph commit.
Research questions use bounded, evidence-backed paths and inspectable read-only Cypher.
Historical knowledge, identity, and validity cutoffs retain their existing behavior.

## Extension points

Use `fig.ingestion` and `fig.sec` for supported SEC forms, `fig.extraction` for proposals
and audited decisions, and the versioned ontology resources for allowed relationships.
For an isolated API instance, call `create_app(Settings(database_url, archive_dir))`.
Do not bypass the review queue or edit stored claims to add new extraction strategies.
General document adapters and hosted multi-user services are deferred.

## Curated SEC excerpt demo

`fig.demo` validates and seeds the packaged real-data snapshot. `Document.content_scope`
identifies excerpts; `excerpt_origin` records the original document/text IDs, full
filing hash, original normalized hash and parser, and source text offsets. The current
content hash identifies the archived excerpt bytes. These are additive `/v1` document
metadata fields; older records default to `full_document` with no excerpt origin.
The existing JSON-backed document store requires no schema migration. Excerpt IDs
are distinct from full-ingestion IDs, so a snapshot can coexist with complete filings.
