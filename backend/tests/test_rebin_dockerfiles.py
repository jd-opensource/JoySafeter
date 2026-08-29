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
RUNTIME_DOCKERFILE = "runtime.Dockerfile"
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


def test_runtime_dockerfile_compiles_runner_inside_target_linux_platform() -> None:
    source = (REPO_ROOT / "deploy/docker" / RUNTIME_DOCKERFILE).read_text()

    first_from = source.index("FROM ")
    assert source.index('ARG RUST_IMAGE=') < first_from
    assert source.index('ARG BASE_IMAGE_REGISTRY=') < first_from
    assert "FROM ${RUST_IMAGE} AS runner-builder" in source
    assert "COPY proto ./proto" in source
    assert "COPY shared ./shared" in source
    assert "COPY sandbox-runner ./sandbox-runner" in source
    assert "cargo build --release -p joysafeter-runner" in source
    assert "COPY --from=runner-builder" in source
    assert "/usr/local/bin/joysafeter-runner" in source


def test_runtime_build_context_contains_only_required_sources() -> None:
    source = (REPO_ROOT / "deploy/docker" / f"{RUNTIME_DOCKERFILE}.dockerignore").read_text()

    assert source.startswith("*\n")
    assert "!proto/**" in source
    assert "!shared/**" in source
    assert "!sandbox-runner/**" in source
    assert "!deploy/docker/runtime.Dockerfile" in source
    assert "!deploy/docker/runner-entrypoint.sh" in source
    assert "!deploy/docker/codex-entrypoint.sh" in source
    assert "!deploy/docker/pi-entrypoint.sh" in source
    assert "!deploy/docker/claude-code-best-2.8.4.tgz" in source
    assert "**/target/" in source


def test_runtime_build_selects_named_target_without_host_binary_staging() -> None:
    source = (REPO_ROOT / "deploy/lib/images.sh").read_text()
    match = re.search(
        r"build_runtime_image\(\) \{(?P<body>.*?)\n\}\n\n# 镜像组件",
        source,
        re.DOTALL,
    )

    assert match is not None
    body = match.group("body")
    assert '"$SCRIPT_DIR/docker/runtime.Dockerfile"' in body
    assert '--target "$engine"' in body
    assert '--build-arg "RUST_IMAGE=$RUST_IMAGE"' in body
    assert "ensure_runtime_runner_binary" not in body
    assert "target/$target/release/joysafeter-runner" not in body
    assert "zigbuild_rust_binary" not in body
    assert "cargo zigbuild" not in body


@pytest.mark.parametrize("workflow", ("docker-build.yml", "release.yml"))
def test_ci_builds_each_runtime_from_the_unified_multistage_dockerfile(workflow: str) -> None:
    source = (REPO_ROOT / ".github/workflows" / workflow).read_text()
    registry_rows = [
        line.split("\t")
        for line in (REPO_ROOT / "deploy/image-components.tsv").read_text().splitlines()
        if line and not line.startswith("#")
    ]
    runtime_rows = {row[0]: row for row in registry_rows if row[1] == "runtime"}

    assert "./deploy/deploy.sh registry --family container --format github" in source
    assert "target: ${{ matrix.image.target }}" in source
    assert set(runtime_rows) == set(RUNTIME_ENGINES)
    for engine, row in runtime_rows.items():
        assert row[6] == "deploy/docker/runtime.Dockerfile"
        assert row[8] == engine
    assert "runner-builder.Dockerfile" not in source
    assert "cargo zigbuild --release -p joysafeter-runner" not in source


@pytest.mark.parametrize("engine", RUNTIME_ENGINES)
def test_runtime_dockerfile_exposes_one_final_stage_per_engine(engine: str) -> None:
    source = (REPO_ROOT / "deploy/docker" / RUNTIME_DOCKERFILE).read_text()

    assert f"FROM runtime-with-runner AS {engine}" in source
    assert "cargo zigbuild" not in source


def test_legacy_per_arch_runtime_dockerfiles_are_removed() -> None:
    docker_dir = REPO_ROOT / "deploy/docker"

    for engine in RUNTIME_ENGINES:
        assert not (docker_dir / f"{engine}-amd64.Dockerfile").exists()
        assert not (docker_dir / f"{engine}-arm64.Dockerfile").exists()
    assert not (docker_dir / "runner-builder.Dockerfile").exists()
    assert not (docker_dir / "runner-builder.Dockerfile.dockerignore").exists()


def test_deploy_cli_registers_pi_as_a_first_class_runtime() -> None:
    entrypoint = (REPO_ROOT / "deploy/deploy.sh").read_text()
    images = (REPO_ROOT / "deploy/lib/images.sh").read_text()
    registry = (REPO_ROOT / "deploy/image-components.tsv").read_text()

    for marker in (
        "pi\truntime\tPi 运行镜像\truntime\tPI_IMAGE\tjoysafeter-pi",
        "\tpi\tJOYSAFETER_IMAGE_PI\tcontainer\t-",
    ):
        assert marker in registry
    assert "--component NAME" in entrypoint
    assert "--group GROUP" in entrypoint
    assert '--target "$engine"' in images


def test_kubernetes_deployments_project_the_pi_runtime_image() -> None:
    values = (REPO_ROOT / "deploy/helm/joysafeter-orchestrator/values.yaml").read_text()
    configmap = (REPO_ROOT / "deploy/helm/joysafeter-orchestrator/templates/configmap.yaml").read_text()

    assert "pi: aisec-repo.jd.com/joysafeter/joysafeter-pi:latest" in values
    assert "JOYSAFETER_IMAGE_PI: {{ .Values.image.sandbox.pi | quote }}" in configmap
