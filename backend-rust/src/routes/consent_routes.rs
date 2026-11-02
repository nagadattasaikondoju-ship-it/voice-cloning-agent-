use axum::{
    extract::{Multipart, Path, State},
    http::StatusCode,
    Json,
};
use serde::Deserialize;
use serde_json::json;
use uuid::Uuid;

use crate::{
    auth::AuthUser,
    consent_check::{generate_phrase, match_score},
    db::{record_audit_log, AppState},
    error::{ApiError, ApiResult},
    models::{Consent, ConsentVerification, CONSENT_COLUMNS},
    routes::read_audio_upload,
    storage, stt,
};

#[derive(Debug, Default, Deserialize)]
pub struct CreateConsentRequest {
    pub consent_version: Option<String>,
}

/// Step 1: the server issues a randomized phrase the user must read aloud.
pub async fn create_consent(
    auth: AuthUser,
    State(state): State<AppState>,
    body: Option<Json<CreateConsentRequest>>,
) -> ApiResult<Consent> {
    let version = body
        .and_then(|Json(b)| b.consent_version)
        .filter(|v| !v.trim().is_empty() && v.len() <= 32)
        .unwrap_or_else(|| "v1.0".to_string());

    let consent: Consent = sqlx::query_as(&format!(
        "INSERT INTO consents (id, user_id, spoken_phrase, consent_version)
         VALUES ($1, $2, $3, $4) RETURNING {CONSENT_COLUMNS}"
    ))
    .bind(Uuid::new_v4())
    .bind(auth.user_id)
    .bind(generate_phrase())
    .bind(version)
    .fetch_one(&state.db)
    .await?;

    record_audit_log(&state.db, Some(auth.user_id), "consent_issued", json!({ "consent_id": consent.id })).await;
    Ok(Json(consent))
}


/// Step 2: the user uploads a recording of the phrase. The speech_pipeline (Whisper)
/// transcribes it and the consent is verified only if the transcript matches the phrase.
pub async fn verify_consent(
    auth: AuthUser,
    Path(consent_id): Path<Uuid>,
    State(state): State<AppState>,
    multipart: Multipart,
) -> ApiResult<ConsentVerification> {
    let consent: Consent = sqlx::query_as(&format!(
        "SELECT {CONSENT_COLUMNS} FROM consents WHERE id = $1 AND user_id = $2"
    ))
    .bind(consent_id)
    .bind(auth.user_id)
    .fetch_optional(&state.db)
    .await?
    .ok_or_else(|| ApiError::not_found("Consent record not found"))?;

    let max = state.config.consent_max_attempts;
    if consent.verified {
        return Ok(Json(ConsentVerification {
            verified: true,
            transcript: consent.transcript.clone().unwrap_or_default(),
            match_score: consent.match_score.unwrap_or(1.0),
            threshold: state.config.consent_match_threshold,
            attempts_remaining: (max - consent.attempts).max(0),
            consent,
        }));
    }
    if consent.attempts >= max {
        return Err(ApiError::new(
            StatusCode::TOO_MANY_REQUESTS,
            "Too many failed attempts for this phrase. Request a new consent phrase.",
        ));
    }

    let upload = read_audio_upload(multipart).await?;
    let (ext, mime) = storage::audio_mime_for(upload.file_name.as_deref(), upload.content_type.as_deref())
        .ok_or_else(|| ApiError::bad_request("Unsupported audio format (use webm, wav, mp3, m4a or ogg)"))?;

    // Transcribe before counting the attempt, so an outage does not burn attempts.
    let transcript =
        stt::transcribe(&state, upload.bytes.clone(), ext, mime, std::time::Duration::from_secs(120)).await?;

    let attempt = consent.attempts + 1;
    let key = format!("consents/{}_{}.{}", consent.id, attempt, ext);
    storage::save(&state.config.storage_dir, &key, &upload.bytes).await?;

    let score = match_score(&consent.spoken_phrase, &transcript);
    let threshold = state.config.consent_match_threshold;
    let verified = score >= threshold;

    let updated: Consent = sqlx::query_as(&format!(
        "UPDATE consents
         SET attempts = $3, transcript = $4, match_score = $5, consent_audio_key = $6,
             verified = $7, verified_at = CASE WHEN $7 THEN NOW() ELSE NULL END
         WHERE id = $1 AND user_id = $2
         RETURNING {CONSENT_COLUMNS}"
    ))
    .bind(consent.id)
    .bind(auth.user_id)
    .bind(attempt)
    .bind(&transcript)
    .bind(score)
    .bind(&key)
    .bind(verified)
    .fetch_one(&state.db)
    .await?;

    record_audit_log(
        &state.db,
        Some(auth.user_id),
        if verified { "consent_verified" } else { "consent_verification_failed" },
        json!({ "consent_id": consent.id, "score": score, "attempt": attempt }),
    )
    .await;

    Ok(Json(ConsentVerification {
        verified,
        transcript,
        match_score: score,
        threshold,
        attempts_remaining: (max - attempt).max(0),
        consent: updated,
    }))
}

pub async fn get_consents(auth: AuthUser, State(state): State<AppState>) -> ApiResult<Vec<Consent>> {
    let consents: Vec<Consent> = sqlx::query_as(&format!(
        "SELECT {CONSENT_COLUMNS} FROM consents WHERE user_id = $1 ORDER BY created_at DESC"
    ))
    .bind(auth.user_id)
    .fetch_all(&state.db)
    .await?;
    Ok(Json(consents))
}
