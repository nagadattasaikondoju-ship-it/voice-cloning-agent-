pub mod auth_routes;
pub mod clone_routes;
pub mod consent_routes;
pub mod meta_routes;
pub mod speech_routes;

use std::collections::HashMap;

use axum::extract::Multipart;

use crate::error::ApiError;

pub const MAX_AUDIO_BYTES: usize = 20 * 1024 * 1024;

pub struct AudioUpload {
    pub bytes: Vec<u8>,
    pub file_name: Option<String>,
    pub content_type: Option<String>,
    pub fields: HashMap<String, String>,
}

/// Reads one audio file (field `audio`, `file` or `sample_audio`) plus any text fields.
pub async fn read_audio_upload(mut multipart: Multipart) -> Result<AudioUpload, ApiError> {
    let mut upload = AudioUpload { bytes: Vec::new(), file_name: None, content_type: None, fields: HashMap::new() };
    while let Some(field) = multipart
        .next_field()
        .await
        .map_err(|_| ApiError::bad_request("Malformed multipart body"))?
    {
        let name = field.name().unwrap_or_default().to_string();
        if matches!(name.as_str(), "audio" | "file" | "sample_audio") {
            upload.file_name = field.file_name().map(str::to_string);
            upload.content_type = field.content_type().map(str::to_string);
            let data = field
                .bytes()
                .await
                .map_err(|_| ApiError::bad_request("Failed to read audio bytes (file may exceed 20 MB)"))?;
            upload.bytes = data.to_vec();
        } else if let Ok(text) = field.text().await {
            upload.fields.insert(name, text);
        }
    }
    if upload.bytes.is_empty() {
        return Err(ApiError::bad_request("Audio file is missing or empty"));
    }
    if upload.bytes.len() > MAX_AUDIO_BYTES {
        return Err(ApiError::new(axum::http::StatusCode::PAYLOAD_TOO_LARGE, "Audio file exceeds the 20 MB limit"));
    }
    Ok(upload)
}
