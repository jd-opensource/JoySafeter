import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app.joysafeter_shared.common.boundary_errors import log_boundary_failure

logger = logging.getLogger(__name__)


@dataclass
class EnvoyConfig:
    envoy_image: str = "envoyproxy/envoy:v1.31-latest"
    socket_volume: str = "joysafeter-sockets"
    config_dir: str = "/tmp/joysafeter/envoy-config"
    envoy_network: str = "joysafeter-net"
    grpc_target_host: str = "host.docker.internal"
    grpc_target_port: int = 9090
    container_name: str = "joysafeter-envoy"


@dataclass
class SandboxEntry:
    sandbox_id: uuid.UUID
    networking: dict = field(default_factory=dict)


class EnvoyManager:
    """Per-sandbox network isolation using Envoy proxy.

    Manages an Envoy sidecar container that provides:
    - Per-sandbox Unix domain sockets for gRPC (orchestrator) and HTTP (outbound)
    - Domain-based allowlisting for outbound HTTP traffic
    - Dynamic LDS config regeneration when sandboxes are added/removed

    Ported from the sandbox network isolation implementation.
    """

    def __init__(self, config: EnvoyConfig):
        self._config = config
        self._config_dir = Path(config.config_dir)
        self._sandboxes_dir = self._config_dir / "sandboxes"
        self._config_lock = asyncio.Lock()

    @property
    def socket_volume(self) -> str:
        return self._config.socket_volume

    async def init(self) -> None:
        os.makedirs(self._config_dir, exist_ok=True)
        os.makedirs(self._sandboxes_dir, exist_ok=True)

        # Clean stale sandbox entries from previous run
        stale_count = 0
        if self._sandboxes_dir.exists():
            for f in self._sandboxes_dir.iterdir():
                if f.suffix == ".json":
                    f.unlink(missing_ok=True)
                    stale_count += 1
        if stale_count:
            logger.info("Cleaned %d stale sandbox entries from previous run", stale_count)

        # Clean inside envoy container
        await self._exec_in_envoy(
            "rm -rf /envoy-config/sandboxes && mkdir -p /envoy-config/sandboxes && chmod 777 /envoy-config/sandboxes"
        )

        await self._write_bootstrap_config()
        await self._regenerate_lds()
        logger.info("Envoy config initialized (config_dir=%s)", self._config_dir)

    async def add_sandbox(
        self,
        sandbox_id: uuid.UUID,
        networking: dict,
    ) -> None:
        # Create socket directory inside envoy container
        await self._exec_in_envoy(f"mkdir -p /sockets/{sandbox_id} && chmod 777 /sockets/{sandbox_id}")

        # Persist sandbox entry
        entry_path = self._sandboxes_dir / f"{sandbox_id}.json"
        entry_path.write_text(
            json.dumps(
                {
                    "sandbox_id": str(sandbox_id),
                    "networking": networking,
                },
                indent=2,
            )
        )

        await self._regenerate_lds()

        # Wait for sockets to appear (up to 10s)
        deadline = asyncio.get_event_loop().time() + 10
        while asyncio.get_event_loop().time() < deadline:
            result = await self._exec_in_envoy(
                f"test -S /sockets/{sandbox_id}/grpc.sock && test -S /sockets/{sandbox_id}/http.sock"
            )
            if result == 0:
                break
            await asyncio.sleep(0.2)
        else:
            log_boundary_failure(
                logger,
                boundary="envoy_manager",
                code="ENVOY_SOCKET_WAIT_TIMEOUT",
                message="Timed out waiting for Envoy sockets",
                operation="wait_for_sandbox_sockets",
                data={"sandbox_id": str(sandbox_id), "container_name": self._config.container_name},
                retryable=True,
                user_action="retry",
            )

        logger.info("Sandbox %s registered with Envoy proxy", sandbox_id)

    async def remove_sandbox(self, sandbox_id: uuid.UUID) -> None:
        entry_path = self._sandboxes_dir / f"{sandbox_id}.json"
        entry_path.unlink(missing_ok=True)

        await self._regenerate_lds()
        await self._exec_in_envoy(f"rm -rf /sockets/{sandbox_id}")
        logger.info("Sandbox %s removed from Envoy proxy", sandbox_id)

    async def setup_for_sandbox(
        self,
        sandbox_id: uuid.UUID,
        networking: dict,
    ) -> None:
        """Alias used by DockerSandboxProvider.setup_networking."""
        await self.add_sandbox(sandbox_id, networking)

    async def teardown_for_sandbox(self, sandbox_id: uuid.UUID) -> None:
        """Alias used by DockerSandboxProvider.teardown_networking."""
        await self.remove_sandbox(sandbox_id)

    async def _regenerate_lds(self) -> None:
        sandboxes = self._load_sandboxes_from_disk()
        await self._write_lds_config(sandboxes)

    def _load_sandboxes_from_disk(self) -> dict[uuid.UUID, dict]:
        result: dict[uuid.UUID, dict] = {}
        if not self._sandboxes_dir.exists():
            return result
        for f in self._sandboxes_dir.iterdir():
            if f.suffix != ".json":
                continue
            try:
                data = json.loads(f.read_text())
                sid = uuid.UUID(data["sandbox_id"])
                result[sid] = data.get("networking", {})
            except Exception as e:
                log_boundary_failure(
                    logger,
                    boundary="envoy_manager",
                    code="ENVOY_SANDBOX_ENTRY_PARSE_FAILED",
                    message="Failed to parse Envoy sandbox entry",
                    operation="load_sandbox_entry",
                    error=e,
                    data={"entry_path": str(f)},
                    retryable=False,
                    user_action="check_configuration",
                )
        return result

    async def _write_bootstrap_config(self) -> None:
        host = self._config.grpc_target_host
        port = self._config.grpc_target_port

        config = f"""node:
  cluster: joysafeter-proxy
  id: joysafeter-envoy

dynamic_resources:
  lds_config:
    path_config_source:
      path: /envoy-config/lds.yaml
      watched_directory:
        path: /envoy-config

static_resources:
  clusters:
    - name: orchestrator_grpc
      connect_timeout: 5s
      type: STRICT_DNS
      lb_policy: ROUND_ROBIN
      typed_extension_protocol_options:
        envoy.extensions.upstreams.http.v3.HttpProtocolOptions:
          "@type": type.googleapis.com/envoy.extensions.upstreams.http.v3.HttpProtocolOptions
          explicit_http_config:
            http2_protocol_options: {{}}
      load_assignment:
        cluster_name: orchestrator_grpc
        endpoints:
          - lb_endpoints:
              - endpoint:
                  address:
                    socket_address:
                      address: {host}
                      port_value: {port}
    - name: dynamic_forward_proxy
      connect_timeout: 5s
      lb_policy: CLUSTER_PROVIDED
      cluster_type:
        name: envoy.clusters.dynamic_forward_proxy
        typed_config:
          "@type": type.googleapis.com/envoy.extensions.clusters.dynamic_forward_proxy.v3.ClusterConfig
          dns_cache_config:
            name: dynamic_forward_proxy_cache
            dns_lookup_family: V4_ONLY

admin:
  address:
    socket_address:
      address: 127.0.0.1
      port_value: 9901
"""

        # Write to host config dir
        bootstrap_path = self._config_dir / "bootstrap.yaml"
        bootstrap_path.write_text(config)

        # Also write via exec into Envoy container
        await self._write_file_in_envoy("/envoy-config/bootstrap.yaml", config)

    async def _write_lds_config(self, sandboxes: dict[uuid.UUID, dict]) -> None:
        async with self._config_lock:
            resources = ""
            version = len(sandboxes)

            for sandbox_id, networking in sandboxes.items():
                sid = str(sandbox_id)
                allowed_hosts = networking.get("allowed_hosts", [])

                # gRPC listener (TCP proxy to orchestrator)
                resources += f"""  - "@type": type.googleapis.com/envoy.config.listener.v3.Listener
    name: {sid}_grpc
    address:
      pipe:
        path: /sockets/{sid}/grpc.sock
        mode: 438
    filter_chains:
      - filters:
          - name: envoy.filters.network.tcp_proxy
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.filters.network.tcp_proxy.v3.TcpProxy
              stat_prefix: {sid}_grpc
              cluster: orchestrator_grpc
"""

                # HTTP listener with domain filtering
                virtual_hosts = ""
                if allowed_hosts:
                    expanded = []
                    for d in allowed_hosts:
                        expanded.append(f'"{d}"')
                        if ":" not in d:
                            expanded.append(f'"{d}:443"')
                            expanded.append(f'"{d}:80"')
                    domains_yaml = ", ".join(expanded)

                    virtual_hosts += f"""                - name: allowed
                  domains: [{domains_yaml}]
                  routes:
                    - match:
                        connect_matcher: {{}}
                      route:
                        cluster: dynamic_forward_proxy
                        upgrade_configs:
                          - upgrade_type: CONNECT
                            connect_config: {{}}
                    - match:
                        prefix: "/"
                      route:
                        cluster: dynamic_forward_proxy
"""

                virtual_hosts += """                - name: deny_all
                  domains: ["*"]
                  routes:
                    - match:
                        prefix: "/"
                      direct_response:
                        status: 403
                        body:
                          inline_string: "Host not in allowlist"
"""

                resources += f"""  - "@type": type.googleapis.com/envoy.config.listener.v3.Listener
    name: {sid}_http
    address:
      pipe:
        path: /sockets/{sid}/http.sock
        mode: 438
    filter_chains:
      - filters:
          - name: envoy.filters.network.http_connection_manager
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager
              stat_prefix: {sid}_http
              http_protocol_options:
                allow_absolute_url: true
              upgrade_configs:
                - upgrade_type: CONNECT
              route_config:
                virtual_hosts:
{virtual_hosts}              http_filters:
                - name: envoy.filters.http.dynamic_forward_proxy
                  typed_config:
                    "@type": type.googleapis.com/envoy.extensions.filters.http.dynamic_forward_proxy.v3.FilterConfig
                    dns_cache_config:
                      name: dynamic_forward_proxy_cache
                      dns_lookup_family: V4_ONLY
                - name: envoy.filters.http.router
                  typed_config:
                    "@type": type.googleapis.com/envoy.extensions.filters.http.router.v3.Router
"""

            if not resources:
                lds = 'version_info: "0"\nresources: []\n'
            else:
                lds = f'version_info: "{version}"\nresources:\n{resources}'

            # Write via exec into envoy container
            await self._write_file_in_envoy("/envoy-config/lds.yaml", lds)

            # Also write to host config dir as fallback
            tmp_path = self._config_dir / "lds.yaml.tmp"
            final_path = self._config_dir / "lds.yaml"
            tmp_path.write_text(lds)
            tmp_path.rename(final_path)

    async def _exec_in_envoy(self, cmd: str) -> int:
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "exec",
                self._config.container_name,
                "sh",
                "-c",
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return proc.returncode or 0
        except Exception as e:
            log_boundary_failure(
                logger,
                boundary="envoy_manager",
                code="ENVOY_EXEC_FAILED",
                message="Exec in Envoy container failed",
                operation="exec_in_envoy",
                error=e,
                data={"container_name": self._config.container_name},
            )
            return 1

    async def _write_file_in_envoy(self, path: str, content: str) -> None:
        tmp_path = f"{path}.tmp"
        cmd = f"cat > {tmp_path} && mv {tmp_path} {path}"
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "exec",
                "-i",
                self._config.container_name,
                "sh",
                "-c",
                cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate(input=content.encode())
            if proc.returncode != 0:
                msg = stderr.decode(errors="replace").strip() if stderr else "unknown error"
                raise RuntimeError(f"Failed to write {path} in envoy container: {msg}")
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Failed to write {path} in envoy container: {e}") from e
