use std::env;

#[derive(Clone, Debug)]
pub struct Config {
    pub database_url: String,
    pub redis_url: String,
    pub jwt_secret: String,
    pub allowed_origins: Vec<String>,
    pub port: u16,
    /// Sarvam AI key for speech-to-text (consent checks, audio -> script).
    pub sarvam_api_key: String,
    pub sarvam_stt_url: String,
    pub sarvam_stt_model: String,
    /// Minimum word-level similarity (0..1) between the consent phrase and the transcript.
    pub consent_match_threshold: f64,
    pub consent_max_attempts: i32,
    /// Usage limits (0 = unlimited). See limits.rs.
    pub max_voices: i64,
    pub daily_speech_chars: i64,
    pub daily_consents: i64,
    pub daily_transcribe_seconds: i64,
    pub auth_attempts_per_hour: u32,
    /// Take the client IP from proxy headers (set on hosts like Render).
    pub trust_proxy: bool,
    /// Directory with the static site (index.html, frontend/) to serve at /, if set.
    pub public_dir: Option<String>,
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
            allowed_origins,
            port: env_or("PORT", "8080").parse().unwrap_or(8080),
            sarvam_api_key: env::var("SARVAM_API_KEY").unwrap_or_default().trim().to_string(),
            sarvam_stt_url: env_or("SARVAM_STT_URL", "https://api.sarvam.ai/speech-to-text"),
            sarvam_stt_model: env_or("SARVAM_STT_MODEL", "saaras:v3"),
            consent_match_threshold: env_or("CONSENT_MATCH_THRESHOLD", "0.75").parse().unwrap_or(0.75),
            consent_max_attempts: env_or("CONSENT_MAX_ATTEMPTS", "5").parse().unwrap_or(5),
            max_voices: env_or("MAX_VOICES_PER_USER", "3").parse().unwrap_or(3),
            daily_speech_chars: env_or("DAILY_SPEECH_CHARS", "2000").parse().unwrap_or(2000),
            daily_consents: env_or("DAILY_CONSENTS", "10").parse().unwrap_or(10),
            daily_transcribe_seconds: env_or("DAILY_TRANSCRIBE_SECONDS", "600").parse().unwrap_or(600),
            auth_attempts_per_hour: env_or("AUTH_ATTEMPTS_PER_HOUR", "20").parse().unwrap_or(20),
            trust_proxy: matches!(env_or("TRUST_PROXY", "false").to_lowercase().as_str(), "1" | "true" | "yes"),
            public_dir: env::var("PUBLIC_DIR").ok().filter(|v| !v.trim().is_empty()),
        }
    }
}
