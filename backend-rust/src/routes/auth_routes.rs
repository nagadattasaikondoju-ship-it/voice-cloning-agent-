use axum::{extract::State, http::StatusCode, Json};
use serde_json::{json, Value};
use uuid::Uuid;

use crate::{
    auth::{create_jwt, hash_password, verify_password, AuthUser},
    db::{record_audit_log, AppState},
    error::{ApiError, ApiResult},
    models::{AuthResponse, Credentials, User, UserPublic},
};

fn issue_token(state: &AppState, user: User) -> ApiResult<AuthResponse> {
    let token = create_jwt(&user.id, &user.email, &state.config.jwt_secret)
        .map_err(|e| ApiError::internal("JWT signing failed", e))?;
    Ok(Json(AuthResponse { token, user: user.into() }))
}

pub async fn register(State(state): State<AppState>, Json(body): Json<Credentials>) -> ApiResult<AuthResponse> {
    let email = body.email.trim().to_lowercase();
    if !email.contains('@') || email.len() > 254 {
        return Err(ApiError::bad_request("A valid email address is required"));
    }
    if body.password.len() < 8 || body.password.len() > 128 {
        return Err(ApiError::bad_request("Password must be 8–128 characters"));
    }
    let password_hash = hash_password(&body.password).map_err(|e| ApiError::internal("bcrypt failed", e))?;

    let user: Option<User> = sqlx::query_as(
        "INSERT INTO users (id, email, password_hash) VALUES ($1, $2, $3)
         ON CONFLICT (email) DO NOTHING
         RETURNING id, email, password_hash, created_at",
    )
    .bind(Uuid::new_v4())
    .bind(&email)
    .bind(password_hash)
    .fetch_optional(&state.db)
    .await?;
    let user = user.ok_or_else(|| ApiError::new(StatusCode::CONFLICT, "An account with this email already exists"))?;

    record_audit_log(&state.db, Some(user.id), "user_registered", json!({})).await;
    issue_token(&state, user)
}

pub async fn login(State(state): State<AppState>, Json(body): Json<Credentials>) -> ApiResult<AuthResponse> {
    let email = body.email.trim().to_lowercase();
    let user: Option<User> =
        sqlx::query_as("SELECT id, email, password_hash, created_at FROM users WHERE email = $1")
            .bind(&email)
            .fetch_optional(&state.db)
            .await?;

    match user {
        Some(u) if verify_password(&body.password, &u.password_hash) => {
            record_audit_log(&state.db, Some(u.id), "user_login", json!({})).await;
            issue_token(&state, u)
        }
        other => {
            record_audit_log(&state.db, other.map(|u| u.id), "user_login_failed", json!({})).await;
            Err(ApiError::unauthorized("Invalid email or password"))
        }
    }
}

/// JWTs are stateless; the client discards its token. Logged for the audit trail.
pub async fn logout(auth: AuthUser, State(state): State<AppState>) -> Json<Value> {
    record_audit_log(&state.db, Some(auth.user_id), "user_logout", json!({})).await;
    Json(json!({ "message": "Logged out" }))
}

pub async fn me(auth: AuthUser, State(state): State<AppState>) -> ApiResult<UserPublic> {
    let user: User = sqlx::query_as("SELECT id, email, password_hash, created_at FROM users WHERE id = $1")
        .bind(auth.user_id)
        .fetch_optional(&state.db)
        .await?
        .ok_or_else(|| ApiError::not_found("User not found"))?;
    Ok(Json(user.into()))
}
