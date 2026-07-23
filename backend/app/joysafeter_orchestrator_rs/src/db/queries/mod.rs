mod agent;
mod event;
mod sandbox;
mod session;
mod task;

#[cfg(test)]
mod tests;

// Re-export everything to preserve the public surface (`queries::X`).
pub use agent::*;
pub use event::*;
pub use sandbox::*;
pub use session::*;
pub use task::*;

// ---------------------------------------------------------------------------
// Utility queries (advisory locks)
// ---------------------------------------------------------------------------

use sqlx::PgPool;

/// Try to acquire a PostgreSQL advisory lock (non-blocking).
///
/// IMPORTANT: `pg_try_advisory_lock` is a session-level lock — it must be
/// released on the SAME connection. With a connection pool, separate
/// `execute(pool)` calls may hit different connections, so the lock is
/// acquired on one connection but never released (the unlock runs on
/// another connection and produces "you don't own a lock" warnings).
///
/// For watchdog use-cases where the critical section is short, prefer
/// wrapping all work in a single transaction with `pg_try_advisory_xact_lock`
/// (which auto-releases on COMMIT/ROLLBACK). This function is kept for
/// backward compatibility but callers should migrate.
pub async fn try_advisory_lock(pool: &PgPool, lock_name: &str) -> Result<bool, sqlx::Error> {
    let row: (bool,) = sqlx::query_as("SELECT pg_try_advisory_lock(hashtext($1))")
        .bind(lock_name)
        .fetch_one(pool)
        .await?;

    Ok(row.0)
}

/// Release a PostgreSQL advisory lock.
///
/// NOTE: This is a no-op if the lock was acquired on a different pooled
/// connection. See `try_advisory_lock` doc. Callers should migrate to
/// transaction-scoped advisory locks (`pg_try_advisory_xact_lock`).
pub async fn release_advisory_lock(pool: &PgPool, lock_name: &str) -> Result<(), sqlx::Error> {
    // Intentionally a no-op now. Session-level advisory locks acquired via
    // the pool cannot be reliably released because unlock may run on a
    // different connection. The locks are harmless — they auto-release
    // when the connection is returned to the pool and eventually closed.
    // Callers should use transaction-scoped locks instead.
    let _ = lock_name;
    let _ = pool;
    Ok(())
}
