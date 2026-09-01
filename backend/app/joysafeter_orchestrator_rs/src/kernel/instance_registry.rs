use std::sync::Arc;
use std::time::Duration;

use redis::AsyncCommands;
use tracing::{info, warn};

const REFRESH_REGISTRATION_SCRIPT: &str = r#"
redis.call('HSET', KEYS[1],
  'grpc_addr', ARGV[1],
  'http_addr', ARGV[2],
  'started_at', ARGV[3])
redis.call('EXPIRE', KEYS[1], ARGV[4])
return 1
"#;

pub struct RedisInstanceRegistry {
    client: redis::Client,
    instance_id: String,
    key: String,
    heartbeat_interval: Duration,
    heartbeat_ttl: Duration,
    started_at: String,
}

impl RedisInstanceRegistry {
    pub fn new(
        client: redis::Client,
        instance_id: &str,
        heartbeat_interval: u64,
        heartbeat_ttl: u64,
    ) -> Self {
        Self {
            client,
            instance_id: instance_id.to_string(),
            key: format!("joysafeter:instances:{instance_id}"),
            heartbeat_interval: Duration::from_secs(heartbeat_interval),
            heartbeat_ttl: Duration::from_secs(heartbeat_ttl),
            started_at: chrono::Utc::now().timestamp().to_string(),
        }
    }

    pub async fn register(&self) -> anyhow::Result<()> {
        self.refresh().await?;
        info!(instance_id = %self.instance_id, "Registered instance in Redis");
        Ok(())
    }

    pub async fn run(self: Arc<Self>) {
        let mut interval = tokio::time::interval(self.heartbeat_interval);
        interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
        interval.tick().await;
        loop {
            interval.tick().await;
            if let Err(error) = self.refresh().await {
                warn!(instance_id = %self.instance_id, %error, "Redis instance heartbeat failed");
            }
        }
    }

    pub async fn deregister(&self) -> anyhow::Result<()> {
        let mut connection = self.client.get_multiplexed_async_connection().await?;
        connection.del::<_, ()>(&self.key).await?;
        info!(instance_id = %self.instance_id, "Deregistered instance from Redis");
        Ok(())
    }

    async fn refresh(&self) -> anyhow::Result<()> {
        let mut connection = self.client.get_multiplexed_async_connection().await?;
        redis::Script::new(REFRESH_REGISTRATION_SCRIPT)
            .key(&self.key)
            .arg("")
            .arg("")
            .arg(&self.started_at)
            .arg(self.heartbeat_ttl.as_secs())
            .invoke_async::<i32>(&mut connection)
            .await?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::sync::Arc;
    use std::time::Duration;

    use redis::AsyncCommands;

    use super::RedisInstanceRegistry;

    async fn redis_client() -> Option<redis::Client> {
        let url =
            std::env::var("REDIS_URL").unwrap_or_else(|_| "redis://127.0.0.1:6379/".to_string());
        let client = redis::Client::open(url).ok()?;
        let mut connection = client.get_multiplexed_async_connection().await.ok()?;
        redis::cmd("PING")
            .query_async::<String>(&mut connection)
            .await
            .ok()?;
        Some(client)
    }

    #[tokio::test]
    async fn heartbeat_recreates_deleted_registration_with_complete_metadata() {
        let Some(client) = redis_client().await else {
            return;
        };
        let instance_id = format!("registry-test-{}", uuid::Uuid::now_v7());
        let key = format!("joysafeter:instances:{instance_id}");
        let registry = Arc::new(RedisInstanceRegistry::new(
            client.clone(),
            &instance_id,
            1,
            5,
        ));
        registry.register().await.expect("initial registration");

        let mut connection = client
            .get_multiplexed_async_connection()
            .await
            .expect("Redis connection");
        let initial: HashMap<String, String> = connection.hgetall(&key).await.expect("metadata");
        assert_eq!(initial.get("grpc_addr").map(String::as_str), Some(""));
        assert_eq!(initial.get("http_addr").map(String::as_str), Some(""));
        let started_at = initial.get("started_at").cloned().expect("started_at");
        connection.del::<_, ()>(&key).await.expect("delete key");

        let heartbeat = tokio::spawn(registry.clone().run());
        tokio::time::timeout(Duration::from_secs(3), async {
            loop {
                if connection
                    .exists::<_, bool>(&key)
                    .await
                    .expect("key existence")
                {
                    break;
                }
                tokio::time::sleep(Duration::from_millis(25)).await;
            }
        })
        .await
        .expect("heartbeat must recreate the deleted key");
        heartbeat.abort();

        let repaired: HashMap<String, String> = connection.hgetall(&key).await.expect("metadata");
        assert_eq!(repaired.get("started_at"), Some(&started_at));
        assert!(connection.ttl::<_, i64>(&key).await.expect("ttl") > 0);
        connection.del::<_, ()>(&key).await.expect("cleanup key");
    }
}
