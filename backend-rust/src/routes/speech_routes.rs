use axum::{
    body::Body,
    extract::{Path, State},
    http::header,
    response::{IntoResponse, Response},
    Json,
};
use serde_json::{json, Value};
use tokio::fs::File;
use tokio_util::io::ReaderStream;
use uuid::Uuid;

use crate::{
    auth::AuthUser,
    db::{enqueue, record_audit_log, AppState},
    error::{ApiError, ApiResult},
    models::{
        GenerateSpeechRequest, GeneratedAudio, SpeechHistoryItem, SpeechJob, SpeechJobResponse, SpeechWorkerJob,
        VoiceClone, CLONE_COLUMNS,
    },
    storage,
};

const MAX_TEXT_CHARS: usize = 5000;

pub async fn generate_speech(
    auth: AuthUser,
    State(state): State<AppState>,
    Json(body): Json<GenerateSpeechRequest>,
) -> ApiResult<SpeechJobResponse> {
    let text = body.text.trim();
    if text.is_empty() {
        return Err(ApiError::bad_request("Text cannot be empty"));
    }
    if text.chars().count() > MAX_TEXT_CHARS {
        return Err(ApiError::bad_request(format!("Text exceeds {MAX_TEXT_CHARS} characters")));
    }

    let clone: VoiceClone = sqlx::query_as(&format!(
        "SELECT {CLONE_COLUMNS} FROM voice_clones WHERE id = $1 AND user_id = $2 AND deleted_at IS NULL"
    ))
    .bind(body.voice_clone_id)
    .bind(auth.user_id)
    .fetch_optional(&state.db)
    .await?
    .ok_or_else(|| ApiError::not_found("Voice clone not found"))?;
    if clone.status != "ready" {
        return Err(ApiError::bad_request(format!("Voice is not ready yet (status: {})", clone.status)));
    }

    let sample_key: String = sqlx::query_scalar("SELECT storage_key FROM voice_samples WHERE id = $1")
        .bind(clone.sample_id)
        .fetch_one(&state.db)
        .await?;

    let speed = body.speed.unwrap_or(1.0).clamp(0.5, 2.0);
    let volume = body.volume.unwrap_or(1.0).clamp(0.1, 2.0);
    let pitch = body.pitch.unwrap_or(0).clamp(-12, 12);

    let job: SpeechJob = sqlx::query_as(
        "INSERT INTO speech_jobs (id, user_id, voice_clone_id, text, speed, volume, pitch, status)
         VALUES ($1, $2, $3, $4, $5, $6, $7, 'queued') RETURNING id, status, error_message",
    )
    .bind(Uuid::new_v4())
    .bind(auth.user_id)
    .bind(clone.id)
    .bind(text)
    .bind(speed)
    .bind(volume)
    .bind(pitch)
    .fetch_one(&state.db)
    .await?;

    let worker_job = SpeechWorkerJob {
        job_id: job.id,
        user_id: auth.user_id,
        engine: clone.engine.clone(),
        voice_id: clone.voice_id.clone(),
        provider_voice_id: clone.provider_voice_id.clone(),
        sample_storage_path: sample_key,
        text: text.to_string(),
        speed,
        volume,
        pitch,
    };
    if let Err(e) = enqueue(&state.redis, "speech_jobs", &worker_job).await {
        sqlx::query("UPDATE speech_jobs SET status = 'failed', error_message = 'Queue unavailable' WHERE id = $1")
            .bind(job.id)
            .execute(&state.db)
            .await?;
        tracing::error!("Failed to enqueue speech job: {e:?}");
        return Err(ApiError::unavailable("Job queue is unavailable. Try again shortly."));
    }

    record_audit_log(
        &state.db,
        Some(auth.user_id),
        "speech_generation_queued",
        json!({ "job_id": job.id, "engine": clone.engine, "chars": text.chars().count() }),
    )
    .await;

    Ok(Json(SpeechJobResponse { job_id: job.id, status: job.status, audio_url: None, error_message: None }))
}

pub async fn get_speech_job_status(
    auth: AuthUser,
    Path(job_id): Path<Uuid>,
    State(state): State<AppState>,
) -> ApiResult<SpeechJobResponse> {
    let job: SpeechJob =
        sqlx::query_as("SELECT id, status, error_message FROM speech_jobs WHERE id = $1 AND user_id = $2")
            .bind(job_id)
            .bind(auth.user_id)
            .fetch_optional(&state.db)
            .await?
            .ok_or_else(|| ApiError::not_found("Job not found"))?;

    let audio_url = if job.status == "ready" {
        sqlx::query_scalar::<_, Uuid>("SELECT id FROM generated_audio WHERE speech_job_id = $1")
            .bind(job.id)
            .fetch_optional(&state.db)
            .await?
            .map(|id| format!("/api/audio/{id}"))
    } else {
        None
    };

    Ok(Json(SpeechJobResponse { job_id: job.id, status: job.status, audio_url, error_message: job.error_message }))
}

pub async fn get_speech_history(auth: AuthUser, State(state): State<AppState>) -> ApiResult<Vec<SpeechHistoryItem>> {
    let mut rows: Vec<SpeechHistoryItem> = sqlx::query_as(
        "SELECT ga.id, ga.speech_job_id, vc.id AS voice_clone_id, vc.display_name AS voice_name,
                vc.engine, sj.text, ga.duration_seconds, ga.created_at
         FROM generated_audio ga
         JOIN speech_jobs sj ON ga.speech_job_id = sj.id
         JOIN voice_clones vc ON sj.voice_clone_id = vc.id
         WHERE ga.user_id = $1
         ORDER BY ga.created_at DESC
         LIMIT 50",
    )
    .bind(auth.user_id)
    .fetch_all(&state.db)
    .await?;
    for r in &mut rows {
        r.audio_url = format!("/api/audio/{}", r.id);
    }
    Ok(Json(rows))
}

pub async fn delete_generated_audio(
    auth: AuthUser,
    Path(audio_id): Path<Uuid>,
    State(state): State<AppState>,
) -> ApiResult<Value> {
    let audio: GeneratedAudio = sqlx::query_as(
        "DELETE FROM generated_audio WHERE id = $1 AND user_id = $2 RETURNING id, storage_key, mime_type",
    )
    .bind(audio_id)
    .bind(auth.user_id)
    .fetch_optional(&state.db)
    .await?
    .ok_or_else(|| ApiError::not_found("Audio not found"))?;

    let _ = tokio::fs::remove_file(storage::resolve(&state.config.storage_dir, &audio.storage_key)).await;
    record_audit_log(&state.db, Some(auth.user_id), "generated_audio_deleted", json!({ "audio_id": audio.id })).await;
    Ok(Json(json!({ "message": "Audio deleted" })))
}

/// Streams a generated clip to its owner only. The dashboard fetches it with the
/// Authorization header and plays it from a blob URL.
pub async fn stream_audio(
    auth: AuthUser,
    Path(audio_id): Path<Uuid>,
    State(state): State<AppState>,
) -> Result<Response, ApiError> {
    let audio: GeneratedAudio =
        sqlx::query_as("SELECT id, storage_key, mime_type FROM generated_audio WHERE id = $1 AND user_id = $2")
            .bind(audio_id)
            .bind(auth.user_id)
            .fetch_optional(&state.db)
            .await?
            .ok_or_else(|| ApiError::not_found("Audio not found"))?;

    let path = storage::resolve(&state.config.storage_dir, &audio.storage_key);
    let file = File::open(&path).await.map_err(|_| ApiError::not_found("Audio file missing"))?;
    let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("mp3").to_string();

    Ok((
        [
            (header::CONTENT_TYPE, audio.mime_type),
            (
                header::CONTENT_DISPOSITION,
                format!("inline; filename=\"ai_generated_{audio_id}.{ext}\""),
            ),
            (header::CACHE_CONTROL, "private, no-store".to_string()),
        ],
        Body::from_stream(ReaderStream::new(file)),
    )
        .into_response())
}
