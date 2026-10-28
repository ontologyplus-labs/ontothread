CREATE TABLE IF NOT EXISTS ingestion_receipt (
 id TEXT PRIMARY KEY REFERENCES text_version(id),
 document_id TEXT NOT NULL REFERENCES document(id),
 quality_flags TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS passage_text_version_idx ON passage(text_version_id);
CREATE INDEX IF NOT EXISTS text_version_document_idx ON text_version(document_id);
