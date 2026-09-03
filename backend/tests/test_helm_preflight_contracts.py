import subprocess
from collections import Counter
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.no_db

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "deploy/helm/joysafeter-orchestrator"


def test_helm_templates_use_component_directories_and_single_resource_files() -> None:
    assert list((CHART / "templates").glob("*.yaml")) == []

    for network_policy_type in ("cilium", "standard"):
        command = [
            "helm",
            "template",
            f"structure-{network_policy_type}",
            str(CHART),
            "--set",
            "resourceQuota.enabled=true",
            "--set",
            "monitoring.xdsAlerts.enabled=true",
            "--set",
            "monitoring.runnerAlerts.enabled=true",
            "--set-string",
            f"networkPolicy.type={network_policy_type}",
        ]
        if network_policy_type == "standard":
            command.extend(
                [
                    "--set-string",
                    "agentGateway.kubernetesApiCidrs[0]=10.96.0.1/32",
                ]
            )

        result = subprocess.run(command, capture_output=True, text=True, check=False)

        assert result.returncode == 0, result.stderr
        sources = [
            line.removeprefix("# Source: ")
            for line in result.stdout.splitlines()
            if line.startswith("# Source: ")
        ]
        duplicates = {
            source: count for source, count in Counter(sources).items() if count > 1
        }
        assert duplicates == {}


def test_environment_values_keep_redis_instances_and_keys_isolated() -> None:
    environments = {
        name: yaml.safe_load((CHART / f"values-{name}.yaml").read_text())
        for name in ("dev", "pre", "prod")
    }

    assert len({values["externalSecret"] for values in environments.values()}) == 3
    assert len(
        {
            values["orchestrator"]["redis"]["keyPrefix"]
            for values in environments.values()
        }
    ) == 3
    assert len(
        {
            values["orchestrator"]["eventStream"]["key"]
            for values in environments.values()
        }
    ) == 3
    for values in environments.values():
        assert values["agentIdentity"]["services"] == [
            {
                "name": "jd-wildcard-http",
                "host": "*.jd.com",
                "port": 80,
                "tls": False,
            },
            {
                "name": "jd-wildcard-https",
                "host": "*.jd.com",
                "port": 443,
                "tls": True,
            }
        ]


@pytest.mark.parametrize(
    ("field", "value", "expected_error"),
    [
        ("baseUrl", "", "agentIdentity.baseUrl is required"),
        ("clientId", "", "agentIdentity.clientId is required"),
        ("platformId", "", "agentIdentity.platformId is required"),
    ],
)
def test_helm_rejects_incomplete_jd_identity_configuration(
    tmp_path: Path,
    field: str,
    value: str | list[str],
    expected_error: str,
) -> None:
    identity_values: dict[str, object] = {
        "provider": "jd",
        "baseUrl": "https://identity.example.com",
        "services": [],
        "clientId": "client-id",
        "platformId": "platform-id",
    }
    identity_values[field] = value
    values_file = tmp_path / "identity-values.yaml"
    values_file.write_text(yaml.safe_dump({"agentIdentity": identity_values}))
    command = [
        "helm",
        "template",
        "identity-contract",
        str(CHART),
        "--values",
        str(values_file),
    ]

    result = subprocess.run(command, capture_output=True, text=True, check=False)

    assert result.returncode != 0
    assert expected_error in result.stderr


def test_helm_accepts_complete_jd_identity_configuration(tmp_path: Path) -> None:
    values_file = tmp_path / "identity-values.yaml"
    values_file.write_text(
        yaml.safe_dump(
            {
                "agentIdentity": {
                    "provider": "jd",
                    "baseUrl": "https://identity.example.com",
                    "services": [
                        {
                            "name": "crm",
                            "host": "crm.example.com",
                            "port": 80,
                            "tls": False,
                        },
                        {
                            "name": "dataagents",
                            "host": "*.dataagent.example.com",
                            "port": 443,
                            "tls": True,
                        },
                    ],
                    "clientId": "client-id",
                    "platformId": "platform-id",
                }
            }
        )
    )

    result = subprocess.run(
        ["helm", "template", "identity-contract", str(CHART), "--values", str(values_file)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.count("kind: AgentIdentityService") == 2
    assert 'host: "crm.example.com"' in result.stdout
    assert 'host: "*.dataagent.example.com"' in result.stdout
    assert "port: 80\n  tls: false" in result.stdout
    assert "AGENT_IDENTITY_ALLOWED_HOSTS" not in result.stdout


def test_sandbox_pods_receive_chart_image_pull_secrets() -> None:
    configmap = (
        REPO_ROOT
        / "deploy/helm/joysafeter-orchestrator/templates/orchestrator/configmap.yaml"
    ).read_text()
    k8s_provider = (REPO_ROOT / "backend/app/joysafeter_orchestrator_rs/src/sandbox/k8s.rs").read_text()

    assert "JOYSAFETER_K8S_IMAGE_PULL_SECRETS" in configmap
    assert 'pod_spec["imagePullSecrets"]' in k8s_provider


def test_envoy_uses_leader_only_agent_gateway_xds_service() -> None:
    daemonset = (
        REPO_ROOT
        / "deploy/helm/joysafeter-orchestrator/templates/envoy/daemonset.yaml"
    ).read_text()
    gateway = (
        REPO_ROOT
        / "deploy/helm/joysafeter-orchestrator/templates/agent-gateway/service.yaml"
    ).read_text()

    assert '"address": "joysafeter-agent-gateway.' in daemonset
    assert 'joysafeter-agent-gateway-leader: "true"' in gateway


def test_runtime_service_accounts_have_minimum_kubernetes_permissions() -> None:
    rbac = "\n".join(
        [
            (
                REPO_ROOT
                / "deploy/helm/joysafeter-orchestrator/templates/orchestrator/role.yaml"
            ).read_text(),
            (
                REPO_ROOT
                / "deploy/helm/joysafeter-orchestrator/templates/agent-gateway/role.yaml"
            ).read_text(),
        ]
    )
    assert 'resources: ["agentidentityservices"]' in rbac
    assert 'verbs: ["get", "list", "watch"]' in rbac

    assert 'resources: ["pods"]' in rbac
    assert 'verbs: ["get", "list", "watch", "create", "delete", "patch"]' in rbac
    assert 'resources: ["pods/exec"]' in rbac
    assert 'verbs: ["get", "create"]' in rbac
    assert 'resources: ["pods/log"]' not in rbac
    assert 'resources: ["pods/attach"]' not in rbac
    assert 'resources: ["persistentvolumeclaims"]' not in rbac
    assert 'resources: ["networkpolicies"]' not in rbac
    assert 'resources: ["leases"]' in rbac
    assert 'verbs: ["get", "create", "update"]' in rbac


def test_envoy_admin_is_loopback_only_with_in_container_probes() -> None:
    daemonset = (
        REPO_ROOT
        / "deploy/helm/joysafeter-orchestrator/templates/envoy/daemonset.yaml"
    ).read_text()

    assert '"address": "127.0.0.1"' in daemonset
    assert '"address": "0.0.0.0"' not in daemonset
    assert daemonset.count("exec 3<>/dev/tcp/127.0.0.1/9901") >= 2
    assert "GET /ready HTTP/1.1" in daemonset
    assert "httpGet:" not in daemonset
    assert "tcpSocket:" not in daemonset


def test_standard_network_policies_restrict_dns_and_envoy_ingress() -> None:
    policy = "\n".join(
        (
            REPO_ROOT
            / f"deploy/helm/joysafeter-orchestrator/templates/{component}/networkpolicy.yaml"
        ).read_text()
        for component in ("sandbox", "envoy", "orchestrator", "agent-gateway")
    )

    assert "namespaceSelector: {}" not in policy
    assert policy.count("kubernetes.io/metadata.name: kube-system") == 3
    assert "name: joysafeter-envoy-egress" in policy
    assert "ingressDeny:" in policy
    assert "ingress: []" in policy
