# Architecture

The `fig` Python package contains the reusable engine. `fig.cli` supplies the `fig`
entry point; `fig.api:create_app` exposes the existing `/v1` contracts and serves
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
