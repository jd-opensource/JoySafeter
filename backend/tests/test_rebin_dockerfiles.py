from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

REPO_ROOT = Path(__file__).resolve().parents[2]

# Prebuilt-binary runtime Dockerfiles: the Rust binary is cross-compiled on the
# host with cargo-zigbuild (deploy.sh ensure_orchestrator_binary) and COPYed in
# per-arch — no in-image compilation. One Dockerfile per architecture.
BINARY_ORCHESTRATOR_DOCKERFILES = (
    "orchestrator-rs-amd64.Dockerfile",
    "orchestrator-rs-arm64.Dockerfile",
)

# Source Dockerfiles that still compile in-image (used by GitHub CI on native
# runners). Kept for the multi-arch CI build path.
SOURCE_ORCHESTRATOR_DOCKERFILES = ("orchestrator-rs.Dockerfile",)


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
