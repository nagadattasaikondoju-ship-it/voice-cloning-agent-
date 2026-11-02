use axum::{
    extract::{Multipart, Path, State},
    http::StatusCode,
    Json,
};
use redis::AsyncCommands;
use serde_json::json;
use std::path::PathBuf;
use tokio::fs;
use uuid::Uuid;

use crate::{
    auth::AuthUser,
    db::{record_audit_log, AppState},
    models::{
        CloneWorkerJob, CreateVoiceCloneRequest, DeleteVoiceWorkerJob, VoiceClone,
        VoiceCloneResponse, VoiceSample,
    },
};

pub async fn upload_voice_sample(
    auth: AuthUser,
    State(state): State<AppState>,
    mut multipart: Multipart,
) -> Result<Json<VoiceSample>, (StatusCode, Json<serde_json::Value>)> {
    let mut file_data: Option<Vec<u8>> = None;
    let mut file_name: Option<String> = None;
    let mut mime_type: Option<String> = None;
    let mut duration_seconds: f64 = 15.0; // default estimated duration

    while let Some(field) = multipart.next_field().await.map_err(|_| {
        (StatusCode::BAD_REQUEST, Json(json!({ "message": "Failed to parse multipart field" })))
    })? {
        let name = field.name().unwrap_or("").to_string();
        if name == "audio" || name == "file" || name == "sample_audio" {
            file_name = field.file_name().map(|s| s.to_string());
            mime_type = field.content_type().map(|s| s.to_string());
            let data = field.bytes().await.map_err(|_| {
                (StatusCode::BAD_REQUEST, Json(json!({ "message": "Failed to read audio bytes" })))
            })?;
            file_data = Some(data.to_vec());
        } else if name == "duration" {
            if let Ok(text) = field.text().await {
                if let Ok(dur) = text.parse::<f64>() {
                    duration_seconds = dur;
                }
            }
        }
    }

    let bytes = file_data.ok_or_else(|| {
        (StatusCode::BAD_REQUEST, Json(json!({ "message": "Audio file payload missing" })))
    })?;

    // Check max size: 20 MB (20 * 1024 * 1024 = 20,971,520 bytes)
    if bytes.len() > 20 * 1024 * 1024 {
        return Err((
            StatusCode::PAYLOAD_TOO_LARGE,
            Json(json!({ "message": "Audio file exceeds maximum 20 MB size limit" })),
        ));
    }

    let sample_id = Uuid::new_v4();
    let original_ext = file_name
        .as_deref()
        .and_then(|n| n.split('.').last())
        .unwrap_or("wav");

    // Save to private local storage
    let storage_dir = PathBuf::from(&state.config.storage_dir).join("samples");
    fs::create_dir_all(&storage_dir).await.ok();

    let storage_filename = format!("{}.{}", sample_id, original_ext);
    let storage_path = storage_dir.join(&storage_filename);

    fs::write(&storage_path, &bytes).await.map_err(|e| {
        tracing::error!("Failed to write private audio sample: {:?}", e);
        (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({ "message": "Storage error" })))
    })?;

    let storage_key = format!("samples/{}", storage_filename);
    let resolved_mime = mime_type.unwrap_or_else(|| "audio/wav".to_string());

    let sample: VoiceSample = sqlx::query_as!(
        VoiceSample,
        r#"
        INSERT INTO voice_samples (id, user_id, storage_key, mime_type, duration_seconds, file_size_bytes)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id, user_id, storage_key, mime_type, duration_seconds as "duration_seconds: f64", file_size_bytes, created_at
        "#,
        sample_id,
        auth.user_id,
        storage_key,
        resolved_mime,
        bigdecimal::BigDecimal::try_from(duration_seconds).unwrap_or_default(),
        bytes.len() as i64
    )
    .fetch_one(&state.db)
    .await
    .map_err(|e| {
        tracing::error!("Failed to insert voice sample record: {:?}", e);
        (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({ "message": "Database insert error" })))
    })?;

    record_audit_log(
        &state.db,
        Some(auth.user_id),
        "sample_uploaded",
        json!({ "sample_id": sample.id, "size": bytes.len() }),
        None,
    )
    .await;

    Ok(Json(sample))
}

pub async fn get_voice_samples(
    auth: AuthUser,
    State(state): State<AppState>,
) -> Result<Json<Vec<VoiceSample>>, (StatusCode, Json<serde_json::Value>)> {
    let samples: Vec<VoiceSample> = sqlx::query_as!(
        VoiceSample,
        r#"
        SELECT id, user_id, storage_key, mime_type, duration_seconds as "duration_seconds: f64", file_size_bytes, created_at
        FROM voice_samples
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

    Ok(Json(samples))
}

pub async fn create_voice_clone(
    auth: AuthUser,
    State(state): State<AppState>,
    Json(body): Json<CreateVoiceCloneRequest>,
) -> Result<Json<VoiceCloneResponse>, (StatusCode, Json<serde_json::Value>)> {
    // 1. Mandatory Consent Verification check
    let consent_verified: Option<bool> = sqlx::query_scalar!(
        "SELECT verified FROM consents WHERE id = $1 AND user_id = $2",
        body.consent_id,
        auth.user_id
    )
    .fetch_optional(&state.db)
    .await
    .map_err(|_| {
        (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({ "message": "Consent lookup failure" })))
    })?;

    match consent_verified {
        Some(true) => (),
        Some(false) => {
            return Err((
                StatusCode::FORBIDDEN,
                Json(json!({ "message": "Voice cloning rejected: Spoken consent has not been verified" })),
            ));
        }
        None => {
            return Err((
                StatusCode::FORBIDDEN,
                Json(json!({ "message": "Voice cloning rejected: Valid consent record does not exist" })),
            ));
        }
    }

    // 2. Sample Ownership and existence check
    let sample: VoiceSample = sqlx::query_as!(
        VoiceSample,
        r#"
        SELECT id, user_id, storage_key, mime_type, duration_seconds as "duration_seconds: f64", file_size_bytes, created_at
        FROM voice_samples
        WHERE id = $1 AND user_id = $2
        "#,
        body.sample_id,
        auth.user_id
    )
    .fetch_optional(&state.db)
    .await
    .map_err(|_| {
        (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({ "message": "Sample query error" })))
    })?
    .ok_or_else(|| {
        (StatusCode::NOT_FOUND, Json(json!({ "message": "Voice sample not found or unowned" })))
    })?;

    let clone_id = Uuid::new_v4();
    let requested_id = if body.requested_voice_id.starts_with("voice_") {
        body.requested_voice_id.clone()
    } else {
        format!("voice_{}", body.requested_voice_id)
    };

    let clone_record: VoiceClone = sqlx::query_as!(
        VoiceClone,
        r#"
        INSERT INTO voice_clones (id, user_id, consent_id, sample_id, display_name, minimax_voice_id, status)
        VALUES ($1, $2, $3, $4, $5, $6, 'queued')
        RETURNING id, user_id, consent_id, sample_id, display_name, minimax_voice_id, status, created_at, deleted_at
        "#,
        clone_id,
        auth.user_id,
        body.consent_id,
        body.sample_id,
        body.display_name,
        requested_id
    )
    .fetch_one(&state.db)
    .await
    .map_err(|e| {
        tracing::error!("Failed to create voice clone record: {:?}", e);
        (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({ "message": "Failed to create voice clone" })))
    })?;

    // 3. Publish Job to Redis for the Python worker
    let worker_job = CloneWorkerJob {
        job_id: clone_record.id,
        user_id: auth.user_id,
        sample_storage_path: sample.storage_key,
        requested_voice_id: clone_record.minimax_voice_id.clone(),
        display_name: clone_record.display_name.clone(),
    };

    if let Ok(mut con) = state.redis.get_multiplexed_async_connection().await {
        let job_json = serde_json::to_string(&worker_job).unwrap_or_default();
        let _: Result<(), _> = con.lpush("voice_clone_jobs", job_json).await;
    }

    record_audit_log(
        &state.db,
        Some(auth.user_id),
        "voice_clone_queued",
        json!({ "clone_id": clone_record.id, "voice_id": clone_record.minimax_voice_id }),
        None,
    )
    .await;

    Ok(Json(VoiceCloneResponse {
        id: clone_record.id,
        display_name: clone_record.display_name,
        minimax_voice_id: clone_record.minimax_voice_id,
        status: clone_record.status,
        created_at: clone_record.created_at,
    }))
}

pub async fn get_voice_clones(
    auth: AuthUser,
    State(state): State<AppState>,
) -> Result<Json<Vec<VoiceCloneResponse>>, (StatusCode, Json<serde_json::Value>)> {
    let clones: Vec<VoiceClone> = sqlx::query_as!(
        VoiceClone,
        r#"
        SELECT id, user_id, consent_id, sample_id, display_name, minimax_voice_id, status, created_at, deleted_at
        FROM voice_clones
        WHERE user_id = $1 AND deleted_at IS NULL
        ORDER BY created_at DESC
        "#,
        auth.user_id
    )
    .fetch_all(&state.db)
    .await
    .map_err(|_| {
        (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({ "message": "Database query error" })))
    })?;

    let response = clones
        .into_iter()
        .map(|c| VoiceCloneResponse {
            id: c.id,
            display_name: c.display_name,
            minimax_voice_id: c.minimax_voice_id,
            status: c.status,
            created_at: c.created_at,
        })
        .collect();

    Ok(Json(response))
}

pub async fn get_voice_clone_by_id(
    auth: AuthUser,
    Path(id): Path<Uuid>,
    State(state): State<AppState>,
) -> Result<Json<VoiceCloneResponse>, (StatusCode, Json<serde_json::Value>)> {
    let clone: VoiceClone = sqlx::query_as!(
        VoiceClone,
        r#"
        SELECT id, user_id, consent_id, sample_id, display_name, minimax_voice_id, status, created_at, deleted_at
        FROM voice_clones
        WHERE id = $1 AND user_id = $2 AND deleted_at IS NULL
        "#,
        id,
        auth.user_id
    )
    .fetch_optional(&state.db)
    .await
    .map_err(|_| {
        (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({ "message": "Database error" })))
    })?
    .ok_or_else(|| {
        (StatusCode::NOT_FOUND, Json(json!({ "message": "Voice clone not found" })))
    })?;

    Ok(Json(VoiceCloneResponse {
        id: clone.id,
        display_name: clone.display_name,
        minimax_voice_id: clone.minimax_voice_id,
        status: clone.status,
        created_at: clone.created_at,
    }))
}

pub async fn delete_voice_clone(
    auth: AuthUser,
    Path(id): Path<Uuid>,
    State(state): State<AppState>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let clone: VoiceClone = sqlx::query_as!(
        VoiceClone,
        r#"
        UPDATE voice_clones
        SET deleted_at = NOW(), status = 'deleted'
        WHERE id = $1 AND user_id = $2 AND deleted_at IS NULL
        RETURNING id, user_id, consent_id, sample_id, display_name, minimax_voice_id, status, created_at, deleted_at
        "#,
        id,
        auth.user_id
    )
    .fetch_optional(&state.db)
    .await
    .map_err(|_| {
        (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({ "message": "Database error" })))
    })?
    .ok_or_else(|| {
        (StatusCode::NOT_FOUND, Json(json!({ "message": "Voice clone not found or already deleted" })))
    })?;

    // Enqueue delete job to Python worker for MiniMax Voice Management Delete API
    let delete_job = DeleteVoiceWorkerJob {
        minimax_voice_id: clone.minimax_voice_id.clone(),
        user_id: auth.user_id,
    };

    if let Ok(mut con) = state.redis.get_multiplexed_async_connection().await {
        let job_json = serde_json::to_string(&delete_job).unwrap_or_default();
        let _: Result<(), _> = con.lpush("delete_voice_jobs", job_json).await;
    }

    record_audit_log(
        &state.db,
        Some(auth.user_id),
        "voice_clone_deleted",
        json!({ "clone_id": clone.id, "voice_id": clone.minimax_voice_id }),
        None,
    )
    .await;

    Ok(Json(json!({ "message": "Voice clone deleted and scheduled for MiniMax purge" })))
}
