//! Speech-to-text with the Sarvam AI API (https://docs.sarvam.ai/api-reference/speech-to-text/transcribe).
//!
//! The REST endpoint is meant for clips under ~30 s, so every upload is converted with ffmpeg
//! to 16 kHz mono WAV and cut into 25 s segments, which are transcribed in order and joined.
use std::{path::Path, time::Duration};

use serde::Deserialize;
use tokio::process::Command;
use uuid::Uuid;

use crate::{db::AppState, error::ApiError};

const SEGMENT_SECONDS: u32 = 25;
const MAX_ATTEMPTS: u32 = 3;

#[derive(Debug, Deserialize)]
struct SarvamTranscript {
    transcript: String,
}

/// Transcribes `bytes` (any format ffmpeg reads). `language` is a code such as `en-IN`;
/// `None` lets Sarvam detect it. Audio longer than `max_seconds` is rejected.
pub async fn transcribe(
    state: &AppState,
    bytes: &[u8],
    ext: &str,
    language: Option<&str>,
    max_seconds: f64,
) -> Result<(String, f64), ApiError> {
    if state.config.sarvam_api_key.is_empty() {
        return Err(ApiError::unavailable("Speech recognition is not configured (SARVAM_API_KEY is missing)."));
    }

    let dir = std::env::temp_dir().join(format!("stt-{}", Uuid::new_v4()));
    tokio::fs::create_dir_all(&dir).await.map_err(|e| ApiError::internal("Failed to create temp dir", e))?;
    let result = transcribe_in(state, &dir, bytes, ext, language, max_seconds).await;
    let _ = tokio::fs::remove_dir_all(&dir).await;
    result
}

async fn transcribe_in(
    state: &AppState,
    dir: &Path,
    bytes: &[u8],
    ext: &str,
    language: Option<&str>,
    max_seconds: f64,
) -> Result<(String, f64), ApiError> {
    let input = dir.join(format!("input.{ext}"));
    tokio::fs::write(&input, bytes).await.map_err(|e| ApiError::internal("Failed to write temp audio", e))?;

    let seconds = duration_seconds(&input).await?;
    if seconds > max_seconds {
        return Err(ApiError::bad_request(format!(
            "Audio is {:.0} s long; the limit here is {:.0} s.",
            seconds, max_seconds
        )));
    }

    let pattern = dir.join("seg_%03d.wav");
    let out = Command::new("ffmpeg")
        .args(["-y", "-loglevel", "error", "-i"])
        .arg(&input)
        .args(["-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-f", "segment", "-segment_time"])
        .arg(SEGMENT_SECONDS.to_string())
        .arg(&pattern)
        .output()
        .await
        .map_err(|e| ApiError::internal("ffmpeg could not start", e))?;
    if !out.status.success() {
        tracing::warn!("ffmpeg failed: {}", String::from_utf8_lossy(&out.stderr));
        return Err(ApiError::bad_request("Could not decode this audio. Try another recording or format."));
    }

    let mut segments = Vec::new();
    let mut entries = tokio::fs::read_dir(dir).await.map_err(|e| ApiError::internal("Failed to list segments", e))?;
    while let Some(entry) = entries.next_entry().await.map_err(|e| ApiError::internal("Failed to list segments", e))? {
        let name = entry.file_name().to_string_lossy().to_string();
        if name.starts_with("seg_") {
            segments.push(entry.path());
        }
    }
    segments.sort();

    let mut parts = Vec::new();
    let mut total_seconds = 0.0;
    for seg in segments {
        let wav = tokio::fs::read(&seg).await.map_err(|e| ApiError::internal("Failed to read segment", e))?;
        let seg_seconds = wav.len().saturating_sub(44) as f64 / 32_000.0; // 16 kHz, 16-bit mono
        total_seconds += seg_seconds;
        if total_seconds > max_seconds + 1.0 {
            return Err(ApiError::bad_request(format!(
                "Audio is longer than the {:.0} s allowed here.",
                max_seconds
            )));
        }
        if wav.len() <= 44 + 3200 {
            continue; // header plus < 0.1 s of audio
        }
        let text = transcribe_segment(state, wav, language).await?;
        if !text.trim().is_empty() {
            parts.push(text.trim().to_string());
        }
    }
    Ok((parts.join(" "), total_seconds))
}

async fn duration_seconds(path: &Path) -> Result<f64, ApiError> {
    let out = Command::new("ffprobe")
        .args(["-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1"])
        .arg(path)
        .output()
        .await
        .map_err(|e| ApiError::internal("ffprobe could not start", e))?;
    // Browser recordings (webm) often report no duration; ffmpeg still decodes them.
    Ok(String::from_utf8_lossy(&out.stdout).trim().parse().unwrap_or(0.0))
}

async fn transcribe_segment(state: &AppState, wav: Vec<u8>, language: Option<&str>) -> Result<String, ApiError> {
    for attempt in 1..=MAX_ATTEMPTS {
        let part = reqwest::multipart::Part::bytes(wav.clone())
            .file_name("audio.wav")
            .mime_str("audio/wav")
            .map_err(|e| ApiError::internal("Invalid MIME type", e))?;
        let form = reqwest::multipart::Form::new()
            .part("file", part)
            .text("model", state.config.sarvam_stt_model.clone())
            .text("language_code", language.unwrap_or("unknown").to_string());

        let response = state
            .http
            .post(&state.config.sarvam_stt_url)
            .header("api-subscription-key", &state.config.sarvam_api_key)
            .timeout(Duration::from_secs(60))
            .multipart(form)
            .send()
            .await;

        let response = match response {
            Ok(r) => r,
            Err(e) if attempt < MAX_ATTEMPTS => {
                tracing::warn!("Sarvam STT unreachable (attempt {attempt}): {e:?}");
                tokio::time::sleep(Duration::from_secs(2u64.pow(attempt))).await;
                continue;
            }
            Err(e) => {
                tracing::error!("Sarvam STT unreachable: {e:?}");
                return Err(ApiError::unavailable("Speech recognition service is unavailable. Try again shortly."));
            }
        };

        let status = response.status();
        if status.is_success() {
            return Ok(response
                .json::<SarvamTranscript>()
                .await
                .map_err(|e| ApiError::internal("Bad Sarvam STT response", e))?
                .transcript);
        }
        let body = response.text().await.unwrap_or_default();
        if (status.as_u16() == 429 || status.is_server_error()) && attempt < MAX_ATTEMPTS {
            tracing::warn!("Sarvam STT {status} (attempt {attempt}); retrying");
            tokio::time::sleep(Duration::from_secs(2u64.pow(attempt))).await;
            continue;
        }
        tracing::error!("Sarvam STT error {status}: {body}");
        return Err(match status.as_u16() {
            401 | 403 => ApiError::unavailable("Speech recognition failed: Sarvam rejected the API key."),
            402 | 429 => ApiError::unavailable("Speech recognition is over its Sarvam quota. Try again later."),
            400 | 422 => ApiError::bad_request("Could not transcribe this audio. Try another recording or format."),
            _ => ApiError::unavailable("Speech recognition failed. Try again shortly."),
        });
    }
    Err(ApiError::unavailable("Speech recognition failed. Try again shortly."))
}
