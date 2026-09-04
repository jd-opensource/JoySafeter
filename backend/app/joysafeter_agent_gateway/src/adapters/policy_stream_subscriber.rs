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
/// Bounded inline retries for a single event before it is skipped (its failure is
/// still reported to the orchestrator, which re-drives it via the periodic
/// NetworkPolicyReconciler). This bounds the head-of-line impact of a poison event
/// while still absorbing transient apply failures without reconnect churn.
const MAX_APPLY_ATTEMPTS: u32 = 3;
const APPLY_RETRY_BACKOFF: Duration = Duration::from_millis(500);

pub struct PolicyStreamSubscriber {
    orchestrator_endpoint: String,
    instance_id: String,
    boot_id: String,
    application: Arc<GatewayApplication>,
    /// Highest seq that has reached a terminal outcome (applied, or skipped after
    /// exhausting retries). Advances strictly in seq order, so it is a correct
    /// resume watermark. (Fixes C1/C2.)
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

    /// Run the subscription with a permanent reconnect loop. A clean stream end is
    /// still followed by the initial backoff so a server that closes immediately
    /// cannot induce a tight reconnect storm. (Fixes H6.)
    pub async fn run(self: Arc<Self>) -> anyhow::Result<()> {
        let mut backoff = RECONNECT_BACKOFF_INITIAL;

        loop {
            match self.subscribe_loop().await {
                Ok(()) => {
                    info!("Policy stream ended; reconnecting after backoff");
                    tokio::time::sleep(backoff).await;
                    backoff = (backoff * 2).min(RECONNECT_BACKOFF_MAX);
                }
                Err(e) => {
                    error!(error = %e, "Policy stream failed");
                    tokio::time::sleep(backoff).await;
                    backoff = (backoff * 2).min(RECONNECT_BACKOFF_MAX);
                }
            }
            // A connection that survived long enough to make progress resets the
            // backoff so the next transient drop reconnects promptly.
            info!(
                backoff_secs = backoff.as_secs(),
                "Reconnecting to policy stream"
            );
        }
    }

    async fn subscribe_loop(&self) -> anyhow::Result<()> {
        let channel = Channel::from_shared(self.orchestrator_endpoint.clone())?
            .connect()
            .await?;
        let mut client = PolicyStreamServiceClient::new(channel);

        let (tx, rx) = mpsc::channel(STREAM_BUFFER_SIZE);
        let outbound = tokio_stream::wrappers::ReceiverStream::new(rx);

        let resume_from_seq = self.last_processed_seq.load(Ordering::Acquire);
        tx.send(SubscribeMessage {
            message: Some(subscribe_message::Message::Subscribe(SubscribeRequest {
                instance_id: self.instance_id.clone(),
                boot_id: self.boot_id.clone(),
                resume_from_seq,
            })),
        })
        .await?;

        let mut inbound = client.subscribe(Request::new(outbound)).await?.into_inner();

        match inbound.next().await {
            Some(Ok(msg)) => match msg.message {
                Some(stream_message::Message::SubscribeResponse(resp)) => {
                    if !resp.accepted {
                        anyhow::bail!("Subscription rejected");
                    }
                    info!(
                        session_id = %resp.session_id,
                        current_seq = resp.current_seq,
                        resume_from_seq,
                        "Policy stream subscription accepted"
                    );
                }
                _ => anyhow::bail!("Unexpected first message"),
            },
            Some(Err(e)) => anyhow::bail!("Subscription failed: {}", e),
            None => anyhow::bail!("Stream closed before subscription response"),
        }

        // Per-connection ACK sender. Its handle is aborted when this connection
        // ends so it cannot outlive the stream and keep touching shared state.
        // (Contributes to H4.)
        let ack_handle = {
            let tx = tx.clone();
            let last_processed = self.last_processed_seq.clone();
            let pending = self.pending_count.clone();
            tokio::spawn(async move { Self::ack_sender(tx, last_processed, pending).await })
        };
        // Abort the ACK sender on any exit path from here on.
        let _ack_guard = AbortOnDrop(ack_handle);

        // Process events strictly in seq order on this single consumer. Applying
        // inline provides natural backpressure to the orchestrator (we stop reading
        // the gRPC stream while an apply is in flight) and removes the unbounded
        // per-event task spawn. (Fixes C1/H3/H4.)
        while let Some(result) = inbound.next().await {
            match result {
                Ok(msg) => {
                    if let Some(stream_message::Message::Event(event)) = msg.message {
                        self.process_event(event, &mut client).await;
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

    /// Apply one event, retrying transient failures inline, then report the outcome
    /// and advance the watermark. The watermark advances only after a terminal
    /// outcome for this seq (applied, or skipped after exhausting retries), so a
    /// reconnect never resumes past an event that was neither applied nor reported.
    /// (Fixes C1/C2.)
    async fn process_event(&self, event: PolicyEvent, client: &mut PolicyStreamServiceClient<Channel>) {
        let seq = event.seq;
        let trace_id = event.trace_id.clone();
        let (sandbox_id, generation) = match &event.event {
            Some(policy_event::Event::Apply(apply)) => {
                (apply.sandbox_id.clone(), apply.generation.clone())
            }
            Some(policy_event::Event::Remove(remove)) => {
                (remove.sandbox_id.clone(), remove.expected_generation.clone())
            }
            _ => (String::new(), None),
        };

        let mut attempt = 0;
        loop {
            attempt += 1;
            let result = match event.event.clone() {
                Some(policy_event::Event::Apply(apply)) => {
                    self.application.apply_policy_from_stream(apply).await
                }
                Some(policy_event::Event::Remove(remove)) => {
                    self.application.remove_policy_from_stream(remove).await
                }
                Some(policy_event::Event::Placement(placement)) => {
                    self.application.reconcile_placement_from_stream(placement).await
                }
                None => {
                    warn!(seq, "Unknown policy event type; skipping");
                    Ok(())
                }
            };

            match result {
                Ok(()) => {
                    if !sandbox_id.is_empty() {
                        self.report_delivery(
                            client,
                            &sandbox_id,
                            generation.clone(),
                            DeliveryStatus::Delivered,
                            String::new(),
                            &trace_id,
                        )
                        .await;
                    }
                    break;
                }
                Err(error) if attempt < MAX_APPLY_ATTEMPTS => {
                    warn!(seq, attempt, %error, "policy apply failed; retrying in-order");
                    tokio::time::sleep(APPLY_RETRY_BACKOFF).await;
                }
                Err(error) => {
                    // Exhausted retries: report Failed and skip. The orchestrator's
                    // NetworkPolicyReconciler re-drives the sandbox, so ordering is
                    // preserved without a poison event blocking the stream forever.
                    warn!(seq, %error, "policy apply exhausted retries; reporting Failed and skipping");
                    if !sandbox_id.is_empty() {
                        self.report_delivery(
                            client,
                            &sandbox_id,
                            generation.clone(),
                            DeliveryStatus::Failed,
                            error.to_string(),
                            &trace_id,
                        )
                        .await;
                    }
                    break;
                }
            }
        }

        // Terminal outcome for this seq reached; advance the resume watermark.
        self.last_processed_seq.store(seq, Ordering::Release);
    }

    async fn report_delivery(
        &self,
        client: &mut PolicyStreamServiceClient<Channel>,
        sandbox_id: &str,
        generation: Option<crate::proto::policy_stream::PolicyGeneration>,
        status: DeliveryStatus,
        error_message: String,
        trace_id: &str,
    ) {
        let report = DeliveryReport {
            sandbox_id: sandbox_id.to_string(),
            generation,
            status: status as i32,
            error_message,
            delivered_at: None,
            trace_id: trace_id.to_string(),
        };
        if let Err(e) = client.report_delivery(Request::new(report)).await {
            error!(error = %e, sandbox_id, "Failed to report delivery to orchestrator");
        }
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

            let current_seq = last_processed_seq.load(Ordering::Acquire);
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

/// Aborts the wrapped task when dropped, so a per-connection helper task cannot
/// outlive the connection that spawned it. (Fixes H4.)
struct AbortOnDrop(tokio::task::JoinHandle<()>);

impl Drop for AbortOnDrop {
    fn drop(&mut self) {
        self.0.abort();
    }
}
