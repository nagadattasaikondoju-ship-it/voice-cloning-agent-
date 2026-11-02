use crate::config::Config;
use redis::AsyncCommands;
use serde::Serialize;
use sqlx::{postgres::PgPoolOptions, PgPool};
use uuid::Uuid;

#[derive(Clone)]
pub struct AppState {
    pub db: PgPool,
    pub redis: redis::Client,
    pub http: reqwest::Client,
    pub config: Config,
}

pub async fn init_db(database_url: &str) -> anyhow::Result<PgPool> {
    let pool = PgPoolOptions::new().max_connections(20).connect(database_url).await?;
    sqlx::migrate!("./migrations").run(&pool).await?;
    Ok(pool)
}

/// Push a JSON job onto a Redis list consumed by the Python worker (BRPOP).
pub async fn enqueue<T: Serialize>(redis: &redis::Client, queue: &str, job: &T) -> anyhow::Result<()> {
    let mut con = redis.get_multiplexed_async_connection().await?;
    let payload = serde_json::to_string(job)?;
    con.lpush::<_, _, ()>(queue, payload).await?;
    Ok(())
}

pub async fn record_audit_log(
    db: &PgPool,
    user_id: Option<Uuid>,
    action: &str,
    details: serde_json::Value,
) {
    let result = sqlx::query(
        "INSERT INTO audit_logs (id, user_id, action, details) VALUES ($1, $2, $3, $4)",
    )
    .bind(Uuid::new_v4())
    .bind(user_id)
    .bind(action)
    .bind(details)
    .execute(db)
    .await;
    if let Err(e) = result {
        tracing::warn!("Failed to write audit log '{action}': {e:?}");
    }
}
