use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

// ==========================================
// User Entities & DTOs
// ==========================================

#[derive(Debug, Serialize, Deserialize, sqlx::FromRow)]
pub struct User {
    pub id: Uuid,
    pub email: String,
    pub password_hash: String,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct UserPublic {
    pub id: Uuid,
    pub email: String,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Deserialize)]
pub struct RegisterRequest {
    pub email: String,
    pub password: String,
}

#[derive(Debug, Deserialize)]
pub struct LoginRequest {
    pub email: String,
    pub password: String,
}

#[derive(Debug, Serialize)]
pub struct AuthResponse {
    pub token: String,
    pub user: UserPublic,
}

// ==========================================
// Consent Entities & DTOs
// ==========================================

#[derive(Debug, Serialize, Deserialize, sqlx::FromRow)]
pub struct Consent {
    pub id: Uuid,
    pub user_id: Uuid,
    pub consent_audio_url: String,
    pub spoken_phrase: String,
    pub consent_version: String,
    pub verified: bool,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Deserialize)]
pub struct CreateConsentRequest {
    pub spoken_phrase: String,
    pub consent_version: Option<String>,
    pub consent_audio_url: String,
}

#[derive(Debug, Serialize)]
pub struct ConsentResponse {
    pub id: Uuid,
    pub spoken_phrase: String,
    pub consent_version: String,
    pub verified: bool,
    pub created_at: DateTime<Utc>,
}

// ==========================================
// Voice Sample Entities & DTOs
// ==========================================

#[derive(Debug, Serialize, Deserialize, sqlx::FromRow)]
pub struct VoiceSample {
    pub id: Uuid,
    pub user_id: Uuid,
    pub storage_key: String,
    pub mime_type: String,
    pub duration_seconds: f64,
    pub file_size_bytes: i64,
    pub created_at: DateTime<Utc>,
}

// ==========================================
// Voice Clone Entities & DTOs
// ==========================================

#[derive(Debug, Serialize, Deserialize, sqlx::FromRow)]
pub struct VoiceClone {
    pub id: Uuid,
    pub user_id: Uuid,
    pub consent_id: Uuid,
    pub sample_id: Uuid,
    pub display_name: String,
    pub minimax_voice_id: String,
    pub status: String,
    pub created_at: DateTime<Utc>,
    pub deleted_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Deserialize)]
pub struct CreateVoiceCloneRequest {
    pub consent_id: Uuid,
    pub sample_id: Uuid,
    pub display_name: String,
    pub requested_voice_id: String,
}

#[derive(Debug, Serialize)]
pub struct VoiceCloneResponse {
    pub id: Uuid,
    pub display_name: String,
    pub minimax_voice_id: String,
    pub status: String,
    pub created_at: DateTime<Utc>,
}

// ==========================================
// Speech Job & Generation Entities & DTOs
// ==========================================

#[derive(Debug, Serialize, Deserialize, sqlx::FromRow)]
pub struct SpeechJob {
    pub id: Uuid,
    pub user_id: Uuid,
    pub voice_clone_id: Uuid,
    pub text: String,
    pub speed: f64,
    pub volume: f64,
    pub pitch: i32,
    pub status: String,
    pub error_message: Option<String>,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Deserialize)]
pub struct GenerateSpeechRequest {
    pub voice_id: String,
    pub text: String,
    pub speed: Option<f64>,
    pub volume: Option<f64>,
    pub pitch: Option<i32>,
}

#[derive(Debug, Serialize)]
pub struct SpeechJobResponse {
    pub job_id: Uuid,
    pub status: String,
    pub audio_url: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, sqlx::FromRow)]
pub struct GeneratedAudio {
    pub id: Uuid,
    pub speech_job_id: Uuid,
    pub user_id: Uuid,
    pub storage_key: String,
    pub duration_seconds: Option<f64>,
    pub file_size_bytes: Option<i64>,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Serialize)]
pub struct SpeechHistoryItem {
    pub id: Uuid,
    pub speech_job_id: Uuid,
    pub voice_id: String,
    pub text: String,
    pub audio_url: String,
    pub duration_seconds: Option<f64>,
    pub created_at: DateTime<Utc>,
}

// ==========================================
// Redis Queue Messages
// ==========================================

#[derive(Debug, Serialize, Deserialize)]
pub struct CloneWorkerJob {
    pub job_id: Uuid,
    pub user_id: Uuid,
    pub sample_storage_path: String,
    pub requested_voice_id: String,
    pub display_name: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct SpeechWorkerJob {
    pub job_id: Uuid,
    pub user_id: Uuid,
    pub minimax_voice_id: String,
    pub text: String,
    pub speed: f64,
    pub volume: f64,
    pub pitch: i32,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct DeleteVoiceWorkerJob {
    pub minimax_voice_id: String,
    pub user_id: Uuid,
}
