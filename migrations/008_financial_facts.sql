CREATE TABLE IF NOT EXISTS financial_observation (
 id TEXT PRIMARY KEY,
 entity_id TEXT NOT NULL REFERENCES entity(id),
 taxonomy TEXT NOT NULL,
 concept TEXT NOT NULL,
 unit TEXT NOT NULL,
 period_end TEXT NOT NULL,
 filed_at TEXT NOT NULL,
 accession TEXT NOT NULL,
 payload TEXT NOT NULL,
 UNIQUE(entity_id,taxonomy,concept,unit,period_end,accession)
);
CREATE INDEX IF NOT EXISTS financial_observation_lookup_idx ON financial_observation(entity_id,concept,period_end);
