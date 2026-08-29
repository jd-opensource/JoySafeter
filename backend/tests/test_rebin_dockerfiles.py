import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

REPO_ROOT = Path(__file__).resolve().parents[2]

# Prebuilt-binary orchestrator Dockerfiles: the Rust binary is cross-compiled on
# the host with cargo-zigbuild (deploy.sh ensure_orchestrator_binary) and COPYed
# in per-arch — no in-image compilation. One Dockerfile per architecture.
BINARY_ORCHESTRATOR_DOCKERFILES = (
    "orchestrator-rs-amd64.Dockerfile",
    "orchestrator-rs-arm64.Dockerfile",
)

# Source Dockerfiles that still compile in-image (used by GitHub CI on native
# runners). Kept for the multi-arch CI build path.
SOURCE_ORCHESTRATOR_DOCKERFILES = ("orchestrator-rs.Dockerfile",)
RUNNER_BUILDER_DOCKERFILE = "runner-builder.Dockerfile"
RUNTIME_ENGINES = ("claudecode", "codex", "pi", "native")


@pytest.mark.parametrize("filename", BINARY_ORCHESTRATOR_DOCKERFILES)
def test_binary_dockerfile_copies_prebuilt_binary_without_compiling(filename: str) -> None:
    source = (REPO_ROOT / "deploy/docker" / filename).read_text()

    assert "release/joysafeter-orchestrator" in source
    assert "RUN cargo build" not in source
    assert "RUN cargo zigbuild" not in source


def test_binary_dockerfiles_target_distinct_architectures() -> None:
    amd64 = (REPO_ROOT / "deploy/docker/orchestrator-rs-amd64.Dockerfile").read_text()
    arm64 = (REPO_ROOT / "deploy/docker/orchestrator-rs-arm64.Dockerfile").read_text()

    # amd64 parameterizes the triple via `ARG TARGET` (deploy.sh passes the
    # build-platform triple); its default declares x86_64. arm64 hardcodes its
    # triple. Either way each image must target its own arch and not the other's.
    assert "x86_64-unknown-linux-gnu" in amd64
    assert "aarch64-unknown-linux-gnu" not in amd64
    assert "target/aarch64-unknown-linux-gnu/release/" in arm64
    assert "x86_64-unknown-linux-gnu" not in arm64


@pytest.mark.parametrize("filename", SOURCE_ORCHESTRATOR_DOCKERFILES)
def test_orchestrator_source_dockerfile_copies_compile_time_inputs(filename: str) -> None:
    source = (REPO_ROOT / "deploy/docker" / filename).read_text()

    assert "COPY proto ./proto" in source
    assert "COPY backend/app/joysafeter_orchestrator_rs ./backend/app/joysafeter_orchestrator_rs" in source
    assert "COPY backend/config ./backend/config" in source
    build_command = next(marker for marker in ("RUN cargo build", "RUN cargo zigbuild") if marker in source)
    assert source.index("COPY backend/config ./backend/config") < source.index(build_command)


@pytest.mark.parametrize(
    "filename",
    (*SOURCE_ORCHESTRATOR_DOCKERFILES, *BINARY_ORCHESTRATOR_DOCKERFILES),
)
def test_orchestrator_dockerfiles_do_not_export_dead_global_enable_switch(filename: str) -> None:
    source = (REPO_ROOT / "deploy/docker" / filename).read_text()

    assert "JOYSAFETER_ENABLED" not in source


def test_runner_builder_compiles_inside_target_linux_platform() -> None:
    source = (REPO_ROOT / "deploy/docker" / RUNNER_BUILDER_DOCKERFILE).read_text()

    assert not source.startswith("# syntax=docker/dockerfile")
    assert "FROM ${RUST_IMAGE} AS builder" in source
    assert "COPY proto ./proto" in source
    assert "COPY shared ./shared" in source
    assert "COPY sandbox-runner ./sandbox-runner" in source
    assert "cargo build --release -p joysafeter-runner" in source
    assert "FROM scratch AS export" in source
    assert "/joysafeter-runner" in source


def test_runner_builder_context_contains_only_required_sources() -> None:
    source = (REPO_ROOT / "deploy/docker" / f"{RUNNER_BUILDER_DOCKERFILE}.dockerignore").read_text()

    assert source.startswith("*\n")
    assert "!proto/**" in source
    assert "!shared/**" in source
    assert "!sandbox-runner/**" in source
    assert "**/target/" in source


def test_runtime_runner_build_uses_buildkit_export_not_host_zigbuild() -> None:
    source = (REPO_ROOT / "deploy/deploy.sh").read_text()
    match = re.search(
        r"ensure_runtime_runner_binary\(\) \{(?P<body>.*?)\n\}\n\nbuild_runtime_image\(\)",
        source,
        re.DOTALL,
    )

    assert match is not None
    body = match.group("body")
    assert "runner-builder.Dockerfile" in body
    assert "docker buildx build" in body
    assert '--target "export"' in body
    assert "type=local,dest=$output_dir" in body
    assert '"$PROJECT_ROOT/shared/rust"' in body
    assert '"$PROJECT_ROOT/proto"' in body
    assert '"$SCRIPT_DIR/docker/runner-builder.Dockerfile"' in body
    assert '"$SCRIPT_DIR/docker/runner-builder.Dockerfile.dockerignore"' in body
    assert "zigbuild_rust_binary" not in body
    assert "cargo zigbuild" not in body


@pytest.mark.parametrize("workflow", ("docker-build.yml", "release.yml"))
def test_ci_builds_runner_through_the_same_linux_builder(workflow: str) -> None:
    source = (REPO_ROOT / ".github/workflows" / workflow).read_text()

    assert "runner-builder.Dockerfile" in source
    assert "Build runner with Linux Builder" in source
    assert "cargo zigbuild --release -p joysafeter-runner" not in source


@pytest.mark.parametrize("engine", RUNTIME_ENGINES)
@pytest.mark.parametrize(
    ("arch", "target"),
    (
        ("amd64", "x86_64-unknown-linux-gnu"),
        ("arm64", "aarch64-unknown-linux-gnu"),
    ),
)
def test_runtime_images_only_package_the_shared_runner(engine: str, arch: str, target: str) -> None:
    source = (REPO_ROOT / "deploy/docker" / f"{engine}-{arch}.Dockerfile").read_text()

    assert f"COPY target/{target}/release/joysafeter-runner" in source
    assert "cargo build" not in source
    assert "cargo zigbuild" not in source


def test_deploy_cli_registers_pi_as_a_first_class_runtime() -> None:
    source = (REPO_ROOT / "deploy/deploy.sh").read_text()

    for marker in (
        'PI_IMAGE="${PI_IMAGE:-joysafeter-pi}"',
        "--pi-only",
        "pi:linux/amd64",
        "pi:linux/arm64",
        "BUILD_PI",
        "PULL_PI",
        "JOYSAFETER_IMAGE_PI",
    ):
        assert marker in source


def test_kubernetes_deployments_project_the_pi_runtime_image() -> None:
    values = (REPO_ROOT / "deploy/helm/joysafeter-orchestrator/values.yaml").read_text()
    configmap = (REPO_ROOT / "deploy/helm/joysafeter-orchestrator/templates/configmap.yaml").read_text()
    complete = (REPO_ROOT / "deploy/k8s/orchestrator-complete.yaml").read_text()
    multi = (REPO_ROOT / "deploy/k8s/orchestrator-multi.yaml").read_text()

    assert "pi: aisec-repo.jd.com/joysafeter/joysafeter-pi:latest" in values
    assert "JOYSAFETER_IMAGE_PI: {{ .Values.image.sandbox.pi | quote }}" in configmap
    assert "JOYSAFETER_IMAGE_PI" in complete
    assert "JOYSAFETER_IMAGE_PI" in multi
