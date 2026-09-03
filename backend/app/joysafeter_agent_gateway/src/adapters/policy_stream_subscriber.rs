use std::sync::atomic::{AtomicU32, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;

use tokio::sync::mpsc;
use tokio::time::interval;
use tokio_stream::StreamExt;
use tonic::transport::Channel;
use tonic::Request;
use tracing::{debug, error, info, warn};

use crate::application::GatewayApplication;
use crate::proto::policy_stream::{
    policy_event, policy_stream_service_client::PolicyStreamServiceClient, stream_message,
    subscribe_message, DeliveryReport, DeliveryStatus, PolicyEvent, StreamAck, SubscribeMessage,
    SubscribeRequest,
};

const STREAM_BUFFER_SIZE: usize = 2048;
const ACK_INTERVAL: Duration = Duration::from_secs(3);
const RECONNECT_BACKOFF_INITIAL: Duration = Duration::from_secs(1);
const RECONNECT_BACKOFF_MAX: Duration = Duration::from_secs(60);

pub struct PolicyStreamSubscriber {
    orchestrator_endpoint: String,
    instance_id: String,
    boot_id: String,
    application: Arc<GatewayApplication>,
    last_processed_seq: Arc<AtomicU64>,
    pending_count: Arc<AtomicU32>,
}

impl PolicyStreamSubscriber {
    pub fn new(
        orchestrator_endpoint: String,
        instance_id: String,
        application: Arc<GatewayApplication>,
    ) -> Self {
        Self {
            orchestrator_endpoint,
            instance_id,
            boot_id: uuid::Uuid::new_v4().to_string(),
            application,
            last_processed_seq: Arc::new(AtomicU64::new(0)),
            pending_count: Arc::new(AtomicU32::new(0)),
        }
    }

    /// 运行订阅循环(永久重连)
    pub async fn run(self: Arc<Self>) -> anyhow::Result<()> {
        let mut backoff = RECONNECT_BACKOFF_INITIAL;

        loop {
            match self.subscribe_loop().await {
                Ok(()) => {
                    info!("Policy stream ended normally");
                    backoff = RECONNECT_BACKOFF_INITIAL;
                }
                Err(e) => {
                    error!(error = %e, "Policy stream failed");
                    tokio::time::sleep(backoff).await;
                    backoff = (backoff * 2).min(RECONNECT_BACKOFF_MAX);
                }
            }

            info!(
                backoff_secs = backoff.as_secs(),
                "Reconnecting to policy stream"
            );
        }
    }

    async fn subscribe_loop(&self) -> anyhow::Result<()> {
        // 连接 orchestrator gRPC
        let channel = Channel::from_shared(self.orchestrator_endpoint.clone())?
            .connect()
            .await?;
        let mut client = PolicyStreamServiceClient::new(channel);

        // 创建双向 stream
        let (tx, rx) = mpsc::channel(STREAM_BUFFER_SIZE);
        let outbound = tokio_stream::wrappers::ReceiverStream::new(rx);

        // 发送订阅请求
        let resume_from_seq = self.last_processed_seq.load(Ordering::Relaxed);
        tx.send(SubscribeMessage {
            message: Some(subscribe_message::Message::Subscribe(SubscribeRequest {
                instance_id: self.instance_id.clone(),
                boot_id: self.boot_id.clone(),
                resume_from_seq,
            })),
        })
        .await?;

        // 启动订阅
        let mut inbound = client.subscribe(Request::new(outbound)).await?.into_inner();

        // 等待订阅响应
        match inbound.next().await {
            Some(Ok(msg)) => match msg.message {
                Some(stream_message::Message::SubscribeResponse(resp)) => {
                    if !resp.accepted {
                        anyhow::bail!("Subscription rejected");
                    }
                    info!(
                        session_id = %resp.session_id,
                        current_seq = resp.current_seq,
                        "Policy stream subscription accepted"
                    );
                }
                _ => anyhow::bail!("Unexpected first message"),
            },
            Some(Err(e)) => anyhow::bail!("Subscription failed: {}", e),
            None => anyhow::bail!("Stream closed before subscription response"),
        }

        // 启动 ACK 发送器
        let tx_clone = tx.clone();
        let last_processed = self.last_processed_seq.clone();
        let pending = self.pending_count.clone();
        tokio::spawn(async move {
            Self::ack_sender(tx_clone, last_processed, pending).await;
        });

        // 处理 event stream
        while let Some(result) = inbound.next().await {
            match result {
                Ok(msg) => {
                    if let Some(stream_message::Message::Event(event)) = msg.message {
                        self.handle_event(event, client.clone()).await;
                    }
                }
                Err(e) => {
                    error!(error = %e, "Stream error");
                    return Err(e.into());
                }
            }
        }

        Ok(())
    }

    async fn handle_event(
        &self,
        event: PolicyEvent,
        mut client: PolicyStreamServiceClient<Channel>,
    ) {
        let seq = event.seq;
        let trace_id = event.trace_id.clone();

        // Extract the identity needed for the delivery report before consuming
        // the event.
        let (sandbox_id, generation) = match &event.event {
            Some(policy_event::Event::Apply(apply)) => {
                (apply.sandbox_id.clone(), apply.generation.clone())
            }
            Some(policy_event::Event::Remove(remove)) => (
                remove.sandbox_id.clone(),
                remove.expected_generation.clone(),
            ),
            _ => (String::new(), None),
        };

        self.pending_count.fetch_add(1, Ordering::Relaxed);

        let app = self.application.clone();
        let pending = self.pending_count.clone();
        let last_processed = self.last_processed_seq.clone();

        tokio::spawn(async move {
            // 实际 apply policy
            let result = match event.event {
                Some(policy_event::Event::Apply(apply)) => {
                    app.apply_policy_from_stream(apply).await
                }
                Some(policy_event::Event::Remove(remove)) => {
                    app.remove_policy_from_stream(remove).await
                }
                Some(policy_event::Event::Placement(placement)) => {
                    app.reconcile_placement_from_stream(placement).await
                }
                _ => {
                    warn!("Unknown policy event type");
                    Ok(())
                }
            };

            // 回报 delivery 结果给 orchestrator(更新 networking_applied_version)
            if !sandbox_id.is_empty() {
                let (status, error_message) = match &result {
                    Ok(()) => (DeliveryStatus::Delivered as i32, String::new()),
                    Err(error) => (DeliveryStatus::Failed as i32, error.to_string()),
                };
                let report = DeliveryReport {
                    sandbox_id,
                    generation,
                    status,
                    error_message,
                    delivered_at: None,
                    trace_id,
                };
                if let Err(e) = client.report_delivery(Request::new(report)).await {
                    error!(error = %e, "Failed to report delivery to orchestrator");
                }
            }

            pending.fetch_sub(1, Ordering::Relaxed);
            last_processed.store(seq, Ordering::Relaxed);
        });
    }

    async fn ack_sender(
        tx: mpsc::Sender<SubscribeMessage>,
        last_processed_seq: Arc<AtomicU64>,
        pending_count: Arc<AtomicU32>,
    ) {
        let mut ticker = interval(ACK_INTERVAL);
        let mut last_acked = 0;

        loop {
            ticker.tick().await;

            let current_seq = last_processed_seq.load(Ordering::Relaxed);
            if current_seq > last_acked {
                let ack_msg = SubscribeMessage {
                    message: Some(subscribe_message::Message::Ack(StreamAck {
                        seq: current_seq,
                        pending_count: pending_count.load(Ordering::Relaxed),
                    })),
                };

                if tx.send(ack_msg).await.is_err() {
                    debug!("ACK sender: channel closed");
                    break;
                }

                last_acked = current_seq;
                debug!(acked_seq = current_seq, "Sent ACK to orchestrator");
            }
        }
    }
}
