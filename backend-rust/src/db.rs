use crate::config::Config;
use sqlx::{postgres::PgPoolOptions, PgPool};
use uuid::Uuid;

#[derive(Clone)]
pub struct AppState {
    pub db: PgPool,
    pub redis: redis::Client,
    pub config: Config,
}

pub async fn init_db(database_url: &str) -> Result<PgPool, sqlx::Error> {
    let pool = PgPoolOptions::new()
        .max_connections(20)
        .connect(database_url)
        .await?;

    // Run schema migrations automatically on startup if migrations folder exists
    sqlx::migrate!("./migrations")
        .run(&pool)
        .await
        .ok();

    Ok(pool)
}

pub async fn record_audit_log(
    db: &PgPool,
    user_id: Option<Uuid>,
    action: &str,
    details: serde_json::Value,
    ip_address: Option<&str>,
) {
    let log_id = Uuid::new_v4();
    let _ = sqlx::query!(
        r#"
        INSERT INTO audit_logs (id, user_id, action, details, ip_address)
        VALUES ($1, $2, $3, $4, $5)
        "#,
        log_id,
        user_id,
        action,
        details,
        ip_address
    )
    .execute(db)
    .await;
}
