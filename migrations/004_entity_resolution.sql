CREATE TABLE IF NOT EXISTS entity_resolution (
 alias_entity_id TEXT PRIMARY KEY REFERENCES entity(id),
 canonical_entity_id TEXT NOT NULL REFERENCES entity(id),
 state TEXT NOT NULL CHECK(state IN ('merged','split')),
 version INTEGER NOT NULL CHECK(version >= 1),
 decided_at TEXT NOT NULL,
 payload TEXT NOT NULL,
 CHECK(alias_entity_id <> canonical_entity_id)
);
CREATE INDEX IF NOT EXISTS entity_resolution_canonical_idx
 ON entity_resolution(canonical_entity_id,state);
CREATE TABLE IF NOT EXISTS entity_resolution_decision (
 id TEXT PRIMARY KEY,
 alias_entity_id TEXT NOT NULL REFERENCES entity(id),
 resolution_version INTEGER NOT NULL,
 payload TEXT NOT NULL,
 UNIQUE(alias_entity_id,resolution_version)
);
