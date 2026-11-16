-- The verified consent recording is now the voice sample, and each consent creates one voice.
ALTER TABLE consents ADD COLUMN used_at TIMESTAMPTZ;

UPDATE consents c SET used_at = vc.created_at
FROM (SELECT consent_id, MIN(created_at) AS created_at FROM voice_clones GROUP BY consent_id) vc
WHERE vc.consent_id = c.id;
