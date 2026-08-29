import json
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_DIR = REPO_ROOT / "deploy"


def test_deploy_entrypoint_loads_bounded_capability_modules() -> None:
    source = (DEPLOY_DIR / "deploy.sh").read_text()

    for module in ("common", "compose", "development", "images", "kubernetes"):
        assert f'"$SCRIPT_DIR/lib/{module}.sh"' in source

    for implementation in (
        "build_image()",
        "run_local_compose()",
        "run_host_development()",
        "pull_images()",
        "run_kubernetes_command()",
    ):
        assert implementation not in source


def test_kubernetes_capabilities_have_one_cli_owner() -> None:
    source = (DEPLOY_DIR / "lib/kubernetes.sh").read_text()

    for capability in (
        "kubernetes_deploy()",
        "kubernetes_uninstall()",
        "kubernetes_verify()",
        "kubernetes_scale()",
        "kubernetes_status()",
        "kubernetes_apply_secrets()",
    ):
        assert capability in source

    for legacy_script in (
        "deploy.sh",
        "create-secrets.sh",
        "scale.sh",
        "verify.sh",
        "build-push-amd64-images.sh",
    ):
        assert not (DEPLOY_DIR / "scripts" / legacy_script).exists()
    assert not (DEPLOY_DIR / "local-test.sh").exists()


def test_kubernetes_help_does_not_require_docker() -> None:
    result = subprocess.run(
        ["bash", str(DEPLOY_DIR / "deploy.sh"), "k8s", "--help"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr
    assert "k8s deploy" in result.stdout
    assert "Docker" not in result.stderr


def test_plain_single_arch_push_is_owned_by_image_module() -> None:
    entrypoint = (DEPLOY_DIR / "deploy.sh").read_text()
    images = (DEPLOY_DIR / "lib/images.sh").read_text()

    assert "--plain" in entrypoint
    assert "PLAIN_IMAGE" in entrypoint
    assert "--provenance=false" in images
    assert 'docker push "$image_name"' in images


def test_image_commands_share_one_component_registry_and_selector() -> None:
    entrypoint = (DEPLOY_DIR / "deploy.sh").read_text()
    images = (DEPLOY_DIR / "lib/images.sh").read_text()
    deploy_libraries = "\n".join(path.read_text() for path in (DEPLOY_DIR / "lib").glob("*.sh"))

    for capability in (
        "image_component_registry()",
        "select_image_component()",
        "select_image_group()",
        "selected_image_components()",
        "build_component()",
        "pull_component()",
    ):
        assert capability in images

    for option in ("--component NAME", "--group GROUP"):
        assert option in entrypoint

    for legacy in (
        "BACKEND_ONLY",
        "FRONTEND_ONLY",
        "ORCHESTRATOR_ONLY",
        "SKILLSPECTOR_ONLY",
        "RUNTIME_ONLY",
        "CLAUDECODE_ONLY",
        "CODEX_ONLY",
        "NATIVE_ONLY",
        "PI_ONLY",
        "BUILD_ALL",
        "BUILD_BACKEND",
        "PULL_BACKEND",
    ):
        assert legacy not in entrypoint
        assert legacy not in deploy_libraries

    result = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{DEPLOY_DIR / "deploy.sh"}"; '
            "select_image_group runtime; selected_image_components",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["claudecode", "codex", "native", "pi"]


def test_component_registry_is_the_single_source_for_cli_and_ci() -> None:
    registry = DEPLOY_DIR / "image-components.tsv"
    assert registry.is_file()
    deploy_libraries = "\n".join(path.read_text() for path in (DEPLOY_DIR / "lib").glob("*.sh"))
    assert "runtime_target_for()" not in deploy_libraries
    assert "joysafeter-claudecode:latest" not in deploy_libraries

    result = subprocess.run(
        [
            "bash",
            str(DEPLOY_DIR / "deploy.sh"),
            "registry",
            "--family",
            "container",
            "--format",
            "github",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    matrix = json.loads(result.stdout)
    assert [entry["component"] for entry in matrix["include"]] == [
        "backend",
        "frontend",
        "skillspector",
        "claudecode",
        "codex",
        "native",
        "pi",
    ]
    assert matrix["include"][3]["dockerfile"] == "./deploy/docker/runtime.Dockerfile"
    assert matrix["include"][3]["target"] == "claudecode"

    for workflow_name in ("docker-build.yml", "release.yml"):
        workflow = (REPO_ROOT / ".github/workflows" / workflow_name).read_text()
        assert "./deploy/deploy.sh registry --family container --format github" in workflow
        assert "./deploy/deploy.sh registry --family orchestrator --format github" in workflow
        for image_name in (
            "joysafeter-backend",
            "joysafeter-frontend",
            "joysafeter-skillspector",
            "joysafeter-claudecode",
            "joysafeter-codex",
            "joysafeter-native",
            "joysafeter-pi",
            "joysafeter-orchestrator-rs",
        ):
            assert f"name: {image_name}" not in workflow


def test_helm_chart_is_the_only_kubernetes_manifest_source() -> None:
    assert not list((DEPLOY_DIR / "k8s").glob("*.yaml"))
    assert not list((DEPLOY_DIR / "helm").glob("*.tar.gz"))
    assert (DEPLOY_DIR / "helm/joysafeter-orchestrator/Chart.yaml").is_file()


def test_build_image_accepts_no_optional_build_arguments_on_macos_bash() -> None:
    result = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{DEPLOY_DIR / "deploy.sh"}"; '
            "docker() { printf 'docker %s\\n' \"$*\"; }; "
            "USE_BUILDX=true; PUSH=false; NO_CACHE=false; PLAIN_IMAGE=false; "
            "PLATFORMS=linux/arm64; BASE_IMAGE_REGISTRY=; PIP_INDEX_URL=; UV_INDEX_URL=; "
            "build_image Test /tmp/Dockerfile /tmp test:latest",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "docker buildx build" in result.stdout


def test_kubernetes_verify_uses_the_runtime_image_health_client() -> None:
    result = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{DEPLOY_DIR / "deploy.sh"}"; '
            "check_command() { return 0; }; "
            "kubernetes_kubectl() { "
            "case \"$*\" in "
            "*'get deployment'*jsonpath*) echo 2 ;; "
            "*'get daemonset'*numberAvailable*) echo 1 ;; "
            "*'get daemonset'*desiredNumberScheduled*) echo 1 ;; "
            "*'get pods'*jsonpath*) echo pod-a ;; "
            "*'exec '*curl*) echo ready ;; "
            "*'exec '*) return 127 ;; "
            "esac; }; "
            "kubernetes_verify test-ns '' 5m 1s",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "pod-a readiness: ready" in result.stdout


def test_host_development_is_exposed_through_the_single_entrypoint() -> None:
    result = subprocess.run(
        ["bash", str(DEPLOY_DIR / "deploy.sh"), "--help"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "dev" in result.stdout
    assert "local-test.sh" not in result.stdout

    development = (DEPLOY_DIR / "lib/development.sh").read_text()
    assert " up -d db " not in development
    assert "exec -T db" not in development
    assert "logs db" not in development
