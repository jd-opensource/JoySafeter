from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "deploy/helm/joysafeter-orchestrator"


def read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text()


def test_helm_declares_dedicated_xds_port_and_secret_contract() -> None:
    values = read("deploy/helm/joysafeter-orchestrator/values.yaml")
    configmap = read("deploy/helm/joysafeter-orchestrator/templates/configmap.yaml")
    secret = read("deploy/helm/joysafeter-orchestrator/templates/secret.yaml")
    deployment = read("deploy/helm/joysafeter-orchestrator/templates/deployment.yaml")

    assert "xds:\n    port: 9092" in values
    assert "JOYSAFETER_XDS_HOST" in configmap
    assert "JOYSAFETER_XDS_PORT" in configmap
    assert "JOYSAFETER_ENVOY_GRPC_PORT" not in configmap
    assert "JOYSAFETER_XDS_AUTH_KEYRING" in secret
    assert "JOYSAFETER_XDS_AUTH_WRITE_KEY_ID" in secret
    assert "JOYSAFETER_XDS_AUTH_TOKEN" in secret
    assert "name: xds" in deployment
    assert "containerPort: {{ .Values.orchestrator.xds.port }}" in deployment


def test_xds_service_targets_only_the_dedicated_port() -> None:
    service = read("deploy/helm/joysafeter-orchestrator/templates/service.yaml")
    xds_service = service.split("name: joysafeter-orchestrator-xds", maxsplit=1)[1]

    assert "port: {{ .Values.orchestrator.xds.port }}" in xds_service
    assert "targetPort: xds" in xds_service
    assert "targetPort: grpc" not in xds_service


def test_envoy_bootstrap_sends_only_the_selected_xds_token() -> None:
    daemonset = read("deploy/helm/joysafeter-orchestrator/templates/envoy-daemonset.yaml")

    assert '"key": "x-joysafeter-xds-token"' in daemonset
    assert '"value": "${JOYSAFETER_XDS_AUTH_TOKEN}"' in daemonset
    assert "secretKeyRef:" in daemonset
    assert "key: JOYSAFETER_XDS_AUTH_TOKEN" in daemonset
    assert '"port_value": {{ .Values.orchestrator.xds.port }}' in daemonset


def test_network_policy_separates_sandbox_runner_and_envoy_xds_traffic() -> None:
    policy = read("deploy/helm/joysafeter-orchestrator/templates/networkpolicy.yaml")
    sandbox_policy, envoy_policy = policy.split("name: joysafeter-envoy-egress", maxsplit=1)

    assert ".Values.orchestrator.grpc.port" in sandbox_policy
    assert ".Values.orchestrator.xds.port" not in sandbox_policy
    assert ".Values.orchestrator.xds.port" in envoy_policy
    assert "name: joysafeter-orchestrator-ingress" in policy
    ingress_policy = policy.split(
        "name: joysafeter-orchestrator-ingress", maxsplit=1
    )[1]
    assert ".Values.orchestrator.grpc.port" in ingress_policy
    assert ".Values.orchestrator.xds.port" in ingress_policy


def test_compose_uses_internal_dedicated_authenticated_xds_port() -> None:
    compose = read("deploy/docker-compose.yml")

    assert "JOYSAFETER_XDS_PORT: 9092" in compose
    assert "JOYSAFETER_XDS_AUTH_KEYRING:" in compose
    assert "JOYSAFETER_XDS_AUTH_WRITE_KEY_ID:" in compose
    assert "JOYSAFETER_XDS_AUTH_TOKEN:" in compose
    assert "${JOYSAFETER_XDS_PORT_HOST:-9092}:9092" in compose


def test_obsolete_envoy_grpc_port_bridge_is_removed() -> None:
    audited_files = [
        "backend/env.example",
        "backend/app/joysafeter_shared/config/settings.py",
        "backend/app/joysafeter_orchestrator_rs/src/config.rs",
        "deploy/helm/joysafeter-orchestrator/templates/configmap.yaml",
        "deploy/docker-compose.yml",
        "deploy/k8s/env-reference.md",
        "deploy/k8s/orchestrator-multi.yaml",
        "deploy/k8s/orchestrator-complete.yaml",
        "deploy/k8s/orchestrator-deployment.yaml",
    ]

    for relative_path in audited_files:
        assert "JOYSAFETER_ENVOY_GRPC_PORT" not in read(relative_path), relative_path
        assert "envoy_grpc_port" not in read(relative_path), relative_path


@pytest.mark.parametrize(
    "relative_path",
    [
        "deploy/k8s/orchestrator-multi.yaml",
        "deploy/k8s/orchestrator-complete.yaml",
    ],
)
def test_raw_k8s_manifests_authenticate_on_dedicated_xds_port(
    relative_path: str,
) -> None:
    manifest = read(relative_path)

    assert "containerPort: 9092" in manifest
    assert "name: xds" in manifest
    assert "JOYSAFETER_XDS_PORT" in manifest
    assert '"key": "x-joysafeter-xds-token"' in manifest
    assert '"value": "${JOYSAFETER_XDS_AUTH_TOKEN}"' in manifest
    assert "key: JOYSAFETER_XDS_AUTH_TOKEN" in manifest

    sandbox_policy, envoy_policy = manifest.split(
        "name: joysafeter-envoy-egress", maxsplit=1
    )
    assert "# 允许连 orchestrator (gRPC 控制面)" in sandbox_policy
    assert "- port: 9090" in sandbox_policy
    assert "- port: 9092" in envoy_policy
    assert "name: joysafeter-orchestrator-ingress" in manifest


def test_multi_manifest_keeps_runner_and_xds_services_distinct() -> None:
    manifest = read("deploy/k8s/orchestrator-multi.yaml")
    runner_service, xds_service = manifest.split(
        "name: joysafeter-orchestrator-xds", maxsplit=1
    )

    assert "port: 9090\n    targetPort: grpc" in runner_service
    assert "port: 9092\n    targetPort: xds" in xds_service


def test_xds_health_metrics_and_alerts_are_deployed_as_one_contract() -> None:
    application = read(
        "backend/app/joysafeter_orchestrator_rs/src/bootstrap/application.rs"
    )
    supervisor = read(
        "backend/app/joysafeter_orchestrator_rs/src/bootstrap/supervisor.rs"
    )
    values = read("deploy/helm/joysafeter-orchestrator/values.yaml")
    rule = read("deploy/helm/joysafeter-orchestrator/templates/prometheusrule.yaml")

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
