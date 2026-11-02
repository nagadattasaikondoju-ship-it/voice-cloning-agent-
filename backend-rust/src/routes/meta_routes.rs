use axum::{extract::State, Json};
use redis::AsyncCommands;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::{db::AppState, error::ApiError};

/// Status the worker publishes every 30 s to Redis key `engine_health` (expires after 120 s).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EngineStatus {
    pub ok: bool,
    pub status: String,
    #[serde(default)]
    pub engine: String,
    #[serde(default)]
    pub model: String,
    #[serde(default)]
    pub model_label: String,
    pub device: Option<String>,
    #[serde(default)]
    pub languages: Vec<String>,
    #[serde(default)]
    pub problem: String,
}

pub async fn engine_status(state: &AppState) -> EngineStatus {
    let reported: Option<EngineStatus> = async {
        let mut con = state.redis.get_multiplexed_async_connection().await.ok()?;
        let raw: Option<String> = con.get("engine_health").await.ok()?;
        serde_json::from_str(&raw?).ok()
    }
    .await;
    reported.unwrap_or_else(|| EngineStatus {
        ok: false,
        status: "offline".into(),
        engine: "chatterbox".into(),
        model: String::new(),
        model_label: String::new(),
        device: None,
        languages: vec![],
        problem: "The voice worker is not running, so voices cannot be created or spoken.".into(),
    })
}

/// Fails with a clear message unless the worker is up and the model is loaded.
pub async fn require_engine(state: &AppState) -> Result<EngineStatus, ApiError> {
    let s = engine_status(state).await;
    match s.status.as_str() {
        "ready" => Ok(s),
        "loading" => Err(ApiError::unavailable(
            "The voice model is still loading (the first start downloads it). Try again in a minute.",
        )),
        _ => Err(ApiError::unavailable(if s.problem.is_empty() { "Voice engine unavailable".into() } else { s.problem })),
    }
}

pub async fn engine(State(state): State<AppState>) -> Json<EngineStatus> {
    Json(engine_status(&state).await)
}

pub async fn health(State(state): State<AppState>) -> Json<Value> {
    let db_ok = sqlx::query("SELECT 1").execute(&state.db).await.is_ok();
    let redis_ok = match state.redis.get_multiplexed_async_connection().await {
        Ok(mut con) => redis::cmd("PING").query_async::<String>(&mut con).await.is_ok(),
        Err(_) => false,
    };
    let stt_ok = state
        .http
        .get(format!("{}/api/v1/health", state.config.speech_pipeline_url))
        .send()
        .await
        .map(|r| r.status().is_success())
        .unwrap_or(false);
    let engine = engine_status(&state).await;
    Json(json!({
        "status": if db_ok && redis_ok && stt_ok && engine.ok { "ok" } else { "degraded" },
        "database": db_ok,
        "redis": redis_ok,
        "speech_pipeline": stt_ok,
        "worker": engine.status,
    }))
}
