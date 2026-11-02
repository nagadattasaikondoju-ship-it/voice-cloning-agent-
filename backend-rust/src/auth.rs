use axum::{
    async_trait,
    extract::FromRequestParts,
    http::{header, request::Parts},
};
use chrono::{Duration, Utc};
use jsonwebtoken::{decode, encode, DecodingKey, EncodingKey, Header, Validation};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::{db::AppState, error::ApiError};

#[derive(Debug, Serialize, Deserialize)]
pub struct Claims {
    pub sub: String,
    pub email: String,
    pub exp: i64,
    pub iat: i64,
}

pub fn create_jwt(user_id: &Uuid, email: &str, secret: &str) -> Result<String, jsonwebtoken::errors::Error> {
    let now = Utc::now();
    let claims = Claims {
        sub: user_id.to_string(),
        email: email.to_string(),
        exp: (now + Duration::hours(24)).timestamp(),
        iat: now.timestamp(),
    };
    encode(&Header::default(), &claims, &EncodingKey::from_secret(secret.as_bytes()))
}

pub fn verify_jwt(token: &str, secret: &str) -> Result<Claims, jsonwebtoken::errors::Error> {
    let validation = Validation::default(); // HS256, validates exp
    Ok(decode::<Claims>(token, &DecodingKey::from_secret(secret.as_bytes()), &validation)?.claims)
}

pub fn hash_password(password: &str) -> Result<String, bcrypt::BcryptError> {
    bcrypt::hash(password, bcrypt::DEFAULT_COST)
}

pub fn verify_password(password: &str, hash: &str) -> bool {
    bcrypt::verify(password, hash).unwrap_or(false)
}

/// Authenticated user extracted from `Authorization: Bearer <jwt>`.
pub struct AuthUser {
    pub user_id: Uuid,
    #[allow(dead_code)]
    pub email: String,
}

#[async_trait]
impl FromRequestParts<AppState> for AuthUser {
    type Rejection = ApiError;

    async fn from_request_parts(parts: &mut Parts, state: &AppState) -> Result<Self, Self::Rejection> {
        let token = parts
            .headers
            .get(header::AUTHORIZATION)
            .and_then(|v| v.to_str().ok())
            .and_then(|v| v.strip_prefix("Bearer "))
            .map(str::trim)
            .ok_or_else(|| ApiError::unauthorized("Missing or malformed Authorization header"))?;

        let claims = verify_jwt(token, &state.config.jwt_secret)
            .map_err(|_| ApiError::unauthorized("Invalid or expired token"))?;
        let user_id = Uuid::parse_str(&claims.sub)
            .map_err(|_| ApiError::unauthorized("Invalid token subject"))?;

        Ok(AuthUser { user_id, email: claims.email })
    }
}
