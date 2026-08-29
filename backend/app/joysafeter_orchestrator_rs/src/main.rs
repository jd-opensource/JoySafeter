//! JoySafeter Orchestrator process entry point.

use joysafeter_orchestrator::bootstrap::OrchestratorApplication;
use joysafeter_orchestrator::config::JoySafeterConfig;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let _ = dotenvy::dotenv();
    let _ = rustls::crypto::aws_lc_rs::default_provider().install_default();
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .with_target(true)
        .init();

    OrchestratorApplication::build(JoySafeterConfig::from_env())
        .await?
        .run()
        .await
}
