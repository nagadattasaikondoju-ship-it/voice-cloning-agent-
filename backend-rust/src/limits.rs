//! Usage limits for a public deployment: every voice, speech clip and transcription spends
//! Sarvam credits, so each account gets a daily allowance, and sign-in attempts are rate
//! limited per IP address. A limit of 0 means unlimited.
use std::{
    collections::HashMap,
    net::SocketAddr,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

use axum::http::{HeaderMap, StatusCode};
use uuid::Uuid;

use crate::{db::AppState, error::ApiError};

fn too_many(msg: String) -> ApiError {
    ApiError::new(StatusCode::TOO_MANY_REQUESTS, msg)
}

/// Active (not deleted) voices per account.
pub async fn check_voice_count(state: &AppState, user_id: Uuid) -> Result<(), ApiError> {
    let max = state.config.max_voices;
    if max == 0 {
        return Ok(());
    }
    let n: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM voice_clones WHERE user_id = $1 AND deleted_at IS NULL")
        .bind(user_id)
        .fetch_one(&state.db)
        .await?;
    if n >= max {
        return Err(too_many(format!("You can have at most {max} voice(s). Delete one to create another.")));
    }
    Ok(())
}

/// Characters of speech generated in the last 24 hours (failed jobs do not count).
pub async fn check_speech_chars(state: &AppState, user_id: Uuid, chars: i64) -> Result<(), ApiError> {
    let max = state.config.daily_speech_chars;
    if max == 0 {
        return Ok(());
    }
    let used: i64 = sqlx::query_scalar(
        "SELECT COALESCE(SUM(char_length(text)), 0)::BIGINT FROM speech_jobs
         WHERE user_id = $1 AND status <> 'failed' AND created_at > NOW() - INTERVAL '24 hours'",
    )
    .bind(user_id)
    .fetch_one(&state.db)
    .await?;
    if used + chars > max {
        return Err(too_many(format!(
            "Daily limit reached: {used} of {max} characters used in the last 24 hours ({} left).",
            (max - used).max(0)
        )));
    }
    Ok(())
}

/// Consent phrases issued in the last 24 hours (each verification costs a transcription).
pub async fn check_consents(state: &AppState, user_id: Uuid) -> Result<(), ApiError> {
    let max = state.config.daily_consents;
    if max == 0 {
        return Ok(());
    }
    let n: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM consents WHERE user_id = $1 AND created_at > NOW() - INTERVAL '24 hours'",
    )
    .bind(user_id)
    .fetch_one(&state.db)
    .await?;
    if n >= max {
        return Err(too_many(format!("You requested {max} consent phrases in the last 24 hours. Try again tomorrow.")));
    }
    Ok(())
}

/// Seconds of audio transcribed in the last 24 hours; returns how many are left.
pub async fn transcribe_seconds_left(state: &AppState, user_id: Uuid) -> Result<f64, ApiError> {
    let max = state.config.daily_transcribe_seconds;
    if max == 0 {
        return Ok(f64::INFINITY);
    }
    let used: f64 = sqlx::query_scalar(
        "SELECT COALESCE(SUM((details->>'seconds')::DOUBLE PRECISION), 0) FROM audit_logs
         WHERE user_id = $1 AND action = 'audio_transcribed' AND created_at > NOW() - INTERVAL '24 hours'",
    )
    .bind(user_id)
    .fetch_one(&state.db)
    .await?;
    let left = max as f64 - used;
    if left < 1.0 {
        return Err(too_many(format!("Daily transcription limit reached ({} minutes). Try again tomorrow.", max / 60)));
    }
    Ok(left)
}

/// Fixed-window counter of sign-in/sign-up attempts per client IP.
#[derive(Clone, Default)]
pub struct AuthRateLimiter(Arc<Mutex<HashMap<String, (u32, Instant)>>>);

const WINDOW: Duration = Duration::from_secs(3600);

impl AuthRateLimiter {
    pub fn check(&self, state: &AppState, headers: &HeaderMap, peer: SocketAddr) -> Result<(), ApiError> {
        let max = state.config.auth_attempts_per_hour;
        if max == 0 {
            return Ok(());
        }
        let ip = client_ip(headers, peer, state.config.trust_proxy);
        let mut map = self.0.lock().unwrap_or_else(|e| e.into_inner());
        let now = Instant::now();
        if map.len() > 10_000 {
            map.retain(|_, (_, start)| now.duration_since(*start) < WINDOW);
        }
        let entry = map.entry(ip).or_insert((0, now));
        if now.duration_since(entry.1) >= WINDOW {
            *entry = (0, now);
        }
        entry.0 += 1;
        if entry.0 > max {
            return Err(too_many("Too many sign-in attempts from this network. Try again in an hour.".into()));
        }
        Ok(())
    }
}

/// Behind a hosting proxy (TRUST_PROXY=true) the client IP comes from its headers;
/// otherwise from the TCP peer, since clients can forge those headers.
fn client_ip(headers: &HeaderMap, peer: SocketAddr, trust_proxy: bool) -> String {
    if trust_proxy {
        let header = |name: &str| headers.get(name).and_then(|v| v.to_str().ok()).map(str::trim);
        if let Some(ip) = header("true-client-ip").filter(|v| !v.is_empty()) {
            return ip.to_string();
        }
        if let Some(last) = header("x-forwarded-for").and_then(|v| v.rsplit(',').next()).map(str::trim) {
            if !last.is_empty() {
                return last.to_string();
            }
        }
    }
    peer.ip().to_string()
}
