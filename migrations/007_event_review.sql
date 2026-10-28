CREATE TABLE IF NOT EXISTS event_candidate (
 id TEXT PRIMARY KEY,
 passage_id TEXT NOT NULL REFERENCES passage(id),
 company_id TEXT NOT NULL REFERENCES entity(id),
 event_type TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('pending','accepted','rejected')),
 version INTEGER NOT NULL DEFAULT 1,
 payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS event_candidate_state_idx ON event_candidate(state,event_type);
CREATE TABLE IF NOT EXISTS event_review_decision (
 id TEXT PRIMARY KEY,
 candidate_id TEXT NOT NULL REFERENCES event_candidate(id),
 candidate_version INTEGER NOT NULL,
 payload TEXT NOT NULL,
 UNIQUE(candidate_id,candidate_version)
);
