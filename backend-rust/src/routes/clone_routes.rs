use axum::{
    extract::{Multipart, Path, State},
    Json,
};
use serde_json::{json, Value};
use uuid::Uuid;

use crate::{
    auth::AuthUser,
    db::{enqueue, record_audit_log, AppState},
    error::{ApiError, ApiResult},
    models::{
        CloneWorkerJob, CreateVoiceCloneRequest, DeleteVoiceWorkerJob, VoiceClone, VoiceSample, CLONE_COLUMNS,
    },
    routes::{meta_routes::require_engine, read_audio_upload},
    storage,
};

/// Chatterbox needs more than 5 s of speech; silence is trimmed by the worker.
const MIN_SAMPLE_SECONDS: f64 = 6.0;
const SAMPLE_COLUMNS: &str = "id, user_id, storage_key, mime_type, duration_seconds, file_size_bytes, created_at";

pub async fn upload_voice_sample(
    auth: AuthUser,
    State(state): State<AppState>,
    multipart: Multipart,
) -> ApiResult<VoiceSample> {
    let upload = read_audio_upload(multipart).await?;
    let (ext, mime) = storage::audio_mime_for(upload.file_name.as_deref(), upload.content_type.as_deref())
        .ok_or_else(|| ApiError::bad_request("Unsupported audio format (use mp3, m4a, wav, webm or ogg)"))?;

    let duration: f64 = upload.fields.get("duration").and_then(|d| d.parse().ok()).unwrap_or(0.0);
    if duration > 0.0 && !(MIN_SAMPLE_SECONDS..=300.0).contains(&duration) {
        return Err(ApiError::bad_request("Voice samples must be between 6 seconds and 5 minutes long"));
    }

    let sample_id = Uuid::new_v4();
    let key = format!("samples/{sample_id}.{ext}");
    storage::save(&state.config.storage_dir, &key, &upload.bytes).await?;

    let sample: VoiceSample = sqlx::query_as(&format!(
        "INSERT INTO voice_samples (id, user_id, storage_key, mime_type, duration_seconds, file_size_bytes)
         VALUES ($1, $2, $3, $4, $5, $6) RETURNING {SAMPLE_COLUMNS}"
    ))
    .bind(sample_id)
    .bind(auth.user_id)
    .bind(&key)
    .bind(mime)
    .bind(duration)
    .bind(upload.bytes.len() as i64)
    .fetch_one(&state.db)
    .await?;

    record_audit_log(&state.db, Some(auth.user_id), "sample_uploaded", json!({ "sample_id": sample.id })).await;
    Ok(Json(sample))
}

pub async fn get_voice_samples(auth: AuthUser, State(state): State<AppState>) -> ApiResult<Vec<VoiceSample>> {
    let samples = sqlx::query_as(&format!(
        "SELECT {SAMPLE_COLUMNS} FROM voice_samples WHERE user_id = $1 ORDER BY created_at DESC"
    ))
    .bind(auth.user_id)
    .fetch_all(&state.db)
    .await?;
    Ok(Json(samples))
}

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

    // 1. Consent must belong to this user and have passed speech verification.
    let verified: Option<bool> = sqlx::query_scalar("SELECT verified FROM consents WHERE id = $1 AND user_id = $2")
        .bind(body.consent_id)
        .bind(auth.user_id)
        .fetch_optional(&state.db)
        .await?;
    match verified {
        Some(true) => {}
        Some(false) => return Err(ApiError::forbidden("Voice cloning rejected: spoken consent has not been verified")),
        None => return Err(ApiError::forbidden("Voice cloning rejected: consent record not found")),
    }

    // 2. The sample must belong to this user.
    let sample: VoiceSample = sqlx::query_as(&format!(
        "SELECT {SAMPLE_COLUMNS} FROM voice_samples WHERE id = $1 AND user_id = $2"
    ))
    .bind(body.sample_id)
    .bind(auth.user_id)
    .fetch_optional(&state.db)
    .await?
    .ok_or_else(|| ApiError::not_found("Voice sample not found"))?;

    let voice_id = format!("voice_{}", &Uuid::new_v4().simple().to_string()[..20]);

    let clone: VoiceClone = sqlx::query_as(&format!(
        "INSERT INTO voice_clones (id, user_id, consent_id, sample_id, display_name, voice_id, engine, status)
         VALUES ($1, $2, $3, $4, $5, $6, 'chatterbox', 'queued') RETURNING {CLONE_COLUMNS}"
    ))
    .bind(Uuid::new_v4())
    .bind(auth.user_id)
    .bind(body.consent_id)
    .bind(sample.id)
    .bind(display_name)
    .bind(&voice_id)
    .fetch_one(&state.db)
    .await?;

    let job = CloneWorkerJob {
        job_id: clone.id,
        user_id: auth.user_id,
        voice_id,
        sample_storage_path: sample.storage_key,
    };
    if let Err(e) = enqueue(&state.redis, "voice_clone_jobs", &job).await {
        sqlx::query("UPDATE voice_clones SET status = 'failed', error_message = 'Queue unavailable' WHERE id = $1")
            .bind(clone.id)
            .execute(&state.db)
            .await?;
        tracing::error!("Failed to enqueue clone job: {e:?}");
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
