use axum::{
    extract::{Path, State},
    Json,
};
use serde_json::{json, Value};
use uuid::Uuid;

use crate::{
    auth::AuthUser,
    db::{enqueue, record_audit_log, AppState},
    error::{ApiError, ApiResult},
    models::{CloneWorkerJob, CreateVoiceCloneRequest, DeleteVoiceWorkerJob, VoiceClone, CLONE_COLUMNS},
    routes::meta_routes::require_engine,
    storage,
};

/// Creates a voice from a verified consent. The consent recording itself is the voice sample,
/// so the cloned voice is the one that read the server's random phrase. Each consent makes one voice.
pub async fn create_voice_clone(
    auth: AuthUser,
    State(state): State<AppState>,
    Json(body): Json<CreateVoiceCloneRequest>,
) -> ApiResult<VoiceClone> {
    let display_name = body.display_name.trim();
    if display_name.is_empty() || display_name.chars().count() > 80 {
        return Err(ApiError::bad_request("Voice name must be 1–80 characters"));
    }
    require_engine(&state).await?;

    let mut tx = state.db.begin().await?;

    // Claim the consent atomically: it must be this user's, verified, recorded, and unused.
    let claimed: Option<(String, Option<String>)> = sqlx::query_as(
        "UPDATE consents SET used_at = NOW()
         WHERE id = $1 AND user_id = $2 AND verified AND used_at IS NULL AND consent_audio_key IS NOT NULL
         RETURNING consent_audio_key, transcript",
    )
    .bind(body.consent_id)
    .bind(auth.user_id)
    .fetch_optional(&mut *tx)
    .await?;

    let Some((audio_key, transcript)) = claimed else {
        let status: Option<(bool, bool)> =
            sqlx::query_as("SELECT verified, used_at IS NOT NULL FROM consents WHERE id = $1 AND user_id = $2")
                .bind(body.consent_id)
                .bind(auth.user_id)
                .fetch_optional(&mut *tx)
                .await?;
        return Err(match status {
            None => ApiError::forbidden("Voice cloning rejected: consent record not found"),
            Some((false, _)) => ApiError::forbidden("Voice cloning rejected: spoken consent has not been verified"),
            Some((true, true)) => ApiError::forbidden("This consent was already used to create a voice. Record a new phrase."),
            Some((true, false)) => ApiError::forbidden("Voice cloning rejected: the consent recording is missing"),
        });
    };

    let size = tokio::fs::metadata(storage::resolve(&state.config.storage_dir, &audio_key))
        .await
        .map(|m| m.len() as i64)
        .map_err(|_| ApiError::bad_request("The consent recording is missing. Record a new phrase."))?;
    let mime = storage::audio_mime_for(Some(&audio_key), None).map(|(_, m)| m).unwrap_or("audio/webm");

    let sample_id = Uuid::new_v4();
    sqlx::query(
        "INSERT INTO voice_samples (id, user_id, storage_key, mime_type, duration_seconds, file_size_bytes)
         VALUES ($1, $2, $3, $4, 0, $5)",
    )
    .bind(sample_id)
    .bind(auth.user_id)
    .bind(&audio_key)
    .bind(mime)
    .bind(size)
    .execute(&mut *tx)
    .await?;

    let voice_id = format!("voice_{}", &Uuid::new_v4().simple().to_string()[..20]);
    let clone: VoiceClone = sqlx::query_as(&format!(
        "INSERT INTO voice_clones (id, user_id, consent_id, sample_id, display_name, voice_id, engine, status)
         VALUES ($1, $2, $3, $4, $5, $6, 'sarvam', 'queued') RETURNING {CLONE_COLUMNS}"
    ))
    .bind(Uuid::new_v4())
    .bind(auth.user_id)
    .bind(body.consent_id)
    .bind(sample_id)
    .bind(display_name)
    .bind(&voice_id)
    .fetch_one(&mut *tx)
    .await?;
    tx.commit().await?;

    let job = CloneWorkerJob {
        job_id: clone.id,
        user_id: auth.user_id,
        voice_id,
        sample_storage_path: audio_key,
        reference_text: transcript,
    };
    if let Err(e) = enqueue(&state.redis, "voice_clone_jobs", &job).await {
        tracing::error!("Failed to enqueue clone job: {e:?}");
        // Give the consent back so the user can retry without re-recording.
        sqlx::query("UPDATE voice_clones SET status = 'failed', error_message = 'Queue unavailable', deleted_at = NOW() WHERE id = $1")
            .bind(clone.id)
            .execute(&state.db)
            .await?;
        sqlx::query("UPDATE consents SET used_at = NULL WHERE id = $1")
            .bind(body.consent_id)
            .execute(&state.db)
            .await?;
        return Err(ApiError::unavailable("Job queue is unavailable. Try again shortly."));
    }

    record_audit_log(
        &state.db,
        Some(auth.user_id),
        "voice_clone_queued",
        json!({ "clone_id": clone.id, "consent_id": body.consent_id }),
    )
    .await;
    Ok(Json(clone))
}

pub async fn get_voice_clones(auth: AuthUser, State(state): State<AppState>) -> ApiResult<Vec<VoiceClone>> {
    let clones = sqlx::query_as(&format!(
        "SELECT {CLONE_COLUMNS} FROM voice_clones WHERE user_id = $1 AND deleted_at IS NULL ORDER BY created_at DESC"
    ))
    .bind(auth.user_id)
    .fetch_all(&state.db)
    .await?;
    Ok(Json(clones))
}

pub async fn get_voice_clone_by_id(
    auth: AuthUser,
    Path(id): Path<Uuid>,
    State(state): State<AppState>,
) -> ApiResult<VoiceClone> {
    let clone = sqlx::query_as(&format!(
        "SELECT {CLONE_COLUMNS} FROM voice_clones WHERE id = $1 AND user_id = $2 AND deleted_at IS NULL"
    ))
    .bind(id)
    .bind(auth.user_id)
    .fetch_optional(&state.db)
    .await?
    .ok_or_else(|| ApiError::not_found("Voice clone not found"))?;
    Ok(Json(clone))
}

pub async fn delete_voice_clone(
    auth: AuthUser,
    Path(id): Path<Uuid>,
    State(state): State<AppState>,
) -> ApiResult<Value> {
    let clone: VoiceClone = sqlx::query_as(&format!(
        "UPDATE voice_clones SET deleted_at = NOW(), status = 'deleted'
         WHERE id = $1 AND user_id = $2 AND deleted_at IS NULL RETURNING {CLONE_COLUMNS}"
    ))
    .bind(id)
    .bind(auth.user_id)
    .fetch_optional(&state.db)
    .await?
    .ok_or_else(|| ApiError::not_found("Voice clone not found or already deleted"))?;

    let job = DeleteVoiceWorkerJob { user_id: auth.user_id, voice_id: clone.voice_id.clone() };
    if let Err(e) = enqueue(&state.redis, "delete_voice_jobs", &job).await {
        tracing::error!("Failed to enqueue reference delete for {}: {e:?}", clone.id);
    }

    record_audit_log(
        &state.db,
        Some(auth.user_id),
        "voice_clone_deleted",
        json!({ "clone_id": clone.id }),
    )
    .await;
    Ok(Json(json!({ "message": "Voice clone deleted" })))
}
