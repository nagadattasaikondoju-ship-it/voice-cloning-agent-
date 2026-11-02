use std::env;

#[derive(Clone, Debug)]
pub struct Config {
    pub database_url: String,
    pub redis_url: String,
    pub jwt_secret: String,
    pub storage_dir: String,
    pub allowed_origins: Vec<String>,
    pub port: u16,
    /// Base URL of the speech_pipeline service (Whisper STT) used to verify spoken consent.
    pub speech_pipeline_url: String,
    /// Minimum word-level similarity (0..1) between the consent phrase and the transcript.
    pub consent_match_threshold: f64,
    pub consent_max_attempts: i32,
}

fn env_or(key: &str, default: &str) -> String {
    env::var(key).ok().filter(|v| !v.trim().is_empty()).unwrap_or_else(|| default.to_string())
}

impl Config {
    pub fn from_env() -> Self {
        dotenvy::dotenv().ok();

        let jwt_secret = env::var("JWT_SECRET").unwrap_or_default();
        if jwt_secret.len() < 32 {
            panic!(
                "JWT_SECRET must be set to a random value of at least 32 characters \
                 (generate one with: openssl rand -hex 32)"
            );
        }

        let allowed_origins = env_or("ALLOWED_ORIGINS", "http://localhost:5500,http://127.0.0.1:5500")
            .split(',')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect();

        Config {
            database_url: env_or("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/voiceclone"),
            redis_url: env_or("REDIS_URL", "redis://localhost:6379/0"),
            jwt_secret,
            storage_dir: env_or("STORAGE_DIR", "./private_storage"),
            allowed_origins,
            port: env_or("PORT", "8080").parse().unwrap_or(8080),
            speech_pipeline_url: env_or("SPEECH_PIPELINE_URL", "http://localhost:8000")
                .trim_end_matches('/')
                .to_string(),
            consent_match_threshold: env_or("CONSENT_MATCH_THRESHOLD", "0.75").parse().unwrap_or(0.75),
            consent_max_attempts: env_or("CONSENT_MAX_ATTEMPTS", "5").parse().unwrap_or(5),
        }
    }
}
