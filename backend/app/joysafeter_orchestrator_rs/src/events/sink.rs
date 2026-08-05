use async_trait::async_trait;

use super::envelope::EventEnvelope;

/// A pluggable event persistence/forwarding sink.
///
/// The EventBus dispatches non-status, non-already-persisted events to all
/// registered sinks. To add a new sink (Kafka, S3 audit, webhook), implement
/// this trait and register it at startup.
#[async_trait]
pub trait EventSink: Send + Sync {
    /// Sink name for diagnostics/logging.
    fn name(&self) -> &str;
    /// Persist/forward a single event.
    async fn publish(&self, envelope: &EventEnvelope);
    /// Force-flush any internal buffer.
    async fn flush(&self);
}
