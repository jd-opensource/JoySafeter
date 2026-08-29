#![cfg(unix)]

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::Arc;
use std::time::{Duration, Instant};

use anyhow::{bail, Context};
use envoy_types::pb::envoy::service::discovery::v3::aggregated_discovery_service_server::AggregatedDiscoveryServiceServer;
use joysafeter_orchestrator::ids::{AgentId, SandboxId};
use joysafeter_orchestrator::kernel::mcp_runtime_plan::{
    resolve_mcp_runtime_plan, EffectiveNetworkMode,
};
use joysafeter_orchestrator::kernel::network_policy::envoy_model::{
    EgressCredentialRoute, EgressExposure, EgressKind, EgressPathMapping, EgressRetryMode,
    SandboxCredentials, MCP_EGRESS_HOST,
};
use joysafeter_orchestrator::sandbox::envoy::{EnvoyConfig, EnvoyManager};
use joysafeter_orchestrator::xds::publisher::{GrpcCds, GrpcLds};
use joysafeter_orchestrator::xds::transport::DeltaXdsServer;
use serde_json::Value;
use tempfile::TempDir;
use tokio::net::TcpListener;
use tokio::sync::oneshot;
use tokio_stream::wrappers::TcpListenerStream;
use tonic::transport::Server;
use uuid::Uuid;

const DEFAULT_ENVOY_IMAGE: &str = "docker.m.daocloud.io/envoyproxy/envoy:v1.37.1";
const DEFAULT_FIXTURE_IMAGE: &str = "joysafeter-backend:latest";

struct DockerResources {
    containers: Vec<String>,
    volumes: Vec<String>,
    network: String,
}

impl DockerResources {
    fn new(network: String) -> Self {
        Self {
            containers: Vec::new(),
            volumes: Vec::new(),
            network,
        }
    }

    fn track_container(&mut self, name: String) {
        self.containers.push(name);
    }

    fn track_volume(&mut self, name: String) {
        self.volumes.push(name);
    }
}

impl Drop for DockerResources {
    fn drop(&mut self) {
        for container in self.containers.iter().rev() {
            let _ = Command::new("docker")
                .args(["rm", "-f", container])
                .output();
        }
        for volume in self.volumes.iter().rev() {
            let _ = Command::new("docker")
                .args(["volume", "rm", "-f", volume])
                .output();
        }
        let _ = Command::new("docker")
            .args(["network", "rm", &self.network])
            .output();
    }
}

fn command_output(command: &mut Command) -> anyhow::Result<Output> {
    let output = command.output().context("failed to execute command")?;
    if !output.status.success() {
        bail!(
            "command failed: status={} stdout={} stderr={}",
            output.status,
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
    }
    Ok(output)
}

fn docker(args: &[&str]) -> anyhow::Result<String> {
    let output = command_output(Command::new("docker").args(args))?;
    Ok(String::from_utf8(output.stdout)?.trim().to_string())
}

fn docker_diagnostics(container: &str) -> String {
    let inspect = Command::new("docker")
        .args([
            "inspect",
            container,
            "--format",
            "status={{.State.Status}} exit={{.State.ExitCode}} error={{json .State.Error}} path={{json .Path}} args={{json .Args}}",
        ])
        .output();
    let logs = Command::new("docker").args(["logs", container]).output();
    format!(
        "inspect: {}{}\nlogs: {}{}",
        inspect
            .as_ref()
            .map(|output| String::from_utf8_lossy(&output.stdout))
            .unwrap_or_default(),
        inspect
            .as_ref()
            .map(|output| String::from_utf8_lossy(&output.stderr))
            .unwrap_or_default(),
        logs.as_ref()
            .map(|output| String::from_utf8_lossy(&output.stdout))
            .unwrap_or_default(),
        logs.as_ref()
            .map(|output| String::from_utf8_lossy(&output.stderr))
            .unwrap_or_default(),
    )
}

fn docker_visible_tempdir() -> anyhow::Result<TempDir> {
    let root = std::env::var_os("JOYSAFETER_LIVE_TEST_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|| Path::new(env!("CARGO_MANIFEST_DIR")).join("target/live-tests"));
    fs::create_dir_all(&root)?;
    Ok(tempfile::Builder::new()
        .prefix("mcp-envoy-")
        .tempdir_in(root)?)
}

fn write_fixture_files(temp: &TempDir) -> anyhow::Result<PathBuf> {
    let fixture_dir = temp.path().join("fixture");
    fs::create_dir_all(&fixture_dir)?;
    fs::set_permissions(&fixture_dir, fs::Permissions::from_mode(0o755))?;
    let source = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/mcp_live_fixture.py");
    fs::copy(source, fixture_dir.join("mcp_live_fixture.py"))?;
    command_output(Command::new("openssl").args([
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        fixture_dir.join("key.pem").to_str().unwrap(),
        "-out",
        fixture_dir.join("cert.pem").to_str().unwrap(),
        "-days",
        "1",
        "-subj",
        "/CN=mcp-tls.fixture",
        "-addext",
        "subjectAltName=DNS:mcp-tls.fixture",
    ]))?;
    Ok(fixture_dir)
}

fn wait_for_fixture(container: &str) -> anyhow::Result<()> {
    let deadline = Instant::now() + Duration::from_secs(15);
    while Instant::now() < deadline {
        let result = Command::new("docker")
            .args([
                "exec",
                container,
                "python",
                "-c",
                "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=1).read()",
            ])
            .output();
        if result.is_ok_and(|output| output.status.success()) {
            return Ok(());
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    bail!("MCP fixture did not become ready")
}

fn wait_for_socket(container: &str, path: &str) -> anyhow::Result<()> {
    let deadline = Instant::now() + Duration::from_secs(10);
    while Instant::now() < deadline {
        let result = Command::new("docker")
            .args(["exec", container, "test", "-S", path])
            .output();
        if result.is_ok_and(|output| output.status.success()) {
            return Ok(());
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    bail!("Envoy listener socket was not created: {path}")
}

fn curl_json(
    container: &str,
    socket: &str,
    url: &str,
    headers: &[(&str, &str)],
) -> anyhow::Result<Value> {
    let mut command = Command::new("docker");
    command.args(["exec", container, "curl", "-sS", "--fail", "--unix-socket"]);
    command.arg(socket);
    for (name, value) in headers {
        command.args(["-H", &format!("{name}: {value}")]);
    }
    command.arg(url);
    let output = command_output(&mut command)?;
    serde_json::from_slice(&output.stdout).context("fixture returned invalid JSON")
}

fn curl_status(container: &str, socket: &str, url: &str) -> anyhow::Result<u16> {
    let output = command_output(
        Command::new("docker")
            .args([
                "exec",
                container,
                "curl",
                "-sS",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code}",
                "--unix-socket",
            ])
            .arg(socket)
            .arg(url),
    )?;
    Ok(String::from_utf8(output.stdout)?.trim().parse()?)
}

fn curl_json_with_status(
    container: &str,
    socket: &str,
    method: &str,
    url: &str,
) -> anyhow::Result<(u16, Value)> {
    let output = command_output(Command::new("docker").args([
        "exec",
        container,
        "curl",
        "-sS",
        "-X",
        method,
        "-w",
        "\n%{http_code}",
        "--unix-socket",
        socket,
        url,
    ]))?;
    let text = String::from_utf8(output.stdout)?;
    let (body, status) = text
        .rsplit_once('\n')
        .context("curl response did not include an HTTP status")?;
    Ok((status.trim().parse()?, serde_json::from_str(body)?))
}

fn assert_sse_streams_without_buffering(container: &str, socket: &str) -> anyhow::Result<()> {
    let started = Instant::now();
    let partial = Command::new("docker")
        .args([
            "exec",
            container,
            "curl",
            "-sS",
            "--no-buffer",
            "--max-time",
            "0.7",
            "--unix-socket",
            socket,
            "http://mcp-egress.internal/r/sse/stream",
        ])
        .output()?;
    let partial_body = String::from_utf8_lossy(&partial.stdout);
    if !partial_body.contains("data: first") || partial_body.contains("data: second") {
        bail!(
            "SSE first event was buffered: status={} elapsed={:?} stdout={} stderr={}",
            partial.status,
            started.elapsed(),
            partial_body,
            String::from_utf8_lossy(&partial.stderr)
        )
    }
    if started.elapsed() >= Duration::from_millis(1_500) {
        bail!("first SSE event arrived only after the upstream delay")
    }

    let complete = command_output(Command::new("docker").args([
        "exec",
        container,
        "curl",
        "-sS",
        "--no-buffer",
        "--max-time",
        "3",
        "--unix-socket",
        socket,
        "http://mcp-egress.internal/r/sse/stream",
    ]))?;
    let complete_body = String::from_utf8_lossy(&complete.stdout);
    if !complete_body.contains("data: first") || !complete_body.contains("data: second") {
        bail!("SSE stream did not deliver both events: {complete_body}")
    }
    Ok(())
}

fn route(
    id: &str,
    route_key: &str,
    upstream_host: &str,
    upstream_port: u16,
    upstream_prefix: &str,
    upstream_tls: bool,
    fixture_ip: &str,
    inject_headers: Vec<(String, String)>,
) -> EgressCredentialRoute {
    EgressCredentialRoute {
        id: format!("mcp:{id}"),
        kind: EgressKind::Mcp,
        exposure: EgressExposure::Placeholder,
        match_host: MCP_EGRESS_HOST.to_string(),
        path_mapping: EgressPathMapping::RewritePrefix {
            exposed_prefix: format!("/r/{route_key}/"),
            upstream_prefix: upstream_prefix.to_string(),
        },
        retry_mode: EgressRetryMode::Disabled,
        upstream_host: upstream_host.to_string(),
        upstream_port,
        upstream_tls,
        cluster_name: String::new(),
        vetted_addresses: vec![fixture_ip.to_string()],
        inject_headers,
        remove_headers: vec![
            "authorization".to_string(),
            "x-api-key".to_string(),
            "x-custom-auth".to_string(),
        ],
    }
}

fn policy(fixture_ip: &str, bearer: &str) -> SandboxCredentials {
    SandboxCredentials {
        routes: vec![
            route(
                "http-default",
                "http-default",
                "mcp-http.fixture",
                80,
                "/root/",
                false,
                fixture_ip,
                vec![("authorization".to_string(), format!("Bearer {bearer}"))],
            ),
            route(
                "http-alt",
                "http-alt",
                "mcp-http.fixture",
                8765,
                "/base/",
                false,
                fixture_ip,
                vec![("x-api-key".to_string(), "api-secret".to_string())],
            ),
            route(
                "https-default",
                "https-default",
                "mcp-tls.fixture",
                443,
                "/secure/",
                true,
                fixture_ip,
                vec![(
                    "x-custom-auth".to_string(),
                    "Token custom-secret".to_string(),
                )],
            ),
            route(
                "https-alt",
                "https-alt",
                "mcp-tls.fixture",
                8443,
                "/nested/",
                true,
                fixture_ip,
                Vec::new(),
            ),
            route(
                "sse",
                "sse",
                "mcp-http.fixture",
                8765,
                "/events/",
                false,
                fixture_ip,
                Vec::new(),
            ),
        ],
        proxy_auth_token: None,
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires Docker, curl, openssl, Envoy v1.37.1, and a local fixture image"]
async fn live_envoy_enforces_mcp_routes_headers_streaming_rotation_and_recovery(
) -> anyhow::Result<()> {
    if std::env::var("JOYSAFETER_RUN_LIVE_ENVOY").as_deref() != Ok("1") {
        bail!("set JOYSAFETER_RUN_LIVE_ENVOY=1 to run this destructive live test")
    }

    let run_id = format!("{}-{}", std::process::id(), Uuid::now_v7().simple());
    let network = format!("joysafeter-mcp-live-{run_id}");
    let fixture_container = format!("joysafeter-mcp-fixture-{run_id}");
    let envoy_container = format!("joysafeter-mcp-envoy-{run_id}");
    let socket_volume = format!("joysafeter-mcp-live-sockets-{run_id}");
    docker(&["network", "create", &network])?;
    let mut resources = DockerResources::new(network.clone());
    docker(&["volume", "create", &socket_volume])?;
    resources.track_volume(socket_volume.clone());

    let temp = docker_visible_tempdir()?;
    let fixture_dir = write_fixture_files(&temp)?;
    let fixture_image = std::env::var("JOYSAFETER_LIVE_FIXTURE_IMAGE")
        .unwrap_or_else(|_| DEFAULT_FIXTURE_IMAGE.to_string());
    docker(&[
        "run",
        "-d",
        "--name",
        &fixture_container,
        "--network",
        &network,
        "-v",
        &format!("{}:/fixture:ro", fixture_dir.display()),
        "-v",
        &format!("{socket_volume}:/sockets"),
        &fixture_image,
        "python",
        "/fixture/mcp_live_fixture.py",
    ])?;
    resources.track_container(fixture_container.clone());
    if let Err(error) = wait_for_fixture(&fixture_container) {
        bail!(
            "{error:#}\nMCP fixture diagnostics:\n{}",
            docker_diagnostics(&fixture_container)
        )
    }
    let fixture_ip = docker(&[
        "inspect",
        "-f",
        "{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
        &fixture_container,
    ])?;

    let raw_mcp_servers = serde_json::json!([
        {
            "type": "streamable_http",
            "name": "exact-path",
            "url": "http://mcp-http.fixture:8765/mcp?tenant=a&tenant=b",
            "auth_requirement": "none"
        },
        {
            "type": "streamable_http",
            "name": "no-retry",
            "url": "http://mcp-http.fixture:8765/retry-probe",
            "auth_requirement": "none"
        }
    ]);
    let mut runtime_plan = resolve_mcp_runtime_plan(
        AgentId::from_uuid(Uuid::now_v7()),
        1,
        EffectiveNetworkMode::Limited,
        Some(&raw_mcp_servers),
        &[],
    )?;
    for server in &mut runtime_plan.servers {
        server
            .original_endpoint
            .as_mut()
            .expect("remote MCP server")
            .vetted_addresses = vec![fixture_ip.parse()?];
    }
    let runner_servers = runtime_plan.runner_servers();
    let exact_url = runner_servers[0].url.clone();
    let retry_url = runner_servers[1].url.clone();
    let exact_route_key = runtime_plan.servers[0].route_key.clone();

    let xds = DeltaXdsServer::with_static_token("test-xds-token")?;
    let listener = TcpListener::bind("0.0.0.0:0").await?;
    let xds_port = listener.local_addr()?.port();
    let (shutdown_tx, shutdown_rx) = oneshot::channel::<()>();
    let xds_service = xds.clone();
    let xds_task = tokio::spawn(async move {
        Server::builder()
            .add_service(AggregatedDiscoveryServiceServer::from_arc(xds_service))
            .serve_with_incoming_shutdown(TcpListenerStream::new(listener), async {
                let _ = shutdown_rx.await;
            })
            .await
    });

    let config_dir = temp.path().join("config");
    fs::create_dir_all(&config_dir)?;
    fs::set_permissions(&config_dir, fs::Permissions::from_mode(0o755))?;
    let lds = Arc::new(GrpcLds::new(xds.clone()));
    let cds = Arc::new(GrpcCds::new(xds));
    let manager = EnvoyManager::new(
        None,
        EnvoyConfig {
            envoy_image: DEFAULT_ENVOY_IMAGE.to_string(),
            socket_volume: socket_volume.clone(),
            socket_host_dir: None,
            config_dir: config_dir.display().to_string(),
            envoy_network: network.clone(),
            grpc_target_host: "host.docker.internal".to_string(),
            grpc_target_port: xds_port,
            xds_auth_token: "test-xds-token".to_string(),
            container_name: envoy_container.clone(),
            xds_mode: "grpc".to_string(),
            write_debug_entries: false,
            socket_ready_timeout_ms: 15_000,
            health_check_interval_sec: 0,
            health_failure_threshold: 1,
            skip_socket_dir_prep: true,
            node_id: "joysafeter-mcp-live-envoy".to_string(),
        },
        lds,
        cds,
    );
    manager.init().await?;

    let envoy_image = std::env::var("JOYSAFETER_LIVE_ENVOY_IMAGE")
        .unwrap_or_else(|_| DEFAULT_ENVOY_IMAGE.to_string());
    docker(&[
        "run",
        "-d",
        "--name",
        &envoy_container,
        "--network",
        &network,
        "--add-host",
        "host.docker.internal:host-gateway",
        "-v",
        &format!("{}:/envoy-config:ro", config_dir.display()),
        "-v",
        &format!("{socket_volume}:/sockets"),
        "-v",
        &format!(
            "{}:/etc/ssl/certs/ca-certificates.crt:ro",
            fixture_dir.join("cert.pem").display()
        ),
        "--entrypoint",
        "/bin/sh",
        &envoy_image,
        "-c",
        "exec envoy -c /envoy-config/bootstrap.json --log-level info",
    ])?;
    resources.track_container(envoy_container.clone());

    let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
    let socket_parent = format!("/sockets/{}", sandbox_id.as_uuid());
    docker(&["exec", &fixture_container, "mkdir", "-p", &socket_parent])?;
    docker(&["exec", &fixture_container, "chmod", "755", &socket_parent])?;
    let mut initial_policy = policy(&fixture_ip, "bearer-one");
    initial_policy.routes.extend(runtime_plan.egress_routes());
    if let Err(error) = manager
        .add_sandbox_policy(sandbox_id, initial_policy.to_policy(&sandbox_id, vec![]))
        .await
    {
        bail!(
            "{error:#}\nEnvoy diagnostics:\n{}",
            docker_diagnostics(&envoy_container)
        )
    }
    let socket = format!("/sockets/{}/http.sock", sandbox_id.as_uuid());
    wait_for_socket(&fixture_container, &socket)?;

    let (exact_status, exact_body) =
        curl_json_with_status(&fixture_container, &socket, "POST", &exact_url)?;
    assert_eq!(exact_status, 200);
    assert_eq!(exact_body["method"], "POST");
    assert_eq!(exact_body["path"], "/mcp?tenant=a&tenant=b");

    let descendant_status = curl_status(
        &fixture_container,
        &socket,
        &format!("http://{MCP_EGRESS_HOST}/r/{exact_route_key}/child"),
    )?;
    assert_ne!(descendant_status, 200);

    let (retry_status, retry_body) =
        curl_json_with_status(&fixture_container, &socket, "POST", &retry_url)?;
    assert_eq!(retry_status, 503);
    assert_eq!(retry_body["request_count"], 1);

    let http_default = curl_json(
        &fixture_container,
        &socket,
        "http://mcp-egress.internal/r/http-default/?root=1",
        &[
            ("authorization", "Bearer attacker"),
            ("x-api-key", "attacker"),
        ],
    )?;
    assert_eq!(http_default["path"], "/root/?root=1");
    assert_eq!(http_default["host"], "mcp-http.fixture");
    assert_eq!(http_default["authorization"], "Bearer bearer-one");
    assert!(http_default["x_api_key"].is_null());
    assert_eq!(http_default["server_port"], 80);

    let http_alt = curl_json(
        &fixture_container,
        &socket,
        "http://mcp-egress.internal/r/http-alt/nested/?q=1",
        &[("x-api-key", "attacker")],
    )?;
    assert_eq!(http_alt["path"], "/base/nested/?q=1");
    assert_eq!(http_alt["host"], "mcp-http.fixture:8765");
    assert_eq!(http_alt["x_api_key"], "api-secret");
    assert_eq!(http_alt["server_port"], 8765);

    let https_default = curl_json(
        &fixture_container,
        &socket,
        "http://mcp-egress.internal/r/https-default/child",
        &[("x-custom-auth", "attacker")],
    )?;
    assert_eq!(https_default["path"], "/secure/child");
    assert_eq!(https_default["host"], "mcp-tls.fixture");
    assert_eq!(https_default["x_custom_auth"], "Token custom-secret");
    assert_eq!(https_default["server_port"], 443);

    let https_alt = curl_json(
        &fixture_container,
        &socket,
        "http://mcp-egress.internal/r/https-alt/trailing/",
        &[("authorization", "Bearer attacker")],
    )?;
    assert_eq!(https_alt["path"], "/nested/trailing/");
    assert_eq!(https_alt["host"], "mcp-tls.fixture:8443");
    assert!(https_alt["authorization"].is_null());
    assert_eq!(https_alt["server_port"], 8443);

    assert_sse_streams_without_buffering(&fixture_container, &socket)?;
    let direct_status = curl_status(&fixture_container, &socket, "http://mcp-http.fixture/root/")?;
    assert_ne!(
        direct_status, 200,
        "direct upstream host must not bypass the MCP route"
    );

    if let Err(error) = manager
        .add_sandbox_policy(
            sandbox_id,
            policy(&fixture_ip, "bearer-rotated").to_policy(&sandbox_id, vec![]),
        )
        .await
    {
        bail!(
            "credential rotation failed: {error:#}\nEnvoy diagnostics:\n{}",
            docker_diagnostics(&envoy_container)
        )
    }
    let rotated = curl_json(
        &fixture_container,
        &socket,
        "http://mcp-egress.internal/r/http-default/rotation",
        &[],
    )?;
    assert_eq!(rotated["authorization"], "Bearer bearer-rotated");

    docker(&["restart", &envoy_container])?;
    if let Err(error) = manager
        .add_sandbox_policy(
            sandbox_id,
            policy(&fixture_ip, "after-restart").to_policy(&sandbox_id, vec![]),
        )
        .await
    {
        bail!(
            "Envoy restart recovery failed: {error:#}\nEnvoy diagnostics:\n{}",
            docker_diagnostics(&envoy_container)
        )
    }
    wait_for_socket(&fixture_container, &socket)?;
    let recovered = curl_json(
        &fixture_container,
        &socket,
        "http://mcp-egress.internal/r/http-default/recovered",
        &[],
    )?;
    assert_eq!(recovered["authorization"], "Bearer after-restart");

    docker(&["stop", &envoy_container])?;
    let _ = shutdown_tx.send(());
    xds_task.await??;
    drop(resources);
    Ok(())
}
