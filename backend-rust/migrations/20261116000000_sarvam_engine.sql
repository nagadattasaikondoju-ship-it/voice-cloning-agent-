-- Voices are now spoken by the Sarvam AI voice cloning API. Existing reference clips keep working
-- (the worker sends the same prepared WAV), so existing voices are only relabelled.
ALTER TABLE voice_clones ALTER COLUMN engine SET DEFAULT 'sarvam';
UPDATE voice_clones SET engine = 'sarvam' WHERE engine = 'chatterbox';
