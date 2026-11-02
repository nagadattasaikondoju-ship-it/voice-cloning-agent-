use std::path::{Path, PathBuf};

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

/// Writes bytes under `<storage_dir>/<key>`; keys are generated server-side.
pub async fn save(storage_dir: &str, key: &str, bytes: &[u8]) -> Result<PathBuf, ApiError> {
    let path = PathBuf::from(storage_dir).join(key);
    if let Some(parent) = path.parent() {
        tokio::fs::create_dir_all(parent)
            .await
            .map_err(|e| ApiError::internal("Failed to create storage dir", e))?;
    }
    tokio::fs::write(&path, bytes)
        .await
        .map_err(|e| ApiError::internal("Failed to write audio file", e))?;
    Ok(path)
}

pub fn resolve(storage_dir: &str, key: &str) -> PathBuf {
    PathBuf::from(storage_dir).join(key)
}
