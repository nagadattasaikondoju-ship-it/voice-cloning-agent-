use std::time::Duration;

use axum::{extract::Multipart, extract::State, Json};
use serde_json::{json, Value};

use crate::{
    auth::AuthUser,
    db::{record_audit_log, AppState},
    error::{ApiError, ApiResult},
    routes::read_audio_upload,
    storage, stt,
};

/// Turn an uploaded recording into editable script text for text-to-speech.
/// The audio is not stored.
pub async fn transcribe_audio(auth: AuthUser, State(state): State<AppState>, multipart: Multipart) -> ApiResult<Value> {
    let upload = read_audio_upload(multipart).await?;
    let (ext, mime) = storage::audio_mime_for(upload.file_name.as_deref(), upload.content_type.as_deref())
        .ok_or_else(|| ApiError::bad_request("Unsupported audio format (use mp3, m4a, wav, webm or ogg)"))?;
    let size = upload.bytes.len();
    let transcript = stt::transcribe(&state, upload.bytes, ext, mime, Duration::from_secs(900)).await?;
    record_audit_log(&state.db, Some(auth.user_id), "audio_transcribed", json!({ "bytes": size })).await;
    Ok(Json(json!({ "transcript": transcript })))
}
