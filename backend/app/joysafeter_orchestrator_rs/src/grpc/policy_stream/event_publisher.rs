use std::sync::atomic::{AtomicU32, AtomicU64, Ordering};
use std::sync::Arc;

use dashmap::DashMap;
use tokio::sync::mpsc;
use tracing::{info, warn};

use crate::proto::policy_stream::PolicyEvent;

const DEFAULT_SUBSCRIBER_BUFFER: usize = 2048;
const MAX_BACKPRESSURE_PENDING: u32 = 1000;

/// 零拷贝 policy event 发布器
///
/// 多订阅者广播,使用 Arc<PolicyEvent> 避免重复序列化
pub struct EventPublisher {
    seq_counter: Arc<AtomicU64>,
    subscribers: Arc<DashMap<String, SubscriberState>>,
}

struct SubscriberState {
    tx: mpsc::Sender<Arc<PolicyEvent>>,
    last_ack_seq: Arc<AtomicU64>,
    pending_count: Arc<AtomicU32>,
}

impl EventPublisher {
    pub fn new() -> Self {
        Self {
            seq_counter: Arc::new(AtomicU64::new(0)),
            subscribers: Arc::new(DashMap::new()),
        }
    }

    /// 发布 event 到所有订阅者(零拷贝)
    pub async fn publish_event(&self, mut event: PolicyEvent) {
        // 分配全局序列号
        let seq = self.seq_counter.fetch_add(1, Ordering::SeqCst) + 1;
        event.seq = seq;
        event.timestamp = Some(prost_types::Timestamp::from(std::time::SystemTime::now()));

        let event = Arc::new(event); // 零拷贝,所有订阅者共享
        let mut failed_sessions = Vec::new();

        // 并行推送到所有订阅者
        for entry in self.subscribers.iter() {
            let session_id = entry.key();
            let state = entry.value();

            // 背压检测:gateway 积压过多时跳过或断开
            let pending = state.pending_count.load(Ordering::Relaxed);
            if pending > MAX_BACKPRESSURE_PENDING {
                warn!(
                    session_id = %session_id,
                    pending_count = pending,
                    "Subscriber backpressure, skipping event"
                );
                continue;
            }

            // try_send 非阻塞:满了立即失败
            if state.tx.try_send(event.clone()).is_err() {
                warn!(
                    session_id = %session_id,
                    "Subscriber channel full, marking for disconnect"
                );
                failed_sessions.push(session_id.clone());
            }
        }

        // 清理失败的订阅者
        for session_id in failed_sessions {
            self.remove_subscriber(&session_id);
        }
    }

    /// 注册新订阅者
    pub fn add_subscriber(
        &self,
        session_id: String,
        buffer_size: Option<usize>,
    ) -> mpsc::Receiver<Arc<PolicyEvent>> {
        let buffer_size = buffer_size.unwrap_or(DEFAULT_SUBSCRIBER_BUFFER);
        let (tx, rx) = mpsc::channel(buffer_size);

        self.subscribers.insert(
            session_id.clone(),
            SubscriberState {
                tx,
                last_ack_seq: Arc::new(AtomicU64::new(0)),
                pending_count: Arc::new(AtomicU32::new(0)),
            },
        );

        info!(
            session_id = %session_id,
            buffer_size,
            subscribers_total = self.subscribers.len(),
            "Subscriber registered"
        );

        rx
    }

    /// 移除订阅者
    pub fn remove_subscriber(&self, session_id: &str) {
        self.subscribers.remove(session_id);
        info!(
            session_id = %session_id,
            subscribers_total = self.subscribers.len(),
            "Subscriber removed"
        );
    }

    /// 更新订阅者 ACK 状态
    pub fn update_subscriber_ack(&self, session_id: &str, seq: u64, pending_count: u32) {
        if let Some(state) = self.subscribers.get(session_id) {
            state.last_ack_seq.store(seq, Ordering::Relaxed);
            state.pending_count.store(pending_count, Ordering::Relaxed);
        }
    }

    /// 获取当前序列号
    pub fn current_seq(&self) -> u64 {
        self.seq_counter.load(Ordering::SeqCst)
    }

    /// 获取订阅者数量
    pub fn subscriber_count(&self) -> usize {
        self.subscribers.len()
    }
}

impl Default for EventPublisher {
    fn default() -> Self {
        Self::new()
    }
}
