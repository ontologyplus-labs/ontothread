CREATE TABLE IF NOT EXISTS entity_identifier (
 entity_id TEXT NOT NULL REFERENCES entity(id),
 scheme TEXT NOT NULL,
 value TEXT NOT NULL,
 source TEXT NOT NULL,
 payload TEXT NOT NULL,
 PRIMARY KEY(scheme,value),
 UNIQUE(entity_id,scheme)
);
CREATE INDEX IF NOT EXISTS entity_identifier_entity_idx ON entity_identifier(entity_id);
CREATE TABLE IF NOT EXISTS entity_alias (
 entity_id TEXT NOT NULL REFERENCES entity(id),
 alias TEXT NOT NULL,
 normalized_alias TEXT NOT NULL,
 source TEXT NOT NULL,
 payload TEXT NOT NULL,
 PRIMARY KEY(entity_id,normalized_alias)
);
CREATE INDEX IF NOT EXISTS entity_alias_lookup_idx ON entity_alias(normalized_alias);
