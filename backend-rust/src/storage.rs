//! Audio storage. Files live in the `blobs` table so the app works on hosts without a
//! persistent disk. The Python worker reads and writes the same table.
use std::path::Path;

use sqlx::PgPool;
use uuid::Uuid;

use crate::error::ApiError;

/// Allowed audio uploads: extension -> canonical MIME type.
pub fn audio_mime_for(file_name: Option<&str>, declared: Option<&str>) -> Option<(&'static str, &'static str)> {
    let ext = file_name
        .and_then(|n| Path::new(n).extension())
        .and_then(|e| e.to_str())
        .map(|e| e.to_ascii_lowercase());
    let by_ext = match ext.as_deref() {
        Some("mp3") => Some(("mp3", "audio/mpeg")),
        Some("m4a") | Some("mp4") => Some(("m4a", "audio/mp4")),
        Some("wav") => Some(("wav", "audio/wav")),
        Some("webm") => Some(("webm", "audio/webm")),
        Some("ogg") | Some("oga") => Some(("ogg", "audio/ogg")),
        _ => None,
    };
    by_ext.or_else(|| {
        let d = declared?.split(';').next()?.trim().to_ascii_lowercase();
        match d.as_str() {
            "audio/mpeg" | "audio/mp3" => Some(("mp3", "audio/mpeg")),
            "audio/mp4" | "audio/m4a" | "audio/x-m4a" => Some(("m4a", "audio/mp4")),
            "audio/wav" | "audio/x-wav" | "audio/wave" => Some(("wav", "audio/wav")),
            "audio/webm" => Some(("webm", "audio/webm")),
            "audio/ogg" => Some(("ogg", "audio/ogg")),
            _ => None,
        }
    })
}

/// Stores bytes under `key` (keys are generated server-side).
pub async fn save(db: &PgPool, user_id: Uuid, key: &str, mime: &str, bytes: &[u8]) -> Result<(), ApiError> {
    sqlx::query(
        "INSERT INTO blobs (key, user_id, mime_type, data) VALUES ($1, $2, $3, $4)
         ON CONFLICT (key) DO UPDATE SET data = EXCLUDED.data, mime_type = EXCLUDED.mime_type",
    )
    .bind(key)
    .bind(user_id)
    .bind(mime)
    .bind(bytes)
    .execute(db)
    .await
    .map_err(|e| ApiError::internal("Failed to store audio", e))?;
    Ok(())
}

pub async fn load(db: &PgPool, key: &str) -> Result<Option<Vec<u8>>, ApiError> {
    Ok(sqlx::query_scalar("SELECT data FROM blobs WHERE key = $1").bind(key).fetch_optional(db).await?)
}

pub async fn size(db: &PgPool, key: &str) -> Result<Option<i64>, ApiError> {
    Ok(sqlx::query_scalar("SELECT octet_length(data)::BIGINT FROM blobs WHERE key = $1")
        .bind(key)
        .fetch_optional(db)
        .await?)
}

pub async fn delete(db: &PgPool, key: &str) -> Result<(), ApiError> {
    sqlx::query("DELETE FROM blobs WHERE key = $1").bind(key).execute(db).await?;
    Ok(())
}
