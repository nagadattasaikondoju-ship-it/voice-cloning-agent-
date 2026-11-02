use axum::{extract::State, http::StatusCode, Json};
use serde_json::json;
use uuid::Uuid;

use crate::{
    auth::{create_jwt, hash_password, verify_password, AuthUser},
    db::{record_audit_log, AppState},
    models::{AuthResponse, LoginRequest, RegisterRequest, User, UserPublic},
};

pub async fn register(
    State(state): State<AppState>,
    Json(body): Json<RegisterRequest>,
) -> Result<Json<AuthResponse>, (StatusCode, Json<serde_json::Value>)> {
    let email = body.email.trim().to_lowercase();
    if email.is_empty() || body.password.len() < 8 {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({ "message": "Email is required and password must be at least 8 characters" })),
        ));
    }

    // Check if user already exists
    let existing: Option<User> = sqlx::query_as!(
        User,
        "SELECT id, email, password_hash, created_at FROM users WHERE email = $1",
        email
    )
    .fetch_optional(&state.db)
    .await
    .map_err(|e| {
        tracing::error!("Database query error: {:?}", e);
        (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({ "message": "Internal error" })))
    })?;

    if existing.is_some() {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({ "message": "User with this email already exists" })),
        ));
    }

    let password_hash = hash_password(&body.password).map_err(|_| {
        (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({ "message": "Error hashing password" })))
    })?;

    let user_id = Uuid::new_v4();
    let new_user: User = sqlx::query_as!(
        User,
        r#"
        INSERT INTO users (id, email, password_hash)
        VALUES ($1, $2, $3)
        RETURNING id, email, password_hash, created_at
        "#,
        user_id,
        email,
        password_hash
    )
    .fetch_one(&state.db)
    .await
    .map_err(|e| {
        tracing::error!("Failed to insert user: {:?}", e);
        (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({ "message": "Failed to create user" })))
    })?;

    record_audit_log(&state.db, Some(user_id), "user_registered", json!({ "email": email }), None).await;

    let token = create_jwt(&new_user.id, &new_user.email, &state.config.jwt_secret).map_err(|_| {
        (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({ "message": "Failed to generate token" })))
    })?;

    Ok(Json(AuthResponse {
        token,
        user: UserPublic {
            id: new_user.id,
            email: new_user.email,
            created_at: new_user.created_at,
        },
    }))
}

pub async fn login(
    State(state): State<AppState>,
    Json(body): Json<LoginRequest>,
) -> Result<Json<AuthResponse>, (StatusCode, Json<serde_json::Value>)> {
    let email = body.email.trim().to_lowercase();

    let user: User = sqlx::query_as!(
        User,
        "SELECT id, email, password_hash, created_at FROM users WHERE email = $1",
        email
    )
    .fetch_optional(&state.db)
    .await
    .map_err(|_| {
        (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({ "message": "Database query error" })))
    })?
    .ok_or_else(|| {
        (StatusCode::UNAUTHORIZED, Json(json!({ "message": "Invalid email or password" })))
    })?;

    if !verify_password(&body.password, &user.password_hash) {
        return Err((
            StatusCode::UNAUTHORIZED,
            Json(json!({ "message": "Invalid email or password" })),
        ));
    }

    record_audit_log(&state.db, Some(user.id), "user_login", json!({ "email": email }), None).await;

    let token = create_jwt(&user.id, &user.email, &state.config.jwt_secret).map_err(|_| {
        (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({ "message": "Failed to generate token" })))
    })?;

    Ok(Json(AuthResponse {
        token,
        user: UserPublic {
            id: user.id,
            email: user.email,
            created_at: user.created_at,
        },
    }))
}

pub async fn logout(
    auth: AuthUser,
    State(state): State<AppState>,
) -> Result<Json<serde_json::Value>, StatusCode> {
    record_audit_log(&state.db, Some(auth.user_id), "user_logout", json!({}), None).await;
    Ok(Json(json!({ "message": "Logged out successfully" })))
}

pub async fn me(
    auth: AuthUser,
    State(state): State<AppState>,
) -> Result<Json<UserPublic>, (StatusCode, Json<serde_json::Value>)> {
    let user: User = sqlx::query_as!(
        User,
        "SELECT id, email, password_hash, created_at FROM users WHERE id = $1",
        auth.user_id
    )
    .fetch_optional(&state.db)
    .await
    .map_err(|_| {
        (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({ "message": "Database query error" })))
    })?
    .ok_or_else(|| {
        (StatusCode::NOT_FOUND, Json(json!({ "message": "User not found" })))
    })?;

    Ok(Json(UserPublic {
        id: user.id,
        email: user.email,
        created_at: user.created_at,
    }))
}
