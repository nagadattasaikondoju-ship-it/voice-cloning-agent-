use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

// ---------- Users ----------

#[derive(Debug, sqlx::FromRow)]
pub struct User {
    pub id: Uuid,
    pub email: String,
    pub password_hash: String,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Serialize)]
pub struct UserPublic {
    pub id: Uuid,
    pub email: String,
    pub created_at: DateTime<Utc>,
}

impl From<User> for UserPublic {
    fn from(u: User) -> Self {
        Self { id: u.id, email: u.email, created_at: u.created_at }
    }
}

#[derive(Debug, Deserialize)]
pub struct Credentials {
    pub email: String,
    pub password: String,
}

#[derive(Debug, Serialize)]
pub struct AuthResponse {
    pub token: String,
    pub user: UserPublic,
}

// ---------- Consents ----------

#[allow(dead_code)] // some columns are loaded for completeness but not read
#[derive(Debug, Serialize, sqlx::FromRow)]
pub struct Consent {
    pub id: Uuid,
    #[serde(skip)]
    pub user_id: Uuid,
    #[serde(skip)]
    pub consent_audio_key: Option<String>,
    pub spoken_phrase: String,
    pub consent_version: String,
    pub verified: bool,
    pub transcript: Option<String>,
    pub match_score: Option<f64>,
    pub attempts: i32,
    pub verified_at: Option<DateTime<Utc>>,
    pub created_at: DateTime<Utc>,
}

pub const CONSENT_COLUMNS: &str = "id, user_id, consent_audio_key, spoken_phrase, consent_version, verified, \
     transcript, match_score, attempts, verified_at, created_at";

#[derive(Debug, Serialize)]
pub struct ConsentVerification {
    pub verified: bool,
    pub transcript: String,
    pub match_score: f64,
    pub threshold: f64,
    pub attempts_remaining: i32,
    pub consent: Consent,
}

// ---------- Voice samples ----------

#[allow(dead_code)] // some columns are loaded for completeness but not read
#[derive(Debug, Serialize, sqlx::FromRow)]
pub struct VoiceSample {
    pub id: Uuid,
    #[serde(skip)]
    pub user_id: Uuid,
    #[serde(skip)]
    pub storage_key: String,
    pub mime_type: String,
    pub duration_seconds: f64,
    pub file_size_bytes: i64,
    pub created_at: DateTime<Utc>,
}

// ---------- Voice clones ----------

#[allow(dead_code)] // some columns are loaded for completeness but not read
#[derive(Debug, Serialize, sqlx::FromRow)]
pub struct VoiceClone {
    pub id: Uuid,
    #[serde(skip)]
    pub user_id: Uuid,
    pub consent_id: Uuid,
    pub sample_id: Uuid,
    pub display_name: String,
    pub voice_id: String,
    pub engine: String,
    pub status: String,
    pub error_message: Option<String>,
    pub created_at: DateTime<Utc>,
    #[serde(skip)]
    pub deleted_at: Option<DateTime<Utc>>,
}

pub const CLONE_COLUMNS: &str =
    "id, user_id, consent_id, sample_id, display_name, voice_id, engine, status, error_message, created_at, deleted_at";

#[derive(Debug, Deserialize)]
pub struct CreateVoiceCloneRequest {
    pub consent_id: Uuid,
    pub sample_id: Uuid,
    pub display_name: String,
}

// ---------- Speech ----------

#[derive(Debug, sqlx::FromRow)]
pub struct SpeechJob {
    pub id: Uuid,
    pub status: String,
    pub error_message: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct GenerateSpeechRequest {
    /// The voice clone's id (UUID) as returned by /api/voice-clones.
    pub voice_clone_id: Uuid,
    pub text: String,
    pub speed: Option<f64>,
    pub volume: Option<f64>,
    /// ISO 639-1 code; only "en" unless the worker runs the multilingual model.
    pub language: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct SpeechJobResponse {
    pub job_id: Uuid,
    pub status: String,
    pub audio_url: Option<String>,
    pub error_message: Option<String>,
}

#[derive(Debug, sqlx::FromRow)]
pub struct GeneratedAudio {
    pub id: Uuid,
    pub storage_key: String,
    pub mime_type: String,
}

#[derive(Debug, Serialize, sqlx::FromRow)]
pub struct SpeechHistoryItem {
    pub id: Uuid,
    pub speech_job_id: Uuid,
    pub voice_clone_id: Uuid,
    pub voice_name: String,
    pub language: String,
    pub text: String,
    pub duration_seconds: Option<f64>,
    pub created_at: DateTime<Utc>,
    #[sqlx(skip)]
    pub audio_url: String,
}

// ---------- Redis queue messages (consumed by worker-python) ----------

#[derive(Debug, Serialize)]
pub struct CloneWorkerJob {
    pub job_id: Uuid,
    pub user_id: Uuid,
    pub voice_id: String,
    pub sample_storage_path: String,
}

#[derive(Debug, Serialize)]
pub struct SpeechWorkerJob {
    pub job_id: Uuid,
    pub user_id: Uuid,
    pub voice_id: String,
    pub text: String,
    pub speed: f64,
    pub volume: f64,
    pub language: String,
}

#[derive(Debug, Serialize)]
pub struct DeleteVoiceWorkerJob {
    pub user_id: Uuid,
    pub voice_id: String,
}
