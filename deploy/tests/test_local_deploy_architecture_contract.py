from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SH = PROJECT_ROOT / "deploy" / "deploy.sh"
COMPOSE = PROJECT_ROOT / "deploy" / "docker-compose.yml"
ENV_EXAMPLE = PROJECT_ROOT / "deploy" / ".env.example"
DEPLOY_README = PROJECT_ROOT / "deploy" / "README.md"
INSTALL = PROJECT_ROOT / "INSTALL.md"
INSTALL_CN = PROJECT_ROOT / "INSTALL_CN.md"
DOCKER_DIR = PROJECT_ROOT / "deploy" / "docker"


def test_compose_defaults_use_multiarch_official_images() -> None:
    body = COMPOSE.read_text()

    assert "public.ecr.aws/docker/library/rust:1-bookworm" in body
    assert "public.ecr.aws/docker/library/debian:bookworm-slim" in body
    assert "public.ecr.aws/docker/library/postgres:15" in body
    assert "public.ecr.aws/docker/library/redis:alpine3.22" in body
    assert "${BASE_IMAGE_REGISTRY:-public.ecr.aws/docker/library/}" in body
    assert "swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/rust" not in body
    assert "rust:1.85-bookworm" not in body


def test_dockerfiles_do_not_pin_arch_specific_mirror_tags() -> None:
    for dockerfile in DOCKER_DIR.glob("*.Dockerfile"):
        body = dockerfile.read_text()
        assert "swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io" not in body
        assert "22.04-linuxarm64" not in body

    for dockerfile in [
        "claudecode-amd64.Dockerfile",
        "claudecode-arm64.Dockerfile",
        "codex-amd64.Dockerfile",
        "codex-arm64.Dockerfile",
        "native-amd64.Dockerfile",
        "native-arm64.Dockerfile",
    ]:
        body = (DOCKER_DIR / dockerfile).read_text()
        assert 'ARG BASE_IMAGE_REGISTRY="public.ecr.aws/docker/library/"' in body
        assert "FROM ${BASE_IMAGE_REGISTRY}ubuntu:22.04 AS base" in body


def test_python_backend_image_does_not_expose_removed_orchestrator_ports() -> None:
    backend = (DOCKER_DIR / "backend.Dockerfile").read_text()
    orchestrator = (DOCKER_DIR / "orchestrator-rs.Dockerfile").read_text()

    assert "EXPOSE 8000 8002" in backend
    assert "EXPOSE 8000 8001 8002 9090" not in backend
    assert "EXPOSE 9090" in orchestrator


def test_local_deploy_script_detects_docker_arch_and_preflights() -> None:
    body = DEPLOY_SH.read_text()

    assert "get_docker_platform()" in body
    assert "docker info --format '{{.Architecture}}'" in body
    assert "doctor|local|build|push|pull" in body
    assert "DOCKER_DEFAULT_PLATFORM\" \"$PLATFORMS\"" in body
    assert "--profile init run --rm db-init" in body
    assert "compose --profile local-redis --profile rust-orchestrator config >/dev/null" in body
    assert "git clone \"$SKILLSPECTOR_REPO_URL\" \"$DEFAULT_SKILLSPECTOR_SOURCE_PATH\"" in body
    assert "wait_for_local_redis()" in body
    assert "redis-cli ping" in body
    assert "LOCAL_REDIS_READY_TIMEOUT_SECONDS" in body
    assert "wait_for_local_redis\n\n        log_info \"运行数据库迁移...\"" in body


def test_image_lifecycle_includes_rust_orchestrator_and_skillspector() -> None:
    body = DEPLOY_SH.read_text()

    assert "ORCHESTRATOR_RS_IMAGE" in body
    assert "SKILLSPECTOR_IMAGE" in body
    assert "--orchestrator-only" in body
    assert "--skillspector-only" in body
    assert "BUILD_ORCHESTRATOR" in body
    assert "BUILD_SKILLSPECTOR" in body
    assert "ORCHESTRATOR_RS_FULL_IMAGE" in body
    assert "SKILLSPECTOR_FULL_IMAGE" in body
    assert "docker/orchestrator-rs.Dockerfile" in body
    assert "docker/skillspector-service.Dockerfile" in body
    assert "--build-context\" \"skillspector=$skillspector_source_path" in body
    assert "PULL_ORCHESTRATOR" in body
    assert "PULL_SKILLSPECTOR" in body


def test_pull_syncs_compose_env_to_pulled_images() -> None:
    body = DEPLOY_SH.read_text()

    assert 'local deploy_env="$SCRIPT_DIR/.env"' in body
    assert 'ensure_env_file "$deploy_env" "$SCRIPT_DIR/.env.example"' in body
    assert 'set_env_value "$deploy_env" "BACKEND_FULL_IMAGE" "$BACKEND_FULL_IMAGE"' in body
    assert 'set_env_value "$deploy_env" "FRONTEND_FULL_IMAGE" "$FRONTEND_FULL_IMAGE"' in body
    assert 'set_env_value "$deploy_env" "ORCHESTRATOR_RS_FULL_IMAGE" "$ORCHESTRATOR_RS_FULL_IMAGE"' in body
    assert 'set_env_value "$deploy_env" "SKILLSPECTOR_FULL_IMAGE" "$SKILLSPECTOR_FULL_IMAGE"' in body
    assert 'set_env_value "$deploy_env" "JOYSAFETER_SANDBOX_IMAGE" "$CLAUDECODE_FULL_IMAGE"' in body
    assert 'set_env_value "$deploy_env" "JOYSAFETER_IMAGE_CLAUDE" "$CLAUDECODE_FULL_IMAGE"' in body
    assert 'set_env_value "$deploy_env" "JOYSAFETER_IMAGE_CODEX" "$CODEX_FULL_IMAGE"' in body
    assert 'set_env_value "$deploy_env" "JOYSAFETER_IMAGE_NATIVE" "$NATIVE_FULL_IMAGE"' in body


def test_image_lifecycle_success_paths_return_zero_after_conditional_output() -> None:
    body = DEPLOY_SH.read_text()

    assert 'log_info "镜像未推送，使用 push 命令推送到仓库"\n        if [ "$USE_BUILDX" = true ]' in body
    assert 'log_info "镜像未推送，使用 push 命令推送到仓库"' in body
    assert 'log_info "已同步 deploy/.env 中的镜像变量，后续 compose up --no-build 会使用本次拉取的镜像"' in body
    assert body.index('log_info "镜像未推送，使用 push 命令推送到仓库"') < body.index("    return 0\n}\n\n# 拉取镜像")
    assert body.index('log_info "已同步 deploy/.env 中的镜像变量') < body.rindex("    return 0\n}\n\n# 主函数")


def test_runtime_multiarch_push_fails_before_partial_core_image_push() -> None:
    body = DEPLOY_SH.read_text()

    preflight = "避免核心镜像先推送后才失败"
    first_build = '# 初始化 Buildx（如果需要）'
    assert preflight in body
    assert body.index(preflight) < body.index(first_build)


def test_env_example_documents_local_multiarch_defaults() -> None:
    body = ENV_EXAMPLE.read_text()

    assert "BASE_IMAGE_REGISTRY=public.ecr.aws/docker/library/" in body
    assert "RUST_IMAGE=public.ecr.aws/docker/library/rust:1-bookworm" in body
    assert "RUNTIME_IMAGE=public.ecr.aws/docker/library/debian:bookworm-slim" in body
    assert "ORCHESTRATOR_RS_FULL_IMAGE=joysafeter-orchestrator-rs:latest" in body
    assert "SKILLSPECTOR_FULL_IMAGE=joysafeter-skillspector:latest" in body
    assert "JOYSAFETER_SANDBOX_IMAGE=joysafeter-claudecode:latest" in body
    assert "JOYSAFETER_IMAGE_CLAUDE=joysafeter-claudecode:latest" in body
    assert "JOYSAFETER_IMAGE_CODEX=joysafeter-codex:latest" in body
    assert "JOYSAFETER_IMAGE_NATIVE=joysafeter-native:latest" in body
    assert "SKILLSPECTOR_SOURCE_PATH=../.deps/SkillSpector" in body
    assert "ORCHESTRATOR_HEALTH_BIND_HOST" not in body
    assert "ORCHESTRATOR_HEALTH_PORT_HOST" not in body
    assert "Rust orchestrator 当前只暴露 gRPC 9090" in body


def test_docs_separate_local_and_cloud_redis_migration_commands() -> None:
    cloud_migration = "docker compose --profile rust-orchestrator --profile init run --rm db-init"
    local_migration = "docker compose --profile local-redis --profile rust-orchestrator --profile init run --rm db-init"

    for doc in (DEPLOY_README, INSTALL, INSTALL_CN):
        body = doc.read_text()
        assert local_migration in body
        assert cloud_migration in body
