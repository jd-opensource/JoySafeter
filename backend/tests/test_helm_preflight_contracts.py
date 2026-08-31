import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.no_db

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "deploy/helm/joysafeter-orchestrator"


@pytest.mark.parametrize(
    ("field", "value", "expected_error"),
    [
        ("baseUrl", "", "agentIdentity.baseUrl is required"),
        ("allowedHosts", [], "agentIdentity.allowedHosts must contain at least one host"),
        ("allowedHosts", ["  "], "agentIdentity.allowedHosts must not contain empty hosts"),
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
    identity_values: dict[str, str | list[str]] = {
        "provider": "jd",
        "baseUrl": "https://identity.example.com",
        "allowedHosts": ["crm.example.com"],
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
                    "allowedHosts": ["crm.example.com"],
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
    assert 'AGENT_IDENTITY_ALLOWED_HOSTS: "crm.example.com"' in result.stdout


def test_sandbox_pods_receive_chart_image_pull_secrets() -> None:
    configmap = (
        REPO_ROOT / "deploy/helm/joysafeter-orchestrator/templates/configmap.yaml"
    ).read_text()
    k8s_provider = (
        REPO_ROOT / "backend/app/joysafeter_orchestrator_rs/src/sandbox/k8s.rs"
    ).read_text()

    assert "JOYSAFETER_K8S_IMAGE_PULL_SECRETS" in configmap
    assert 'pod_spec["imagePullSecrets"]' in k8s_provider


def test_multi_mode_envoy_uses_leader_only_xds_service() -> None:
    daemonset = (
        REPO_ROOT / "deploy/helm/joysafeter-orchestrator/templates/envoy-daemonset.yaml"
    ).read_text()
    service = (
        REPO_ROOT / "deploy/helm/joysafeter-orchestrator/templates/service.yaml"
    ).read_text()

    assert '"address": "joysafeter-orchestrator-xds.' in daemonset
    assert 'joysafeter-xds-leader: "true"' in service


def test_xds_leader_has_pod_patch_and_lease_update_permissions() -> None:
    rbac = (REPO_ROOT / "deploy/helm/joysafeter-orchestrator/templates/rbac.yaml").read_text()

    assert 'resources: ["pods", "pods/exec", "pods/log", "pods/attach"]' in rbac
    assert 'verbs: ["get", "list", "watch", "create", "delete", "patch"]' in rbac
    assert 'resources: ["leases"]' in rbac
    assert 'verbs: ["get", "create", "update"]' in rbac
