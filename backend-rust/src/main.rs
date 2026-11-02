mod auth;
mod config;
mod consent_check;
mod db;
mod error;
mod models;
mod routes;
mod storage;
mod stt;

use std::{net::SocketAddr, time::Duration};

use axum::{
    extract::DefaultBodyLimit,
    http::{header, HeaderValue, Method},
    routing::{delete, get, post},
    Router,
};
use tower_http::{cors::CorsLayer, trace::TraceLayer};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

use crate::{
    config::Config,
    db::{init_db, AppState},
    routes::{
        auth_routes, clone_routes, consent_routes, meta_routes, speech_routes, transcribe_routes, MAX_AUDIO_BYTES,
    },
};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "intelligence_backend=info,tower_http=info".into()),
        )
        .with(tracing_subscriber::fmt::layer())
        .init();

    let config = Config::from_env();
    tracing::info!(
        "Engines: f5={} minimax={} elevenlabs={} | speech pipeline: {}",
        config.f5_enabled,
        config.minimax_enabled,
        config.elevenlabs_enabled,
        config.speech_pipeline_url
    );

    let db = init_db(&config.database_url).await?;
    let redis = redis::Client::open(config.redis_url.clone())?;
    let http = reqwest::Client::builder().connect_timeout(Duration::from_secs(10)).timeout(Duration::from_secs(180)).build()?;
    tokio::fs::create_dir_all(&config.storage_dir).await?;

    let origins: Vec<HeaderValue> = config.allowed_origins.iter().filter_map(|o| o.parse().ok()).collect();
    let cors = CorsLayer::new()
        .allow_origin(origins)
        .allow_methods([Method::GET, Method::POST, Method::DELETE, Method::OPTIONS])
        .allow_headers([header::AUTHORIZATION, header::CONTENT_TYPE, header::ACCEPT]);

    let state = AppState { db, redis, http, config: config.clone() };

    let app = Router::new()
        .route("/api/health", get(meta_routes::health))
        .route("/api/engines", get(meta_routes::engines))
        // Auth
        .route("/api/auth/register", post(auth_routes::register))
        .route("/api/auth/login", post(auth_routes::login))
        .route("/api/auth/logout", post(auth_routes::logout))
        .route("/api/auth/me", get(auth_routes::me))
        // Consent (phrase issued by server, verified via Whisper)
        .route("/api/consents", post(consent_routes::create_consent).get(consent_routes::get_consents))
        .route("/api/consents/:id/verify", post(consent_routes::verify_consent))
        // Samples & clones
        .route(
            "/api/voice-samples",
            post(clone_routes::upload_voice_sample).get(clone_routes::get_voice_samples),
        )
        .route(
            "/api/voice-clones",
            post(clone_routes::create_voice_clone).get(clone_routes::get_voice_clones),
        )
        .route(
            "/api/voice-clones/:id",
            get(clone_routes::get_voice_clone_by_id).delete(clone_routes::delete_voice_clone),
        )
        // Speech
        .route("/api/speech/generate", post(speech_routes::generate_speech))
        .route("/api/speech/jobs/:id", get(speech_routes::get_speech_job_status))
        .route("/api/speech/history", get(speech_routes::get_speech_history))
        .route("/api/speech/audio/:id", delete(speech_routes::delete_generated_audio))
        .route("/api/audio/:id", get(speech_routes::stream_audio))
        // Audio -> script text for TTS
        .route("/api/transcribe", post(transcribe_routes::transcribe_audio))
        .layer(DefaultBodyLimit::max(MAX_AUDIO_BYTES + 1024 * 1024))
        .layer(cors)
        .layer(TraceLayer::new_for_http())
        .with_state(state);

    let addr = SocketAddr::from(([0, 0, 0, 0], config.port));
    tracing::info!("Intelligence API listening on http://{addr}");
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}
