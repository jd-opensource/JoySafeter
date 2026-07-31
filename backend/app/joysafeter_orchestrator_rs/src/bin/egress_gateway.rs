use joysafeter_orchestrator::egress::gateway::{app, GatewayConfig};
use tracing::info;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let _ = dotenvy::dotenv();

    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .with_target(true)
        .init();

    let config = GatewayConfig::from_env();
    let bind_addr = config.bind_addr()?;
    let listener = tokio::net::TcpListener::bind(bind_addr).await?;

    info!(
        addr = %bind_addr,
        require_sandbox_token = config.require_sandbox_token,
        control_api_configured = config.control_token_sha256.is_some(),
        "Starting JoySafeter egress gateway"
    );

    axum::serve(listener, app(config)).await?;
    Ok(())
}
