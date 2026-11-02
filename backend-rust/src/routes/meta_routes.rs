use axum::{extract::State, Json};
use redis::AsyncCommands;
use serde_json::{json, Value};

use crate::db::AppState;

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
    let worker_ok = worker_health(&state).await.is_some();
    Json(json!({
        "status": if db_ok && redis_ok && worker_ok { "ok" } else { "degraded" },
        "database": db_ok,
        "redis": redis_ok,
        "speech_pipeline": stt_ok,
        "worker": worker_ok,
    }))
}

/// Self-check results the worker publishes to Redis (`engine_health`, refreshed every 10 min).
async fn worker_health(state: &AppState) -> Option<Value> {
    let mut con = state.redis.get_multiplexed_async_connection().await.ok()?;
    let raw: Option<String> = con.get("engine_health").await.ok()?;
    serde_json::from_str(&raw?).ok()
}

pub struct EngineStatus {
    pub available: bool,
    pub problem: Option<String>,
    pub detail: Option<String>,
}

/// The worker holds the keys, so its self-check decides; env flags are the fallback.
pub async fn engine_status(state: &AppState, engine: &str) -> EngineStatus {
    let configured = state.config.engine_enabled(engine);
    match worker_health(state).await.and_then(|h| h.get(engine).cloned()) {
        Some(h) => {
            let ok = h.get("ok").and_then(Value::as_bool).unwrap_or(false);
            let text = |k: &str| h.get(k).and_then(Value::as_str).filter(|s| !s.is_empty()).map(str::to_string);
            EngineStatus { available: ok, problem: text("problem"), detail: text("detail") }
        }
        None => EngineStatus {
            available: false,
            problem: Some(if configured {
                "The worker is not running (no engine health report in Redis), so jobs would never run.".into()
            } else {
                "Not configured on this server.".into()
            }),
            detail: None,
        },
    }
}

const ENGINES: &[(&str, &str, &str)] = &[
    ("f5", "F5-TTS (Hugging Face, free)", "Zero-shot cloning through the public F5-TTS Space. Free, slower, needs HF_TOKEN for steady use."),
    ("minimax", "MiniMax speech-2.8-hd", "Highest quality. Paid; needs MINIMAX_API_KEY, a verified account and balance. Samples 10 s–5 min."),
    ("elevenlabs", "ElevenLabs Instant Voice Clone", "Fast, high quality. Needs ELEVENLABS_API_KEY on a plan with Instant Voice Cloning."),
];

pub async fn engines(State(state): State<AppState>) -> Json<Value> {
    let mut out = Vec::new();
    for (id, name, description) in ENGINES {
        let s = engine_status(&state, id).await;
        out.push(json!({
            "id": id,
            "name": name,
            "description": description,
            "available": s.available,
            "problem": s.problem,
            "detail": s.detail,
        }));
    }
    Json(Value::Array(out))
}
