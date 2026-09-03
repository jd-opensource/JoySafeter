from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "deploy/helm/joysafeter-orchestrator"


def read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text()


def test_helm_declares_independent_gateway_xds_and_secret_contract() -> None:
    values = read("deploy/helm/joysafeter-orchestrator/values.yaml")
    configmap = read(
        "deploy/helm/joysafeter-orchestrator/templates/orchestrator/configmap.yaml"
    )
    secret = read(
        "deploy/helm/joysafeter-orchestrator/templates/platform/secret.yaml"
    )
    deployment = read(
        "deploy/helm/joysafeter-orchestrator/templates/agent-gateway/deployment.yaml"
    )

    assert "xdsPort: 9092" in values
    assert "JOYSAFETER_AGENT_GATEWAY_URL" in configmap
    assert "JOYSAFETER_AGENT_GATEWAY_XDS_PORT" in configmap
    assert "JOYSAFETER_ENVOY_GRPC_PORT" not in configmap
    assert "JOYSAFETER_XDS_AUTH_KEYRING" in secret
    assert "JOYSAFETER_XDS_AUTH_WRITE_KEY_ID" in secret
    assert "JOYSAFETER_XDS_AUTH_TOKEN" in secret
    assert "name: xds" in deployment
    assert "containerPort: {{ .Values.agentGateway.xdsPort }}" in deployment


def test_helm_excludes_api_only_and_unconsumed_runtime_settings() -> None:
    values = read("deploy/helm/joysafeter-orchestrator/values.yaml")
    configmap = read(
        "deploy/helm/joysafeter-orchestrator/templates/orchestrator/configmap.yaml"
    )
    secret = read(
        "deploy/helm/joysafeter-orchestrator/templates/platform/secret.yaml"
    )
    remote_compose = read("deploy/docker-compose.remote.yml")

    assert "\n  SECRET_KEY:" not in secret
    assert "\n  JWT_SECRET_KEY:" not in remote_compose
    assert "JOYSAFETER_VAULT_ENCRYPTION_KEY: ${JOYSAFETER_VAULT_ENCRYPTION_KEY:-}" in remote_compose
    assert "JOYSAFETER_CREDENTIAL_ENCRYPTION_KEYRING:" in remote_compose
    assert "JOYSAFETER_CREDENTIAL_ENCRYPTION_WRITE_KEY_ID:" in remote_compose
    assert "POSTGRES_SSL:" not in secret
    assert "cookieName:" not in values
    assert "contextTtlSeconds:" not in values
    assert "AGENT_IDENTITY_COOKIE_NAME" not in configmap
    assert "AGENT_IDENTITY_CONTEXT_TTL_SECONDS" not in configmap
    assert "DISABLE_TELEMETRY" not in configmap


def test_xds_service_targets_only_the_dedicated_port() -> None:
    service = read(
        "deploy/helm/joysafeter-orchestrator/templates/agent-gateway/service.yaml"
    )

    assert "port: {{ .Values.agentGateway.xdsPort }}" in service
    assert "targetPort: xds" in service
    assert "targetPort: grpc" not in service


def test_envoy_bootstrap_sends_only_the_selected_xds_token() -> None:
    daemonset = read(
        "deploy/helm/joysafeter-orchestrator/templates/envoy/daemonset.yaml"
    )

    assert '"key": "x-joysafeter-xds-token"' in daemonset
    assert '"value": "${JOYSAFETER_XDS_AUTH_TOKEN}"' in daemonset
    assert "secretKeyRef:" in daemonset
    assert "key: JOYSAFETER_XDS_AUTH_TOKEN" in daemonset
    assert '"port_value": {{ .Values.agentGateway.xdsPort }}' in daemonset


def test_network_policy_separates_sandbox_runner_and_envoy_xds_traffic() -> None:
    sandbox_policy = read(
        "deploy/helm/joysafeter-orchestrator/templates/sandbox/networkpolicy.yaml"
    )
    envoy_policy = read(
        "deploy/helm/joysafeter-orchestrator/templates/envoy/networkpolicy.yaml"
    )
    orchestrator_policy = read(
        "deploy/helm/joysafeter-orchestrator/templates/orchestrator/networkpolicy.yaml"
    )

    assert ".Values.orchestrator.grpc.port" in sandbox_policy
    assert ".Values.agentGateway.xdsPort" not in sandbox_policy
    assert ".Values.agentGateway.xdsPort" in envoy_policy
    assert "name: joysafeter-orchestrator-ingress" in orchestrator_policy
    assert ".Values.orchestrator.grpc.port" in orchestrator_policy
    assert ".Values.agentGateway.xdsPort" not in orchestrator_policy


def test_compose_uses_internal_dedicated_authenticated_xds_port() -> None:
    compose = read("deploy/docker-compose.yml")

    assert "JOYSAFETER_XDS_PORT: 9092" in compose
    assert "JOYSAFETER_XDS_AUTH_KEYRING:" in compose
    assert "JOYSAFETER_XDS_AUTH_WRITE_KEY_ID:" in compose
    assert "JOYSAFETER_XDS_AUTH_TOKEN:" in compose
    assert "${JOYSAFETER_XDS_PORT_HOST:-9092}:9092" in compose


def test_compose_and_kubernetes_use_explicit_socket_storage_modes() -> None:
    compose = read("deploy/docker-compose.yml")
    configmap = read(
        "deploy/helm/joysafeter-orchestrator/templates/orchestrator/configmap.yaml"
    )
    daemonset = read(
        "deploy/helm/joysafeter-orchestrator/templates/envoy/daemonset.yaml"
    )
    k8s_provider = read("backend/app/joysafeter_orchestrator_rs/src/sandbox/k8s.rs")

    volume_name = (
        "${JOYSAFETER_ENVOY_SOCKET_VOLUME:-"
        "${COMPOSE_PROJECT_NAME:-deploy}_joysafeter-sockets}"
    )
    assert 'JOYSAFETER_ENVOY_SOCKET_HOST_DIR: ""' in compose
    assert f"JOYSAFETER_ENVOY_SOCKET_VOLUME: {volume_name}" in compose
    assert f"name: {volume_name}" in compose
    assert (
        "${JOYSAFETER_ENVOY_SOCKET_HOST_DIR:-/tmp/joysafeter-sockets}:"
        "${JOYSAFETER_ENVOY_SOCKET_HOST_DIR:-/tmp/joysafeter-sockets}"
    ) not in compose

    assert "JOYSAFETER_ENVOY_SOCKET_HOST_DIR: {{ .Values.envoy.socketHostDir | quote }}" in configmap
    assert "path: {{ .Values.envoy.socketHostDir }}" in daemonset
    assert '"type": "DirectoryOrCreate"' in k8s_provider
    assert '"subPath": sandbox_uuid.to_string()' in k8s_provider
    assert '"name": "create-socket-dir"' in k8s_provider


def test_kubernetes_envoy_owns_socket_root_for_lifecycle_cleanup() -> None:
    values = read("deploy/helm/joysafeter-orchestrator/values.yaml")
    daemonset = read(
        "deploy/helm/joysafeter-orchestrator/templates/envoy/daemonset.yaml"
    )

    assert "runAsUser: 101" in values
    assert "runAsGroup: 101" in values
    assert "name: prepare-socket-root" in daemonset
    assert "chown 0:0 /sockets" in daemonset
    assert "chown {{ .Values.envoy.runAsUser }}:{{ .Values.envoy.runAsGroup }} /sockets" in daemonset
    assert 'add: ["CHOWN"]' in daemonset
    root_chown = daemonset.index("chown 0:0 /sockets")
    chmod = daemonset.index("chmod 0750 /sockets")
    envoy_chown = daemonset.index(
        "chown {{ .Values.envoy.runAsUser }}:{{ .Values.envoy.runAsGroup }} /sockets"
    )
    assert root_chown < chmod < envoy_chown
    assert "runAsUser: {{ .Values.envoy.runAsUser }}" in daemonset
    assert "runAsGroup: {{ .Values.envoy.runAsGroup }}" in daemonset


def test_obsolete_envoy_grpc_port_bridge_is_removed() -> None:
    audited_files = [
        "backend/env.example",
        "backend/app/joysafeter_shared/config/settings.py",
        "backend/app/joysafeter_orchestrator_rs/src/config.rs",
        "deploy/helm/joysafeter-orchestrator/templates/orchestrator/configmap.yaml",
        "deploy/docker-compose.yml",
        "deploy/k8s/env-reference.md",
    ]

    for relative_path in audited_files:
        assert "JOYSAFETER_ENVOY_GRPC_PORT" not in read(relative_path), relative_path
        assert "envoy_grpc_port" not in read(relative_path), relative_path


def test_xds_health_metrics_and_alerts_are_deployed_as_one_contract() -> None:
    application = read(
        "backend/app/joysafeter_orchestrator_rs/src/bootstrap/application.rs"
    )
    supervisor = read(
        "backend/app/joysafeter_orchestrator_rs/src/bootstrap/supervisor.rs"
    )
    values = read("deploy/helm/joysafeter-orchestrator/values.yaml")
    rule = read(
        "deploy/helm/joysafeter-orchestrator/templates/agent-gateway/prometheusrule.yaml"
    )

    assert "spawn_health_server(" in application
    assert '"/healthz/xds"' in supervisor
    assert '"/metrics"' in supervisor
    assert "monitoring:\n  xdsAlerts:" in values
    assert "enabled: false" in values
    assert "applyTimeoutSeconds:" in values
    assert "recoveryBudgetSeconds:" in values
    assert "apiVersion: monitoring.coreos.com/v1" in rule
    assert "kind: PrometheusRule" in rule
    assert ".Values.monitoring.xdsAlerts.enabled" in rule

    for alert_name in [
        "JoySafeterXdsAuthorityUnavailable",
        "JoySafeterXdsRecoveryOverBudget",
        "JoySafeterXdsSustainedNacks",
        "JoySafeterXdsDeliveryStalled",
        "JoySafeterXdsDegradedInventory",
        "JoySafeterXdsEnvoyNodeCountMismatch",
    ]:
        assert f"alert: {alert_name}" in rule

    for forbidden_label in ["sandbox_id", "node_name", "resource_name", "policy_hash"]:
        assert forbidden_label not in rule
