use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use tokio::net::{TcpListener, UnixListener};
use tokio::task::JoinHandle;
use tokio_stream::wrappers::{TcpListenerStream, UnixListenerStream};
use tracing::{error, info, warn};

use sqlx::PgPool;

use crate::grpc::policy_stream::PolicyStreamServer;
use crate::grpc::policy_stream::RedisEventPublisher;
use crate::grpc::proto::agent_bridge_server::AgentBridgeServer;
use crate::grpc::transport::RunnerTransport;
use crate::proto::policy_stream::policy_stream_service_server::PolicyStreamServiceServer;

const GRPC_MAX_RECV_MESSAGE_SIZE: usize = 128 * 1024 * 1024;
const GRPC_MAX_SEND_MESSAGE_SIZE: usize = 32 * 1024 * 1024;

pub(crate) async fn start_grpc_server(
    addr: SocketAddr,
    control_socket_host_dir: String,
    transport: Arc<RunnerTransport>,
    db: Option<PgPool>,
    event_publisher: Option<Arc<RedisEventPublisher>>,
) -> anyhow::Result<JoinHandle<()>> {
    let control_socket_path = prepare_runner_control_socket(&control_socket_host_dir).await?;
    let tcp_listener = TcpListener::bind(addr).await?;
    let control_listener = UnixListener::bind(&control_socket_path)?;

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if let Err(error) =
            tokio::fs::set_permissions(&control_socket_path, std::fs::Permissions::from_mode(0o666))
                .await
        {
            warn!(path = %control_socket_path.display(), %error, "failed to chmod runner control UDS");
        }
    }

    let tcp_service = AgentBridgeServer::from_arc(transport.clone())
        .max_decoding_message_size(GRPC_MAX_RECV_MESSAGE_SIZE)
        .max_encoding_message_size(GRPC_MAX_SEND_MESSAGE_SIZE);
    let control_service = AgentBridgeServer::from_arc(transport)
        .max_decoding_message_size(GRPC_MAX_RECV_MESSAGE_SIZE)
        .max_encoding_message_size(GRPC_MAX_SEND_MESSAGE_SIZE);

    let handle = tokio::spawn(async move {
        info!(addr = %addr, control_socket = %control_socket_path.display(), "runner gRPC server listening (TCP and UDS: joysafeter.AgentBridge)");

        let mut tcp_server_builder = tonic::transport::Server::builder()
            .tcp_keepalive(Some(Duration::from_secs(30)))
            .http2_keepalive_interval(Some(Duration::from_secs(30)))
            .http2_keepalive_timeout(Some(Duration::from_secs(10)))
            .add_service(tcp_service);

        // Add PolicyStreamService if db and event_publisher are provided
        if let (Some(db), Some(publisher)) = (db, event_publisher) {
            let policy_stream_service = PolicyStreamServer::new(db, publisher);
            tcp_server_builder = tcp_server_builder
                .add_service(PolicyStreamServiceServer::new(policy_stream_service));
            info!("PolicyStreamService enabled on TCP gRPC server");
        }

        let tcp_server =
            tcp_server_builder.serve_with_incoming(TcpListenerStream::new(tcp_listener));
        let control_server = tonic::transport::Server::builder()
            .add_service(control_service)
            .serve_with_incoming(UnixListenerStream::new(control_listener));

        tokio::select! {
            result = tcp_server => {
                if let Err(error) = result {
                    error!("TCP gRPC server error: {error}");
                }
            }
            result = control_server => {
                if let Err(error) = result {
                    error!("runner control UDS gRPC server error: {error}");
                }
            }
        }
    });

    Ok(handle)
}

async fn prepare_runner_control_socket(control_socket_host_dir: &str) -> anyhow::Result<PathBuf> {
    let directory = PathBuf::from(control_socket_host_dir);
    tokio::fs::create_dir_all(&directory).await?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        tokio::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o755)).await?;
    }
    let socket_path = directory.join("grpc.sock");
    match tokio::fs::remove_file(&socket_path).await {
        Ok(_) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => return Err(error.into()),
    }
    Ok(socket_path)
}
