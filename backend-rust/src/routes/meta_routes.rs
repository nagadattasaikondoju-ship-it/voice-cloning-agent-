use axum::{extract::State, Json};
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
    Json(json!({
        "status": if db_ok && redis_ok { "ok" } else { "degraded" },
        "database": db_ok,
        "redis": redis_ok,
        "speech_pipeline": stt_ok,
    }))
}

/// Voice engines the worker can run. Keys live only in server environments.
pub async fn engines(State(state): State<AppState>) -> Json<Value> {
    let c = &state.config;
    Json(json!([
        {
            "id": "f5",
            "name": "F5-TTS (Hugging Face, free)",
            "available": c.f5_enabled,
            "description": "Zero-shot cloning through the public F5-TTS Space. Free, slower, queue-dependent.",
        },
        {
            "id": "minimax",
            "name": "MiniMax speech-2.8-hd",
            "available": c.minimax_enabled,
            "description": "Highest quality. Requires MINIMAX_API_KEY on the worker.",
        },
        {
            "id": "elevenlabs",
            "name": "ElevenLabs Instant Voice Clone",
            "available": c.elevenlabs_enabled,
            "description": "Fast, high quality. Requires ELEVENLABS_API_KEY on the worker.",
        }
    ]))
}
