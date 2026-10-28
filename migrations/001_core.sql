-- Portable relational foundation. UUIDs and canonical UTC timestamps are encoded
-- as text in this first migration. Python contracts validate their types.
CREATE TABLE IF NOT EXISTS entity (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, canonical_name TEXT NOT NULL,
 slug TEXT NOT NULL UNIQUE, status TEXT NOT NULL CHECK(status IN ('reviewed','provisional')),
 payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document (
 id TEXT PRIMARY KEY, issuer_id TEXT NOT NULL REFERENCES entity(id),
 source TEXT NOT NULL, source_url TEXT NOT NULL, accession TEXT NOT NULL,
 filename TEXT NOT NULL, published_at TEXT NOT NULL, acquired_at TEXT NOT NULL,
 content_hash TEXT NOT NULL, payload TEXT NOT NULL,
 UNIQUE(source, accession, filename, content_hash)
);
CREATE TABLE IF NOT EXISTS text_version (
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES document(id),
 parser_version TEXT NOT NULL, normalized_hash TEXT NOT NULL,
 normalized_text TEXT NOT NULL, payload TEXT NOT NULL,
 UNIQUE(document_id, parser_version, normalized_hash)
);
CREATE TABLE IF NOT EXISTS passage (
 id TEXT PRIMARY KEY, text_version_id TEXT NOT NULL REFERENCES text_version(id),
 start_offset INTEGER NOT NULL CHECK(start_offset >= 0),
 end_offset INTEGER NOT NULL CHECK(end_offset > start_offset),
 section_path TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claim (
 id TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS claim_revision (
 id TEXT PRIMARY KEY, claim_id TEXT NOT NULL REFERENCES claim(id),
 revision INTEGER NOT NULL CHECK(revision > 0),
 subject_id TEXT NOT NULL REFERENCES entity(id), object_id TEXT NOT NULL REFERENCES entity(id),
 predicate TEXT NOT NULL, review_state TEXT NOT NULL CHECK(review_state IN ('pending','accepted','rejected','superseded')),
 assertion_class TEXT NOT NULL CHECK(assertion_class IN ('explicit','normalized_explicit','inferred')),
 polarity TEXT NOT NULL CHECK(polarity IN ('positive','negative')),
 source_available_at TEXT NOT NULL, system_from TEXT NOT NULL, system_to TEXT,
 valid_from TEXT, valid_to TEXT, payload TEXT NOT NULL,
 UNIQUE(claim_id, revision), CHECK(system_to IS NULL OR system_to > system_from),
 CHECK(valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from)
);
CREATE TABLE IF NOT EXISTS evidence (
 id TEXT PRIMARY KEY, claim_revision_id TEXT NOT NULL REFERENCES claim_revision(id),
 passage_id TEXT NOT NULL REFERENCES passage(id), quote TEXT NOT NULL,
 start_offset INTEGER NOT NULL CHECK(start_offset >= 0),
 end_offset INTEGER NOT NULL CHECK(end_offset > start_offset),
 assessment TEXT NOT NULL CHECK(assessment IN ('supported','partial','unsupported','contradictory')),
 payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projection_outbox (
 id TEXT PRIMARY KEY, claim_revision_id TEXT NOT NULL UNIQUE REFERENCES claim_revision(id),
 payload TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending','delivered'))
);
CREATE INDEX IF NOT EXISTS claim_subject_idx ON claim_revision(subject_id);
CREATE INDEX IF NOT EXISTS claim_object_idx ON claim_revision(object_id);
CREATE INDEX IF NOT EXISTS evidence_claim_idx ON evidence(claim_revision_id);
CREATE INDEX IF NOT EXISTS outbox_state_idx ON projection_outbox(state);
