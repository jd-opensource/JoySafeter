from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

REPO_ROOT = Path(__file__).resolve().parents[2]
REBIN_FILES = (
    "codex-rebin.Dockerfile",
    "orchestrator-rs-rebin.Dockerfile",
    "sandbox-runner-rebin.Dockerfile",
)
SOURCE_ORCHESTRATOR_DOCKERFILES = (
    "orchestrator-rs.Dockerfile",
    "orchestrator-rs-jd.Dockerfile",
)


@pytest.mark.parametrize("filename", REBIN_FILES)
def test_rebin_dockerfile_parameterizes_rust_target(filename: str) -> None:
    source = (REPO_ROOT / "deploy/docker" / filename).read_text()

    assert "ARG TARGET_TRIPLE=" in source
    assert "target/${TARGET_TRIPLE}/release/" in source
    assert "target/x86_64-unknown-linux-gnu/release/" not in source


def test_orchestrator_rebin_allows_pinning_the_base_image() -> None:
    source = (
        REPO_ROOT / "deploy/docker/orchestrator-rs-rebin.Dockerfile"
    ).read_text()

    assert "ARG BASE=" in source
    assert "FROM ${BASE}" in source


def test_codex_rebin_restores_codex_entrypoint() -> None:
    source = (REPO_ROOT / "deploy/docker/codex-rebin.Dockerfile").read_text()

    assert 'ENTRYPOINT ["/usr/local/bin/codex-entrypoint.sh"]' in source


@pytest.mark.parametrize("filename", SOURCE_ORCHESTRATOR_DOCKERFILES)
def test_orchestrator_source_dockerfile_copies_compile_time_inputs(filename: str) -> None:
    source = (REPO_ROOT / "deploy/docker" / filename).read_text()

    assert "COPY proto ./proto" in source
    assert "COPY backend/app/joysafeter_orchestrator_rs ./backend/app/joysafeter_orchestrator_rs" in source
    assert "COPY backend/config ./backend/config" in source
    build_command = next(
        marker for marker in ("RUN cargo build", "RUN cargo zigbuild") if marker in source
    )
    assert source.index("COPY backend/config ./backend/config") < source.index(build_command)


@pytest.mark.parametrize(
    "filename",
    (*SOURCE_ORCHESTRATOR_DOCKERFILES, "orchestrator-rs-binary.Dockerfile"),
)
def test_orchestrator_dockerfiles_do_not_export_dead_global_enable_switch(filename: str) -> None:
    source = (REPO_ROOT / "deploy/docker" / filename).read_text()

    assert "JOYSAFETER_ENABLED" not in source
