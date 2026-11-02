-- Real consent verification (Whisper transcript + match score) and multi-engine voice clones.

-- Use DOUBLE PRECISION instead of NUMERIC so values map directly to f64.
ALTER TABLE voice_samples   ALTER COLUMN duration_seconds TYPE DOUBLE PRECISION;
ALTER TABLE speech_jobs     ALTER COLUMN speed  TYPE DOUBLE PRECISION,
                            ALTER COLUMN volume TYPE DOUBLE PRECISION;
ALTER TABLE generated_audio ALTER COLUMN duration_seconds TYPE DOUBLE PRECISION;

-- Consent: the server issues the phrase first; the audio arrives at verification time.
ALTER TABLE consents ALTER COLUMN consent_audio_url DROP NOT NULL;
ALTER TABLE consents RENAME COLUMN consent_audio_url TO consent_audio_key;
ALTER TABLE consents
    ADD COLUMN transcript  TEXT,
    ADD COLUMN match_score DOUBLE PRECISION,
    ADD COLUMN attempts    INT NOT NULL DEFAULT 0,
    ADD COLUMN verified_at TIMESTAMPTZ;

-- Voice clones: engine-neutral naming.
ALTER TABLE voice_clones RENAME COLUMN minimax_voice_id TO voice_id;
ALTER TABLE voice_clones
    ADD COLUMN engine            TEXT NOT NULL DEFAULT 'minimax',
    ADD COLUMN provider_voice_id TEXT,      -- id returned by the provider (e.g. ElevenLabs)
    ADD COLUMN reference_audio_key TEXT,    -- F5-TTS: trimmed reference clip
    ADD COLUMN reference_text    TEXT,      -- F5-TTS: Whisper transcript of that clip
    ADD COLUMN error_message     TEXT;

ALTER TABLE generated_audio ADD COLUMN mime_type TEXT NOT NULL DEFAULT 'audio/mpeg';

CREATE INDEX IF NOT EXISTS idx_voice_samples_user ON voice_samples(user_id);
