use anyhow::Context;
use redis::AsyncCommands;

#[derive(Clone)]
pub(crate) struct RedisTokenCache {
    client: redis::Client,
}

pub(crate) struct CachedToken {
    pub(crate) value: String,
    pub(crate) remaining_seconds: u64,
}

impl std::fmt::Debug for CachedToken {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("CachedToken")
            .field("value", &"<redacted>")
            .field("remaining_seconds", &self.remaining_seconds)
            .finish()
    }
}

impl RedisTokenCache {
    pub(crate) fn new(client: redis::Client) -> Self {
        Self { client }
    }

    pub(crate) async fn get(&self, key: &str) -> anyhow::Result<Option<CachedToken>> {
        let mut connection = self
            .client
            .get_multiplexed_async_connection()
            .await
            .context("connect to Agent Identity token cache")?;
        let (value, ttl): (Option<String>, i64) = redis::pipe()
            .cmd("GET")
            .arg(key)
            .cmd("TTL")
            .arg(key)
            .query_async(&mut connection)
            .await
            .context("read Agent Identity token cache")?;
        let Some(value) = value else {
            return Ok(None);
        };
        if ttl <= 0 {
            return Ok(None);
        }
        Ok(Some(CachedToken {
            value,
            remaining_seconds: ttl as u64,
        }))
    }

    pub(crate) async fn put(&self, key: &str, value: &str, ttl_seconds: u64) -> anyhow::Result<()> {
        let mut connection = self
            .client
            .get_multiplexed_async_connection()
            .await
            .context("connect to Agent Identity token cache")?;
        connection
            .set_ex::<_, _, ()>(key, value, ttl_seconds)
            .await
            .context("write Agent Identity token cache")
    }

    pub(crate) async fn delete(&self, key: &str) -> anyhow::Result<()> {
        let mut connection = self
            .client
            .get_multiplexed_async_connection()
            .await
            .context("connect to Agent Identity token cache")?;
        let _: usize = connection
            .del(key)
            .await
            .context("delete Agent Identity token cache entry")?;
        Ok(())
    }

    pub(crate) async fn scan(&self, pattern: &str) -> anyhow::Result<Vec<String>> {
        let mut connection = self
            .client
            .get_multiplexed_async_connection()
            .await
            .context("connect to Agent Identity token cache")?;
        let mut keys = Vec::new();
        let mut cursor = 0_u64;
        loop {
            let (next, mut batch): (u64, Vec<String>) = redis::cmd("SCAN")
                .arg(cursor)
                .arg("MATCH")
                .arg(pattern)
                .arg("COUNT")
                .arg(100)
                .query_async(&mut connection)
                .await
                .context("scan Agent Identity token cache")?;
            keys.append(&mut batch);
            cursor = next;
            if cursor == 0 {
                return Ok(keys);
            }
        }
    }
}

pub(crate) fn bot_token_key(
    platform_id: &str,
    tenant_scope: &str,
    agent_id: &str,
    auth_type: &str,
    user_id: &str,
    scope: &str,
) -> String {
    format!(
        "joysafeter:bot_token:{}:{:x}:{}:{}:{:x}:{:x}",
        platform_id,
        md5::compute(tenant_scope.as_bytes()),
        agent_id,
        auth_type,
        md5::compute(user_id.as_bytes()),
        md5::compute(scope.as_bytes()),
    )
}

pub(crate) fn user_token_key(
    platform_id: &str,
    agent_id: &str,
    auth_type: &str,
    identity_type: &str,
    user_name: &str,
) -> String {
    format!(
        "joysafeter:user_token:{platform_id}:{agent_id}:{auth_type}:{identity_type}:{user_name}"
    )
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn agent_token_key(
    platform_id: &str,
    project_id: &str,
    user_id: &str,
    agent_id: &str,
    session_id: &str,
    task_id: &str,
    endpoint: &str,
    scope: &str,
) -> String {
    format!(
        "joysafeter:agent_token:{platform_id}:{project_id}:{agent_id}:{:x}:{session_id}:{task_id}:{:x}:{:x}",
        md5::compute(user_id.as_bytes()),
        md5::compute(endpoint.as_bytes()),
        md5::compute(scope.as_bytes()),
    )
}

#[cfg(test)]
#[path = "token_cache_test.rs"]
mod tests;
