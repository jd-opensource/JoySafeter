from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

REPO_ROOT = Path(__file__).resolve().parents[2]


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
