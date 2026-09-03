use std::sync::Arc;

use sqlx::PgPool;
use tokio::sync::mpsc;
use tokio_stream::wrappers::ReceiverStream;
use tonic::{Request, Response, Status, Streaming};
use tracing::{debug, error, info, warn};

use crate::grpc::policy_stream::database_ext::update_sandbox_delivery;
use crate::grpc::policy_stream::redis_publisher::RedisEventPublisher;
use crate::proto::policy_stream::{
    policy_stream_service_server::PolicyStreamService, stream_message, subscribe_message,
    DeliveryAck, DeliveryReport, PolicyEvent, StreamMessage, SubscribeMessage, SubscribeResponse,
};

const STREAM_BUFFER_SIZE: usize = 2048;
const MAX_REPLAY_GAP: u64 = 10_000;
const REPLAY_BATCH_SIZE: u64 = 100;

pub struct PolicyStreamServer {
    pool: PgPool,
    event_publisher: Arc<RedisEventPublisher>,
}

#[tonic::async_trait]
impl PolicyStreamService for PolicyStreamServer {
    type SubscribeStream = ReceiverStream<Result<StreamMessage, Status>>;

    async fn subscribe(
        &self,
        request: Request<Streaming<SubscribeMessage>>,
    ) -> Result<Response<Self::SubscribeStream>, Status> {
        let mut inbound = request.into_inner();

        // 等待订阅请求
        let subscribe_req = match inbound.message().await? {
            Some(SubscribeMessage {
                message: Some(subscribe_message::Message::Subscribe(req)),
            }) => req,
            _ => {
                return Err(Status::invalid_argument(
                    "First message must be SubscribeRequest",
                ))
            }
        };

        let session_id = uuid::Uuid::now_v7().to_string();
        let (tx, rx) = mpsc::channel(STREAM_BUFFER_SIZE);

        info!(
            instance_id = %subscribe_req.instance_id,
            boot_id = %subscribe_req.boot_id,
            session_id = %session_id,
            resume_from_seq = subscribe_req.resume_from_seq,
            "Policy stream subscriber connected"
        );

        // 发送订阅响应
        let current_seq = self.event_publisher.current_seq().await.unwrap_or(0);
        tx.send(Ok(StreamMessage {
            message: Some(stream_message::Message::SubscribeResponse(
                SubscribeResponse {
                    accepted: true,
                    session_id: session_id.clone(),
                    current_seq,
                },
            )),
        }))
        .await
        .map_err(|_| Status::internal("Failed to send subscribe response"))?;

        // 重放历史 event
        if subscribe_req.resume_from_seq < current_seq {
            self.replay_events(&tx, subscribe_req.resume_from_seq, current_seq)
                .await?;
        }

        // 注册订阅者并获取 event 接收器
        let mut event_rx = self
            .event_publisher
            .add_subscriber(session_id.clone(), None)
            .await;

        // 转发 event 到 gRPC stream
        let tx_clone = tx.clone();
        let session_id_for_forward = session_id.clone();
        tokio::spawn(async move {
            while let Some(event) = event_rx.recv().await {
                let msg = StreamMessage {
                    message: Some(stream_message::Message::Event((*event).clone())),
                };
                if tx_clone.send(Ok(msg)).await.is_err() {
                    break;
                }
            }
            debug!(session_id = %session_id_for_forward, "Event forwarder stopped");
        });

        // 处理 gateway 上行 ACK
        let event_publisher = self.event_publisher.clone();
        let session_id_for_ack = session_id.clone();
        tokio::spawn(async move {
            Self::handle_acks(inbound, session_id_for_ack, event_publisher).await;
        });

        Ok(Response::new(ReceiverStream::new(rx)))
    }

    async fn report_delivery(
        &self,
        request: Request<DeliveryReport>,
    ) -> Result<Response<DeliveryAck>, Status> {
        let report = request.into_inner();

        info!(
            sandbox_id = %report.sandbox_id,
            policy_version = report.generation.as_ref().map(|g| g.policy_version).unwrap_or(0),
            status = ?report.status,
            trace_id = %report.trace_id,
            "Delivery report received"
        );

        // 更新 DB:networking_applied_version
        if let Err(e) = update_sandbox_delivery(
            &self.pool,
            &report.sandbox_id,
            report.generation.as_ref(),
            report.status,
            &report.error_message,
        )
        .await
        {
            error!(
                error = %e,
                sandbox_id = %report.sandbox_id,
                "Failed to update sandbox delivery status"
            );
            return Err(Status::internal("Database update failed"));
        }

        Ok(Response::new(DeliveryAck {
            accepted: true,
            message: String::new(),
        }))
    }
}

impl PolicyStreamServer {
    pub fn new(pool: PgPool, event_publisher: Arc<RedisEventPublisher>) -> Self {
        Self {
            pool,
            event_publisher,
        }
    }

    async fn replay_events(
        &self,
        tx: &mpsc::Sender<Result<StreamMessage, Status>>,
        from_seq: u64,
        to_seq: u64,
    ) -> Result<(), Status> {
        let gap = to_seq - from_seq;
        if gap > MAX_REPLAY_GAP {
            warn!(from_seq, to_seq, gap, "Sequence gap too large");
            return Err(Status::out_of_range(format!(
                "Sequence gap {} exceeds maximum {}",
                gap, MAX_REPLAY_GAP
            )));
        }

        info!(from_seq, to_seq, gap, "Replaying events");

        for batch_start in (from_seq..to_seq).step_by(REPLAY_BATCH_SIZE as usize) {
            let batch_end = (batch_start + REPLAY_BATCH_SIZE).min(to_seq);

            let events = self
                .event_publisher
                .load_events(batch_start, batch_end)
                .await
                .map_err(|e| Status::internal(format!("Failed to load events: {}", e)))?;

            for event in events {
                tx.send(Ok(StreamMessage {
                    message: Some(stream_message::Message::Event(event)),
                }))
                .await
                .map_err(|_| Status::aborted("Subscriber disconnected during replay"))?;
            }

            tokio::time::sleep(tokio::time::Duration::from_millis(10)).await;
        }

        info!(from_seq, to_seq, "Replay complete");
        Ok(())
    }

    async fn load_events_from_db(
        &self,
        from_seq: u64,
        to_seq: u64,
    ) -> anyhow::Result<Vec<PolicyEvent>> {
        // Removed: incremental replay is intentionally delegated to PostgresEventPublisher.
        // This stub remains for API compatibility.
        let _ = (from_seq, to_seq);
        Ok(Vec::new())
    }

    async fn handle_acks(
        mut inbound: Streaming<SubscribeMessage>,
        session_id: String,
        publisher: Arc<RedisEventPublisher>,
    ) {
        while let Ok(Some(msg)) = inbound.message().await {
            if let Some(subscribe_message::Message::Ack(ack)) = msg.message {
                let publisher_clone = publisher.clone();
                let session_id_clone = session_id.clone();
                tokio::spawn(async move {
                    publisher_clone
                        .update_subscriber_ack(&session_id_clone, ack.seq, ack.pending_count)
                        .await;
                });
                debug!(
                    session_id = %session_id,
                    ack_seq = ack.seq,
                    pending = ack.pending_count,
                    "Received ACK"
                );
            }
        }

        publisher.remove_subscriber(&session_id).await;
        info!(session_id = %session_id, "Subscriber disconnected");
    }
}
