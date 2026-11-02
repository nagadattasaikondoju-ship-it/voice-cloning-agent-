use axum::{
    body::Body,
    extract::{Path, State},
    http::{header, HeaderMap, StatusCode},
    response::Response,
    Json,
};
use redis::AsyncCommands;
use serde_json::json;
use std::path::PathBuf;
use tokio::fs::File;
use tokio_util::io::ReaderStream;
use uuid::Uuid;

use crate::{
    auth::AuthUser,
    db::{record_audit_log, AppState},
    models::{
        GenerateSpeechRequest, GeneratedAudio, SpeechHistoryItem, SpeechJob, SpeechJobResponse,
        SpeechWorkerJob, VoiceClone,
    },
};

pub async fn generate_speech(
    auth: AuthUser,
    State(state): State<AppState>,
    Json(body): Json<GenerateSpeechRequest>,
) -> Result<Json<SpeechJobResponse>, (StatusCode, Json<serde_json::Value>)> {
    let text = body.text.trim();
    if text.is_empty() {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({ "message": "Text prompt cannot be empty" })),
        ));
    }

    if text.chars().count() > 5000 {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({ "message": "Text prompt exceeds maximum 5000 characters" })),
        ));
    }

    // Verify user owns the voice clone
    let voice_clone: VoiceClone = sqlx::query_as!(
        VoiceClone,
        r#"
        SELECT id, user_id, consent_id, sample_id, display_name, minimax_voice_id, status, created_at, deleted_at
        FROM voice_clones
        WHERE (minimax_voice_id = $1 OR id::text = $1) AND user_id = $2 AND deleted_at IS NULL
        "#,
        body.voice_id,
        auth.user_id
    )
    .fetch_optional(&state.db)
    .await
    .map_err(|_| {
        (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({ "message": "Database query error" })))
    })?
    .ok_or_else(|| {
        (StatusCode::FORBIDDEN, Json(json!({ "message": "Specified voice clone not found or unauthorized" })))
    })?;

    let speed = body.speed.unwrap_or(1.0).clamp(0.5, 2.0);
    let volume = body.volume.unwrap_or(1.0).clamp(0.1, 2.0);
    let pitch = body.pitch.unwrap_or(0).clamp(-12, 12);

    let job_id = Uuid::new_v4();

    let job: SpeechJob = sqlx::query_as!(
        SpeechJob,
        r#"
        INSERT INTO speech_jobs (id, user_id, voice_clone_id, text, speed, volume, pitch, status)
        VALUES ($1, $2, $3, $4, $5, $6, $7, 'queued')
        RETURNING id, user_id, voice_clone_id, text, speed as "speed: f64", volume as "volume: f64", pitch, status, error_message, created_at
        "#,
        job_id,
        auth.user_id,
        voice_clone.id,
        text,
        bigdecimal::BigDecimal::try_from(speed).unwrap_or_default(),
        bigdecimal::BigDecimal::try_from(volume).unwrap_or_default(),
        pitch
    )
    .fetch_one(&state.db)
    .await
    .map_err(|e| {
        tracing::error!("Failed to insert speech job: {:?}", e);
        (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({ "message": "Failed to create speech job" })))
    })?;

    // Enqueue to Redis for Python worker
    let worker_job = SpeechWorkerJob {
        job_id: job.id,
        user_id: auth.user_id,
        minimax_voice_id: voice_clone.minimax_voice_id,
        text: text.to_string(),
        speed,
        volume,
        pitch,
    };

    if let Ok(mut con) = state.redis.get_multiplexed_async_connection().await {
        let job_json = serde_json::to_string(&worker_job).unwrap_or_default();
        let _: Result<(), _> = con.lpush("speech_jobs", job_json).await;
    }

    record_audit_log(
        &state.db,
        Some(auth.user_id),
        "speech_generation_queued",
        json!({ "job_id": job.id, "char_count": text.len() }),
        None,
    )
    .await;

    Ok(Json(SpeechJobResponse {
        job_id: job.id,
        status: job.status,
        audio_url: None,
    }))
}

pub async fn get_speech_job_status(
    auth: AuthUser,
    Path(job_id): Path<Uuid>,
    State(state): State<AppState>,
) -> Result<Json<SpeechJobResponse>, (StatusCode, Json<serde_json::Value>)> {
    let job: SpeechJob = sqlx::query_as!(
        SpeechJob,
        r#"
        SELECT id, user_id, voice_clone_id, text, speed as "speed: f64", volume as "volume: f64", pitch, status, error_message, created_at
        FROM speech_jobs
        WHERE id = $1 AND user_id = $2
        "#,
        job_id,
        auth.user_id
    )
    .fetch_optional(&state.db)
    .await
    .map_err(|_| {
        (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({ "message": "Database error" })))
    })?
    .ok_or_else(|| {
        (StatusCode::NOT_FOUND, Json(json!({ "message": "Job not found" })))
    })?;

    let audio_url = if job.status == "ready" {
        let audio: Option<GeneratedAudio> = sqlx::query_as!(
            GeneratedAudio,
            r#"
            SELECT id, speech_job_id, user_id, storage_key, duration_seconds as "duration_seconds: f64", file_size_bytes, created_at
            FROM generated_audio
            WHERE speech_job_id = $1
            "#,
            job.id
        )
        .fetch_optional(&state.db)
        .await
        .ok()
        .flatten();

        audio.map(|a| format!("/api/audio/{}", a.id))
    } else {
        None
    };

    Ok(Json(SpeechJobResponse {
        job_id: job.id,
        status: job.status,
        audio_url,
    }))
}

pub async fn get_speech_history(
    auth: AuthUser,
    State(state): State<AppState>,
) -> Result<Json<Vec<SpeechHistoryItem>>, (StatusCode, Json<serde_json::Value>)> {
    struct RawHistory {
        id: Uuid,
        speech_job_id: Uuid,
        voice_id: String,
        text: String,
        duration_seconds: Option<f64>,
        created_at: chrono::DateTime<chrono::Utc>,
    }

    let rows: Vec<RawHistory> = sqlx::query_as!(
        RawHistory,
        r#"
        SELECT
            ga.id as id,
            ga.speech_job_id as speech_job_id,
            vc.minimax_voice_id as voice_id,
            sj.text as text,
            ga.duration_seconds as "duration_seconds: f64",
            ga.created_at as created_at
        FROM generated_audio ga
        JOIN speech_jobs sj ON ga.speech_job_id = sj.id
        JOIN voice_clones vc ON sj.voice_clone_id = vc.id
        WHERE ga.user_id = $1
        ORDER BY ga.created_at DESC
        LIMIT 50
        "#,
        auth.user_id
    )
    .fetch_all(&state.db)
    .await
    .map_err(|e| {
        tracing::error!("Failed to fetch speech history: {:?}", e);
        (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({ "message": "Database query error" })))
    })?;

    let items = rows
        .into_iter()
        .map(|r| SpeechHistoryItem {
            id: r.id,
            speech_job_id: r.speech_job_id,
            voice_id: r.voice_id,
            text: r.text,
            audio_url: format!("/api/audio/{}", r.id),
            duration_seconds: r.duration_seconds,
            created_at: r.created_at,
        })
        .collect();

    Ok(Json(items))
}

pub async fn delete_generated_audio(
    auth: AuthUser,
    Path(audio_id): Path<Uuid>,
    State(state): State<AppState>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let audio: Option<GeneratedAudio> = sqlx::query_as!(
        GeneratedAudio,
        r#"
        SELECT id, speech_job_id, user_id, storage_key, duration_seconds as "duration_seconds: f64", file_size_bytes, created_at
        FROM generated_audio
        WHERE id = $1 AND user_id = $2
        "#,
        audio_id,
        auth.user_id
    )
    .fetch_optional(&state.db)
    .await
    .map_err(|_| {
        (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({ "message": "Database error" })))
    })?;

    if let Some(record) = audio {
        // Delete physical file if exists
        let path = PathBuf::from(&state.config.storage_dir).join(&record.storage_key);
        let _ = tokio::fs::remove_file(path).await;

        let _ = sqlx::query!("DELETE FROM generated_audio WHERE id = $1", audio_id)
            .execute(&state.db)
            .await;

        record_audit_log(
            &state.db,
            Some(auth.user_id),
            "generated_audio_deleted",
            json!({ "audio_id": audio_id }),
            None,
        )
        .await;
    }

    Ok(Json(json!({ "message": "Generated audio removed" })))
}

pub async fn stream_audio(
    Path(audio_id): Path<Uuid>,
    State(state): State<AppState>,
) -> Result<Response, StatusCode> {
    let audio: GeneratedAudio = sqlx::query_as!(
        GeneratedAudio,
        r#"
        SELECT id, speech_job_id, user_id, storage_key, duration_seconds as "duration_seconds: f64", file_size_bytes, created_at
        FROM generated_audio
        WHERE id = $1
        "#,
        audio_id
    )
    .fetch_optional(&state.db)
    .await
    .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?
    .ok_or(StatusCode::NOT_FOUND)?;

    let path = PathBuf::from(&state.config.storage_dir).join(&audio.storage_key);
    let file = File::open(&path).await.map_err(|_| StatusCode::NOT_FOUND)?;

    let stream = ReaderStream::new(file);
    let body = Body::from_stream(stream);

    let mut headers = HeaderMap::new();
    headers.insert(header::CONTENT_TYPE, "audio/mpeg".parse().unwrap());
    headers.insert(
        header::CONTENT_DISPOSITION,
        format!("inline; filename=\"synthesized_{}.mp3\"", audio_id)
            .parse()
            .unwrap(),
    );

    Ok((headers, body).into_response())
}
