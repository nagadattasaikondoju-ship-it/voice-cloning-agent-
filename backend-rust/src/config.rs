use std::env;

#[derive(Clone, Debug)]
pub struct Config {
    pub database_url: String,
    pub redis_url: String,
    pub jwt_secret: String,
    pub minimax_api_key: String,
    pub minimax_base_url: String,
    pub storage_dir: String,
    pub allowed_origins: Vec<String>,
    pub port: u16,
}

impl Config {
    pub fn from_env() -> Self {
        dotenvy::dotenv().ok();

        let database_url = env::var("DATABASE_URL")
            .unwrap_or_else(|_| "postgresql://postgres:postgres@localhost:5432/voiceclone".to_string());

        let redis_url = env::var("REDIS_URL")
            .unwrap_or_else(|_| "redis://localhost:6379/0".to_string());

        let jwt_secret = env::var("JWT_SECRET")
            .unwrap_or_else(|_| "super_secret_jwt_key_intelligence_evolve_2026".to_string());

        let minimax_api_key = env::var("MINIMAX_API_KEY")
            .unwrap_or_else(|_| "mock_or_env_injected_minimax_key".to_string());

        let minimax_base_url = env::var("MINIMAX_BASE_URL")
            .unwrap_or_else(|_| "https://api.minimax.io/v1".to_string());

        let storage_dir = env::var("STORAGE_DIR")
            .unwrap_or_else(|_| "./private_storage".to_string());

        let allowed_origins_raw = env::var("ALLOWED_ORIGINS")
            .unwrap_or_else(|_| "http://localhost:5500,http://127.0.0.1:5500,http://localhost:3000".to_string());

        let allowed_origins = allowed_origins_raw
            .split(',')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect();

        let port = env::var("PORT")
            .ok()
            .and_then(|p| p.parse().ok())
            .unwrap_or(8080);

        Config {
            database_url,
            redis_url,
            jwt_secret,
            minimax_api_key,
            minimax_base_url,
            storage_dir,
            allowed_origins,
            port,
        }
    }
}
