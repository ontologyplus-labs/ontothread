CREATE TABLE IF NOT EXISTS ontology_version (
 version TEXT PRIMARY KEY,
 ordinal INTEGER NOT NULL UNIQUE CHECK(ordinal >= 1),
 parent_version TEXT REFERENCES ontology_version(version),
 schema_hash TEXT NOT NULL UNIQUE,
 definitions TEXT NOT NULL,
 migration_notes TEXT NOT NULL,
 approved_at TEXT NOT NULL,
 approved_by TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ontology_change_proposal (
 id TEXT PRIMARY KEY,
 base_ontology_version TEXT NOT NULL REFERENCES ontology_version(version),
 change_type TEXT NOT NULL CHECK(change_type IN ('add_entity_kind','add_predicate','add_qualifier')),
 concept_name TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('pending','accepted','merged','rejected','deferred')),
 version INTEGER NOT NULL CHECK(version >= 1),
 created_at TEXT NOT NULL,
 payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ontology_proposal_state_idx
 ON ontology_change_proposal(state,change_type,concept_name);
CREATE TABLE IF NOT EXISTS ontology_proposal_evidence (
 proposal_id TEXT NOT NULL REFERENCES ontology_change_proposal(id),
 passage_id TEXT NOT NULL REFERENCES passage(id),
 PRIMARY KEY(proposal_id,passage_id)
);
CREATE TABLE IF NOT EXISTS ontology_change_decision (
 id TEXT PRIMARY KEY,
 proposal_id TEXT NOT NULL REFERENCES ontology_change_proposal(id),
 proposal_version INTEGER NOT NULL,
 payload TEXT NOT NULL,
 UNIQUE(proposal_id,proposal_version)
);
CREATE TABLE IF NOT EXISTS ontology_migration (
 id TEXT PRIMARY KEY,
 proposal_id TEXT NOT NULL UNIQUE REFERENCES ontology_change_proposal(id),
 from_version TEXT NOT NULL REFERENCES ontology_version(version),
 to_version TEXT NOT NULL UNIQUE REFERENCES ontology_version(version),
 payload TEXT NOT NULL
);
