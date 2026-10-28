CREATE TABLE IF NOT EXISTS extraction_run (
 id TEXT PRIMARY KEY,
 passage_id TEXT NOT NULL REFERENCES passage(id),
 status TEXT NOT NULL CHECK(status IN ('running','completed','failed')),
 started_at TEXT NOT NULL,
 payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS extraction_candidate (
 id TEXT PRIMARY KEY,
 run_id TEXT NOT NULL REFERENCES extraction_run(id),
 passage_id TEXT NOT NULL REFERENCES passage(id),
 state TEXT NOT NULL CHECK(state IN ('pending','accepted','rejected','duplicate')),
 version INTEGER NOT NULL DEFAULT 1,
 claim_revision_id TEXT REFERENCES claim_revision(id),
 payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS candidate_passage_idx ON extraction_candidate(passage_id,state);
CREATE TABLE IF NOT EXISTS review_decision (
 id TEXT PRIMARY KEY,
 candidate_id TEXT NOT NULL REFERENCES extraction_candidate(id),
 candidate_version INTEGER NOT NULL,
 payload TEXT NOT NULL,
 UNIQUE(candidate_id,candidate_version)
);
