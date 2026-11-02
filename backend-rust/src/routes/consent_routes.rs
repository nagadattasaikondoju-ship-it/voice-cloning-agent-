use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use serde_json::json;
use uuid::Uuid;

use crate::{
    auth::AuthUser,
    db::{record_audit_log, AppState},
    models::{Consent, ConsentResponse, CreateConsentRequest},
};

pub async fn create_consent(
    auth: AuthUser,
    State(state): State<AppState>,
    Json(body): Json<CreateConsentRequest>,
) -> Result<Json<ConsentResponse>, (StatusCode, Json<serde_json::Value>)> {
    if body.spoken_phrase.trim().is_empty() || body.consent_audio_url.trim().is_empty() {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({ "message": "spoken_phrase and consent_audio_url are required" })),
        ));
    }

    let consent_id = Uuid::new_v4();
    let version = body.consent_version.unwrap_or_else(|| "v1.0".to_string());

    let consent: Consent = sqlx::query_as!(
        Consent,
        r#"
        INSERT INTO consents (id, user_id, consent_audio_url, spoken_phrase, consent_version, verified)
        VALUES ($1, $2, $3, $4, $5, FALSE)
        RETURNING id, user_id, consent_audio_url, spoken_phrase, consent_version, verified, created_at
        "#,
        consent_id,
        auth.user_id,
        body.consent_audio_url,
        body.spoken_phrase,
        version
    )
    .fetch_one(&state.db)
    .await
    .map_err(|e| {
        tracing::error!("Failed to save consent: {:?}", e);
        (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({ "message": "Failed to record consent" })))
    })?;

    record_audit_log(
        &state.db,
        Some(auth.user_id),
        "consent_created",
        json!({ "consent_id": consent.id, "version": consent.consent_version }),
        None,
    )
    .await;

    Ok(Json(ConsentResponse {
        id: consent.id,
        spoken_phrase: consent.spoken_phrase,
        consent_version: consent.consent_version,
        verified: consent.verified,
        created_at: consent.created_at,
    }))
}

pub async fn verify_consent(
    auth: AuthUser,
    Path(consent_id): Path<Uuid>,
    State(state): State<AppState>,
) -> Result<Json<ConsentResponse>, (StatusCode, Json<serde_json::Value>)> {
    let consent: Consent = sqlx::query_as!(
        Consent,
        r#"
        UPDATE consents
        SET verified = TRUE
        WHERE id = $1 AND user_id = $2
        RETURNING id, user_id, consent_audio_url, spoken_phrase, consent_version, verified, created_at
        "#,
        consent_id,
        auth.user_id
    )
    .fetch_optional(&state.db)
    .await
    .map_err(|_| {
        (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({ "message": "Database error" })))
    })?
    .ok_or_else(|| {
        (StatusCode::NOT_FOUND, Json(json!({ "message": "Consent record not found" })))
    })?;

    record_audit_log(
        &state.db,
        Some(auth.user_id),
        "consent_verified",
        json!({ "consent_id": consent.id }),
        None,
    )
    .await;

    Ok(Json(ConsentResponse {
        id: consent.id,
        spoken_phrase: consent.spoken_phrase,
        consent_version: consent.consent_version,
        verified: consent.verified,
        created_at: consent.created_at,
    }))
}

pub async fn get_consents(
    auth: AuthUser,
    State(state): State<AppState>,
) -> Result<Json<Vec<ConsentResponse>>, (StatusCode, Json<serde_json::Value>)> {
    let consents: Vec<Consent> = sqlx::query_as!(
        Consent,
        r#"
        SELECT id, user_id, consent_audio_url, spoken_phrase, consent_version, verified, created_at
        FROM consents
        WHERE user_id = $1
        ORDER BY created_at DESC
        "#,
        auth.user_id
    )
    .fetch_all(&state.db)
    .await
    .map_err(|_| {
        (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({ "message": "Database query error" })))
    })?;

    let response = consents
        .into_iter()
        .map(|c| ConsentResponse {
            id: c.id,
            spoken_phrase: c.spoken_phrase,
            consent_version: c.consent_version,
            verified: c.verified,
            created_at: c.created_at,
        })
        .collect();

    Ok(Json(response))
}
