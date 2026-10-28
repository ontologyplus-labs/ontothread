CREATE TABLE IF NOT EXISTS schema_discovery (
 id TEXT PRIMARY KEY,
 passage_id TEXT NOT NULL REFERENCES passage(id),
 state TEXT NOT NULL CHECK(state IN ('pending','linked','rejected','resolved')),
 failure_type TEXT NOT NULL CHECK(failure_type IN ('missing_predicate','missing_entity_kind','qualifier_required','unresolved_identity','insufficient_context','unsupported_assertion')),
 concept_name TEXT,
 proposed_change_type TEXT CHECK(proposed_change_type IS NULL OR proposed_change_type IN ('add_predicate','add_entity_kind','add_qualifier')),
 created_at TEXT NOT NULL,
 payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS schema_discovery_passage_idx ON schema_discovery(passage_id,state);

CREATE TABLE IF NOT EXISTS claim_ontology_validation (
 claim_revision_id TEXT PRIMARY KEY REFERENCES claim_revision(id),
 ontology_version TEXT NOT NULL REFERENCES ontology_version(version),
 schema_hash TEXT NOT NULL,
 validated_at TEXT NOT NULL,
 validator TEXT NOT NULL,
 payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS claim_ontology_version_idx ON claim_ontology_validation(ontology_version);

CREATE TABLE IF NOT EXISTS ontology_reprocessing_job (
 id TEXT PRIMARY KEY,
 proposal_id TEXT NOT NULL REFERENCES ontology_change_proposal(id),
 from_version TEXT NOT NULL REFERENCES ontology_version(version),
 to_version TEXT NOT NULL REFERENCES ontology_version(version),
 status TEXT NOT NULL CHECK(status IN ('pending','running','completed','failed')),
 input_hash TEXT NOT NULL,
 started_at TEXT,
 completed_at TEXT,
 payload TEXT NOT NULL,
 UNIQUE(proposal_id,to_version,input_hash)
);
CREATE INDEX IF NOT EXISTS ontology_reprocessing_status_idx ON ontology_reprocessing_job(status);
