use sqlx::postgres::{PgPool, PgPoolOptions};

/// Create the PostgreSQL connection pool.
///
/// Pool size is configurable via environment variables:
///   - `DATABASE_POOL_SIZE`: max connections (default 20)
///   - `DATABASE_MIN_CONNECTIONS`: min idle connections (default 2)
pub async fn create_pool(database_url: &str) -> Result<PgPool, sqlx::Error> {
    let max_conn: u32 = std::env::var("DATABASE_POOL_SIZE")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(20);
    let min_conn: u32 = std::env::var("DATABASE_MIN_CONNECTIONS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(2);

    PgPoolOptions::new()
        .max_connections(max_conn)
        .min_connections(min_conn)
        .acquire_timeout(std::time::Duration::from_secs(10))
        .connect(database_url)
        .await
}
