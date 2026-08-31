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
    ):
        assert not (DEPLOY_DIR / "scripts" / legacy_script).exists()
    assert not (DEPLOY_DIR / "local-test.sh").exists()


def test_amd64_push_compatibility_script_is_only_a_thin_cli_wrapper() -> None:
    wrapper = DEPLOY_DIR / "scripts/build-push-amd64-images.sh"
    source = wrapper.read_text()
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", str(wrapper)],
        cwd=REPO_ROOT,
        check=False,
    )

    assert ignored.returncode == 1
    assert "deploy/deploy.sh" in source
    assert "--profile" in source
    assert "--arch amd64" in source
    assert "--plain" in source
    assert "docker build" not in source
    assert "docker push" not in source


def test_amd64_push_compatibility_script_translates_legacy_targets(
    tmp_path: Path,
) -> None:
    deploy_dir = tmp_path / "deploy"
    scripts_dir = deploy_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    wrapper = scripts_dir / "build-push-amd64-images.sh"
    wrapper.write_text(
        (DEPLOY_DIR / "scripts/build-push-amd64-images.sh").read_text()
    )
    captured_args = tmp_path / "deploy-args"
    entrypoint = deploy_dir / "deploy.sh"
    entrypoint.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$@\" > {captured_args!s}\n"
    )
    entrypoint.chmod(0o755)

    result = subprocess.run(
        ["bash", str(wrapper), "orchestrator", "native"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert captured_args.read_text().splitlines() == [
        "push",
        "--component",
        "orchestrator",
        "--component",
        "native",
        "--arch",
        "amd64",
        "--plain",
        "--registry",
        "aisec-repo.jd.com/joysafeter",
        "--tag",
        "latest",
    ]


def test_amd64_push_compatibility_script_translates_legacy_target_environment(
    tmp_path: Path,
) -> None:
    deploy_dir = tmp_path / "deploy"
    scripts_dir = deploy_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    wrapper = scripts_dir / "build-push-amd64-images.sh"
    wrapper.write_text(
        (DEPLOY_DIR / "scripts/build-push-amd64-images.sh").read_text()
    )
    captured_args = tmp_path / "deploy-args"
    entrypoint = deploy_dir / "deploy.sh"
    entrypoint.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$@\" > {captured_args!s}\n"
    )
    entrypoint.chmod(0o755)

    result = subprocess.run(
        ["bash", str(wrapper)],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "TARGETS": "native,pi",
            "REGISTRY_PREFIX": "registry.example.com/team",
            "TAG": "candidate",
        },
    )

    assert result.returncode == 0, result.stderr
    assert captured_args.read_text().splitlines() == [
        "push",
        "--component",
        "native",
        "--component",
        "pi",
        "--arch",
        "amd64",
        "--plain",
        "--registry",
        "registry.example.com/team",
        "--tag",
        "candidate",
    ]


def test_amd64_push_compatibility_script_preserves_build_only_mode(
    tmp_path: Path,
) -> None:
    deploy_dir = tmp_path / "deploy"
    scripts_dir = deploy_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    wrapper = scripts_dir / "build-push-amd64-images.sh"
    wrapper.write_text(
        (DEPLOY_DIR / "scripts/build-push-amd64-images.sh").read_text()
    )
    captured_args = tmp_path / "deploy-args"
    entrypoint = deploy_dir / "deploy.sh"
    entrypoint.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$@\" > {captured_args!s}\n"
    )
    entrypoint.chmod(0o755)

    result = subprocess.run(
        ["bash", str(wrapper), "native"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "SKIP_PUSH": "1",
            "NO_CACHE": "1",
        },
    )

    assert result.returncode == 0, result.stderr
    args = captured_args.read_text().splitlines()
    assert args[0] == "build"
    assert "--plain" not in args
    assert "--no-cache" in args


def test_amd64_push_compatibility_script_forwards_new_selection_options(
    tmp_path: Path,
) -> None:
    deploy_dir = tmp_path / "deploy"
    scripts_dir = deploy_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    wrapper = scripts_dir / "build-push-amd64-images.sh"
    wrapper.write_text(
        (DEPLOY_DIR / "scripts/build-push-amd64-images.sh").read_text()
    )
    captured_args = tmp_path / "deploy-args"
    entrypoint = deploy_dir / "deploy.sh"
    entrypoint.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$@\" > {captured_args!s}\n"
    )
    entrypoint.chmod(0o755)

    result = subprocess.run(
        ["bash", str(wrapper), "--component", "codex"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    args = captured_args.read_text().splitlines()
    assert "--profile" not in args
    assert args.count("--component") == 1
    assert args[args.index("--component") + 1] == "codex"


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
    assert 'push_plain_image_and_verify "$image_name"' in images


@pytest.mark.parametrize(
    ("profile", "expected_components"),
    [
        ("sandbox-plane", ["orchestrator", "claudecode", "codex", "native", "pi"]),
        (
            "non-app",
            ["orchestrator", "skillspector", "claudecode", "codex", "native", "pi"],
        ),
    ],
)
def test_image_profiles_select_components_from_registry(
    profile: str,
    expected_components: list[str],
) -> None:
    result = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{DEPLOY_DIR / "deploy.sh"}"; '
            f'select_image_profile "{profile}"; selected_image_components',
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == expected_components


def test_plain_push_verifies_the_registry_digest() -> None:
    digest = "sha256:" + "a" * 64
    result = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{DEPLOY_DIR / "deploy.sh"}"; '
            "docker() { "
            'if [ "$1" = push ]; then '
            f'echo "latest: digest: {digest} size: 1234"; '
            'elif [ "$1" = pull ]; then echo "verified:$*"; '
            "else return 1; fi; "
            "}; "
            "PLATFORMS=linux/amd64; PUSH_VERIFY_ATTEMPTS=1; PUSH_VERIFY_DELAY_SECONDS=0; "
            "push_plain_image_and_verify registry.example.com/joysafeter/test:latest",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert digest in result.stdout
    assert f"verified:pull --platform linux/amd64 registry.example.com/joysafeter/test@{digest}" in result.stdout


def test_plain_push_retries_transient_registry_failures(tmp_path: Path) -> None:
    digest = "sha256:" + "c" * 64
    attempts_file = tmp_path / "push-attempts"
    attempts_file.write_text("0")
    result = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{DEPLOY_DIR / "deploy.sh"}"; '
            "docker() { "
            'if [ "$1" = push ]; then '
            f'attempts=$(cat "{attempts_file}"); attempts=$((attempts + 1)); printf "%s" "$attempts" > "{attempts_file}"; '
            'if [ "$attempts" -eq 1 ]; then echo "temporary timeout" >&2; return 1; fi; '
            f'echo "latest: digest: {digest} size: 1234"; '
            'elif [ "$1" = pull ]; then return 0; '
            "fi; "
            "}; "
            "PLATFORMS=linux/amd64; PUSH_ATTEMPTS=2; PUSH_RETRY_DELAY_SECONDS=0; "
            "PUSH_VERIFY_ATTEMPTS=1; PUSH_VERIFY_DELAY_SECONDS=0; "
            "push_plain_image_and_verify registry.example.com/joysafeter/test:latest",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert attempts_file.read_text() == "2"
    assert "镜像推送失败（1/2）" in result.stderr


def test_plain_push_runs_preflight_without_starting_container_buildx() -> None:
    result = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{DEPLOY_DIR / "deploy.sh"}"; '
            'preflight_image_push() { echo "preflight:$1"; }; '
            'init_buildx() { echo "unexpected-buildx"; return 1; }; '
            "selected_image_components() { :; }; "
            "USE_BUILDX=true; PUSH=true; PLAIN_IMAGE=true; REGISTRY=registry.example.com/joysafeter; "
            "build_selected_images",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "preflight:registry.example.com/joysafeter" in result.stdout
    assert "unexpected-buildx" not in result.stdout


def test_plain_image_build_does_not_fall_through_to_buildx_push() -> None:
    digest = "sha256:" + "b" * 64
    result = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{DEPLOY_DIR / "deploy.sh"}"; '
            "docker() { "
            'if [ "$1" = image ] && [ "$2" = inspect ]; then echo amd64; '
            'else printf "docker:%s\\n" "$*"; fi; '
            'if [ "$1" = push ]; then '
            f'echo "latest: digest: {digest} size: 1234"; '
            "fi; "
            "}; "
            "PLAIN_IMAGE=true; PUSH=true; USE_BUILDX=true; NO_CACHE=false; "
            "PLATFORMS=linux/amd64; BASE_IMAGE_REGISTRY=; APT_MIRROR_BASE=; "
            "ALPINE_MIRROR_BASE=; PIP_INDEX_URL=; UV_INDEX_URL=; "
            "PUSH_VERIFY_ATTEMPTS=1; PUSH_VERIFY_DELAY_SECONDS=0; "
            "build_image Test /tmp/Dockerfile /tmp registry.example.com/test:latest",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.count("docker:build --provenance=false") == 1
    assert "docker:buildx build" not in result.stdout


def test_push_preflight_rejects_an_unhealthy_registry_before_build() -> None:
    result = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{DEPLOY_DIR / "deploy.sh"}"; '
            'curl() { printf "503"; }; '
            "REGISTRY=registry.example.com/joysafeter; PLATFORMS=linux/amd64; "
            "preflight_image_push \"$REGISTRY\"",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Registry 不可用" in result.stderr


def test_plain_push_preflight_accepts_authenticated_registry_and_amd64_runtime(
    tmp_path: Path,
) -> None:
    docker_config = tmp_path / "docker"
    docker_config.mkdir()
    (docker_config / "config.json").write_text(
        json.dumps({"auths": {"registry.example.com": {"auth": "redacted"}}})
    )
    result = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{DEPLOY_DIR / "deploy.sh"}"; '
            'curl() { printf "401"; }; '
            'docker() { [ "$1" = run ] && printf "x86_64\\n"; }; '
            "REGISTRY=registry.example.com/joysafeter; PLATFORMS=linux/amd64; PLAIN_IMAGE=true; "
            "preflight_image_push \"$REGISTRY\"",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "DOCKER_CONFIG": str(docker_config)},
    )

    assert result.returncode == 0, result.stderr
    assert "镜像推送预检通过" in result.stdout


def test_push_preflight_uses_the_docker_daemon_registry_scheme(tmp_path: Path) -> None:
    docker_config = tmp_path / "docker"
    docker_config.mkdir()
    (docker_config / "config.json").write_text(
        json.dumps({"auths": {"registry.example.com": {"auth": "redacted"}}})
    )
    captured_url = tmp_path / "registry-url"
    result = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{DEPLOY_DIR / "deploy.sh"}"; '
            'docker() { [ "$1" = info ] && printf "http\\n"; }; '
            f'curl() {{ printf "%s" "${{@: -1}}" > "{captured_url}"; printf "401"; }}; '
            "REGISTRY=registry.example.com/joysafeter; PLATFORMS=linux/amd64; PLAIN_IMAGE=false; "
            "preflight_image_push \"$REGISTRY\"",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "DOCKER_CONFIG": str(docker_config)},
    )

    assert result.returncode == 0, result.stderr
    assert captured_url.read_text() == "http://registry.example.com/v2/"


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
            f'source "{DEPLOY_DIR / "deploy.sh"}"; select_image_group runtime; selected_image_components',
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


def test_helm_release_namespace_is_the_single_namespace_authority() -> None:
    chart_dir = DEPLOY_DIR / "helm/joysafeter-orchestrator"
    template_source = "\n".join(path.read_text() for path in (chart_dir / "templates").glob("*.yaml"))

    assert ".Values.namespace" not in template_source
    assert ".Release.Namespace" in template_source
    for values_file in ("values.yaml", "values-pre.yaml", "values-prod.yaml"):
        assert not any(line.startswith("namespace:") for line in (chart_dir / values_file).read_text().splitlines())


def test_build_image_accepts_no_optional_build_arguments_on_macos_bash() -> None:
    result = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{DEPLOY_DIR / "deploy.sh"}"; '
            "docker() { "
            'if [ "$1" = image ] && [ "$2" = inspect ]; then echo arm64; '
            "else printf 'docker %s\\n' \"$*\"; fi; "
            "}; "
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
            'case "$*" in '
            "*'get deployment'*jsonpath*) echo 2 ;; "
            "*'get daemonset'*numberAvailable*) echo 1 ;; "
            "*'get daemonset'*desiredNumberScheduled*) echo 1 ;; "
            "*'get pods'*jsonpath*) echo pod-a ;; "
            "*'127.0.0.1:9091/healthz/live'*) echo ok ;; "
            "*'127.0.0.1:9091/healthz/ready'*) echo ok ;; "
            "*'127.0.0.1:9091/healthz/xds'*) echo ready ;; "
            "*'127.0.0.1:9091/metrics'*) printf '%s\\n' "
            "'joysafeter_xds_enabled 1' "
            "'joysafeter_xds_authority_phase{phase=\"ready\"} 1' "
            "'joysafeter_xds_active_envoy_nodes 1' "
            "'joysafeter_runner_setup_sent_total 0' "
            "'joysafeter_runner_setup_results_total 0' "
            "'joysafeter_runner_setup_failures_total 0' "
            "'joysafeter_runner_reconnect_setup_total 0' "
            "'joysafeter_runner_start_task_dispatched_total 0' ;; "
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
    assert "pod-a 健康与指标契约通过" in result.stdout
    assert "xDS authority 唯一且 Ready" in result.stdout


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
