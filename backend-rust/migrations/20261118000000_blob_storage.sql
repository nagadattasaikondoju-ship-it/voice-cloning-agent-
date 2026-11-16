-- Audio is stored in the database (hosts like Render's free tier have no persistent disk).
-- Keys look like 'consents/<id>_1.webm', 'references/<voice>.wav', 'generated/<job>.mp3'.
CREATE TABLE IF NOT EXISTS blobs (
    key        TEXT PRIMARY KEY,
    user_id    UUID REFERENCES users(id) ON DELETE CASCADE,
    mime_type  TEXT NOT NULL,
    data       BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_blobs_user ON blobs(user_id);
