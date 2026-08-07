//! Reusable Redis Stream utilities for the HA module.
//!
//! Provides common patterns for consuming Redis Streams with blocking reads,
//! connection retry with exponential backoff, and response parsing.

use std::time::Duration;

use tracing::warn;

/// Parse a Redis XREAD response into a list of `(entry_id, fields)` tuples.
///
/// XREAD returns: `[[stream_name, [[entry_id, [field, value, ...]], ...]]]`
/// We only read one stream at a time, so we take the first stream's entries.
pub fn parse_xread_response(value: &[redis::Value]) -> Option<Vec<(String, Vec<(String, String)>)>> {
    let stream = value.first()?;
    let stream_arr = match stream {
        redis::Value::Array(arr) => arr,
        _ => return None,
    };
    let entries_value = stream_arr.get(1)?;
    let entries_arr = match entries_value {
        redis::Value::Array(arr) => arr,
        _ => return None,
    };

    let mut result = Vec::new();
    for entry in entries_arr {
        let entry_arr = match entry {
            redis::Value::Array(arr) => arr,
            _ => continue,
        };
        let id = match entry_arr.first()? {
            redis::Value::BulkString(bytes) => String::from_utf8_lossy(bytes).to_string(),
            redis::Value::SimpleString(s) => s.clone(),
            _ => continue,
        };
        let fields_value = match entry_arr.get(1)? {
            redis::Value::Array(arr) => arr,
            _ => continue,
        };
        let mut fields = Vec::new();
        let mut iter = fields_value.iter();
        while let (Some(k), Some(v)) = (iter.next(), iter.next()) {
            let key = match k {
                redis::Value::BulkString(bytes) => String::from_utf8_lossy(bytes).to_string(),
                redis::Value::SimpleString(s) => s.clone(),
                _ => continue,
            };
            let val = match v {
                redis::Value::BulkString(bytes) => String::from_utf8_lossy(bytes).to_string(),
                redis::Value::SimpleString(s) => s.clone(),
                _ => continue,
            };
            fields.push((key, val));
        }
        result.push((id, fields));
    }

    if result.is_empty() {
        None
    } else {
        Some(result)
    }
}

/// A resilient Redis Stream consumer that handles connection failures with
/// exponential backoff and provides a consistent XREAD BLOCK loop pattern.
pub struct StreamConsumer {
    redis_client: redis::Client,
    stream_key: String,
    last_id: String,
    backoff: u64,
    block_ms: u64,
    batch_size: u64,
}

impl StreamConsumer {
    pub fn new(redis_client: redis::Client, stream_key: String) -> Self {
        Self {
            redis_client,
            stream_key,
            last_id: "$".to_string(),
            backoff: 1,
            block_ms: 5000,
            batch_size: 100,
        }
    }

    /// Read the next batch of entries from the stream.
    ///
    /// Returns `Some(entries)` on success, `None` on timeout (no new data).
    /// Handles connection failures internally with exponential backoff.
    pub async fn next_batch(&mut self) -> Option<Vec<(String, Vec<(String, String)>)>> {
        loop {
            let conn_result = self.redis_client.get_multiplexed_async_connection().await;
            let mut conn = match conn_result {
                Ok(c) => {
                    self.backoff = 1;
                    c
                }
                Err(e) => {
                    warn!(
                        stream = %self.stream_key,
                        "Stream consumer Redis connection failed: {e}, retrying in {}s",
                        self.backoff
                    );
                    tokio::time::sleep(Duration::from_secs(self.backoff)).await;
                    self.backoff = (self.backoff * 2).min(30);
                    continue;
                }
            };

            let result: redis::RedisResult<Vec<redis::Value>> = redis::cmd("XREAD")
                .arg("BLOCK")
                .arg(self.block_ms)
                .arg("COUNT")
                .arg(self.batch_size)
                .arg("STREAMS")
                .arg(&self.stream_key)
                .arg(&self.last_id)
                .query_async(&mut conn)
                .await;

            match result {
                Ok(streams) => {
                    if let Some(entries) = parse_xread_response(&streams) {
                        // Update last_id to the latest entry
                        if let Some((last_entry_id, _)) = entries.last() {
                            self.last_id = last_entry_id.clone();
                        }
                        return Some(entries);
                    }
                    // Timeout — no new entries
                    return None;
                }
                Err(e) => {
                    let err_str = format!("{e}");
                    if !err_str.contains("nil") {
                        warn!(
                            stream = %self.stream_key,
                            "Stream consumer XREAD error: {e}"
                        );
                        tokio::time::sleep(Duration::from_secs(1)).await;
                    }
                    return None;
                }
            }
        }
    }
}
