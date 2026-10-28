CREATE TABLE IF NOT EXISTS relationship_identity (
 id TEXT PRIMARY KEY,
 subject_id TEXT NOT NULL REFERENCES entity(id),
 predicate TEXT NOT NULL,
 object_id TEXT NOT NULL REFERENCES entity(id),
 payload TEXT NOT NULL,
 UNIQUE(subject_id,predicate,object_id)
);
CREATE TABLE IF NOT EXISTS claim_relationship_link (
 claim_revision_id TEXT PRIMARY KEY REFERENCES claim_revision(id),
 relationship_id TEXT NOT NULL REFERENCES relationship_identity(id)
);
CREATE INDEX IF NOT EXISTS claim_relationship_identity_idx ON claim_relationship_link(relationship_id);
CREATE TABLE IF NOT EXISTS claim_lifecycle_decision (
 id TEXT PRIMARY KEY,
 relationship_id TEXT NOT NULL REFERENCES relationship_identity(id),
 action TEXT NOT NULL CHECK(action IN ('supersede','retract','correct','retain_conflict')),
 claim_revision_id TEXT REFERENCES claim_revision(id),
 conflicting_claim_revision_id TEXT REFERENCES claim_revision(id),
 decided_at TEXT NOT NULL,
 payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS claim_lifecycle_relationship_idx ON claim_lifecycle_decision(relationship_id,decided_at);
