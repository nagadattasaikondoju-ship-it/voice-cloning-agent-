mod auth;
mod config;
mod db;
mod models;
mod routes;

use axum::{
    http::{header, Method},
    routing::{delete, get, post},
    Router,
};
use std::net::SocketAddr;
use tower_http::{
    cors::{AllowOrigin, CorsLayer},
    trace::TraceLayer,
};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

use crate::{
    config::Config,
    db::{init_db, AppState},
    routes::{
        auth_routes::{login, logout, me, register},
        clone_routes::{
            create_voice_clone, delete_voice_clone, get_voice_clone_by_id, get_voice_clones,
            get_voice_samples, upload_voice_sample,
        },
        consent_routes::{create_consent, get_consents, verify_consent},
        speech_routes::{
            delete_generated_audio, generate_speech, get_speech_history, get_speech_job_status,
            stream_audio,
        },
    },
};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // 1. Initialize Tracing Subscriber
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "intelligence_backend=debug,tower_http=info".into()),
        )
        .with(tracing_subscriber::fmt::layer())
        .init();

    // 2. Load Configuration
    let config = Config::from_env();
    tracing::info!("Initializing Intelligence API on port {}...", config.port);

    // 3. Connect to PostgreSQL
    let db = init_db(&config.database_url).await.unwrap_or_else(|err| {
        tracing::warn!("PostgreSQL connection failed ({:?}); continuing with mock/startup fallback...", err);
        // Fallback for offline build / verification checks
        panic!("PostgreSQL database required. Verify DATABASE_URL: {}", config.database_url);
    });

    // 4. Connect to Redis Client
    let redis_client = redis::Client::open(config.redis_url.clone())
        .expect("Invalid Redis connection URL");

    let state = AppState {
        db,
        redis: redis_client,
        config: config.clone(),
    };

    // 5. Build CORS Policy
    let origins: Vec<_> = config
        .allowed_origins
        .iter()
        .filter_map(|o| o.parse().ok())
        .collect();

    let cors = CorsLayer::new()
        .allow_origin(AllowOrigin::list(origins))
        .allow_methods([
            Method::GET,
            Method::POST,
            Method::PUT,
            Method::DELETE,
            Method::OPTIONS,
        ])
        .allow_headers([
            header::AUTHORIZATION,
            header::CONTENT_TYPE,
            header::ACCEPT,
        ])
        .allow_credentials(true);

    // 6. Router Composition
    let app = Router::new()
        // Auth Routes
        .route("/api/auth/register", post(register))
        .route("/api/auth/login", post(login))
        .route("/api/auth/logout", post(logout))
        .route("/api/auth/me", get(me))
        // Consent Verification Routes
        .route("/api/consents", post(create_consent).get(get_consents))
        .route("/api/consents/:id/verify", post(verify_consent))
        // Voice Samples & Cloning Routes
        .route("/api/voice-samples", post(upload_voice_sample).get(get_voice_samples))
        .route("/api/voice-clones", post(create_voice_clone).get(get_voice_clones))
        .route(
            "/api/voice-clones/:id",
            get(get_voice_clone_by_id).delete(delete_voice_clone),
        )
        // Speech Synthesis & History Routes
        .route("/api/speech/generate", post(generate_speech))
        .route("/api/speech/jobs/:id", get(get_speech_job_status))
        .route("/api/speech/history", get(get_speech_history))
        .route("/api/speech/audio/:id", delete(delete_generated_audio))
        // Audio Streaming
        .route("/api/audio/:id", get(stream_audio))
        .layer(cors)
        .layer(TraceLayer::new_for_http())
        .with_state(state);

    // 7. Launch HTTP Server
    let addr = SocketAddr::from(([0, 0, 0, 0], config.port));
    tracing::info!("Server running and listening at http://{}", addr);

    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}
