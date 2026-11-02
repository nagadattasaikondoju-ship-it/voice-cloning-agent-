-- One local engine: Chatterbox Turbo (English). The remote engines (MiniMax, ElevenLabs, F5 Space) are removed.
UPDATE voice_clones
SET status = 'failed', error_message = 'This voice used an engine that was removed. Please create it again.'
WHERE engine <> 'chatterbox' AND deleted_at IS NULL;

ALTER TABLE voice_clones ALTER COLUMN engine SET DEFAULT 'chatterbox';
ALTER TABLE voice_clones DROP COLUMN provider_voice_id, DROP COLUMN reference_text;

-- Pitch is not supported by Chatterbox.
ALTER TABLE speech_jobs DROP COLUMN pitch;
