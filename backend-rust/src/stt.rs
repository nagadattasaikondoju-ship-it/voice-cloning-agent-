//! Client for the speech_pipeline (faster-whisper) service.
use std::time::Duration;

use serde::Deserialize;

use crate::{db::AppState, error::ApiError};

#[derive(Debug, Deserialize)]
struct TranscribeResponse {
    transcript: String,
}

pub async fn transcribe(
    state: &AppState,
    bytes: Vec<u8>,
    ext: &str,
    mime: &str,
    timeout: Duration,
) -> Result<String, ApiError> {
    let part = reqwest::multipart::Part::bytes(bytes)
        .file_name(format!("audio.{ext}"))
        .mime_str(mime)
        .map_err(|e| ApiError::internal("Invalid MIME type", e))?;
    let response = state
        .http
        .post(format!("{}/api/v1/transcribe", state.config.speech_pipeline_url))
        .timeout(timeout)
        .multipart(reqwest::multipart::Form::new().part("file", part))
        .send()
        .await
        .map_err(|e| {
            tracing::error!("Speech pipeline unreachable: {e:?}");
            ApiError::unavailable("Speech recognition service is unavailable. Try again shortly.")
        })?;
    if !response.status().is_success() {
        let status = response.status();
        tracing::error!("Speech pipeline error {status}: {}", response.text().await.unwrap_or_default());
        return Err(if status.is_client_error() {
            ApiError::bad_request("Could not decode this audio. Try another recording or format.")
        } else {
            ApiError::unavailable("Speech recognition failed. Try again shortly.")
        });
    }
    Ok(response
        .json::<TranscribeResponse>()
        .await
        .map_err(|e| ApiError::internal("Bad speech pipeline response", e))?
        .transcript)
}
