from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _section(content: str, start: str, end: str) -> str:
    return content[content.index(start) : content.index(end)]


def test_local_deploy_builds_core_images_before_running_migrations():
    deploy_script = (ROOT / "deploy/deploy.sh").read_text(encoding="utf-8")
    build_local_compose_images = _section(
        deploy_script,
        "build_local_compose_images() {",
        "wait_for_local_redis() {",
    )
    run_local_compose = _section(
        deploy_script,
        "run_local_compose() {",
        "run_local_doctor() {",
    )

    build_marker = "build_local_compose_images"
    migrations_marker = "run_local_migrations"
    run_marker = "compose_local_env --profile local-redis --profile rust-orchestrator --profile init run --rm db-init"

    assert "BUILD_BACKEND=true" in build_local_compose_images
    assert "BUILD_FRONTEND=true" in build_local_compose_images
    assert "BUILD_ORCHESTRATOR=true" in build_local_compose_images
    assert "BUILD_SKILLSPECTOR=true" in build_local_compose_images
    assert 'BASE_IMAGE_REGISTRY="$LOCAL_OFFICIAL_IMAGE_REGISTRY"' in build_local_compose_images
    assert "PUSH=false" in build_local_compose_images
    assert "build_all_images" in build_local_compose_images
    assert run_marker in deploy_script
    assert run_local_compose.index(build_marker) < run_local_compose.index(migrations_marker)


def test_local_deploy_avoids_compose_bake_up_build_path():
    deploy_script = (ROOT / "deploy/deploy.sh").read_text(encoding="utf-8")
    compose_local_env = _section(
        deploy_script,
        "compose_local_env() {",
        "sync_local_core_image_env() {",
    )
    run_local_migrations = _section(
        deploy_script,
        "run_local_migrations() {",
        "require_single_platform() {",
    )
    run_local_compose = _section(
        deploy_script,
        "run_local_compose() {",
        "run_local_doctor() {",
    )

    assert 'COMPOSE_BAKE="${COMPOSE_BAKE:-false}"' in compose_local_env
    assert "up -d --build" not in run_local_migrations
    assert "up -d --build" not in run_local_compose
    assert "up -d --no-build db redis skillspector" in run_local_migrations
    assert "compose_local_env" in run_local_migrations
    assert "compose_local_env --profile local-redis --profile rust-orchestrator build" not in run_local_migrations
    assert "compose_local_env --profile local-redis --profile rust-orchestrator build" not in run_local_compose
    assert "compose_local_env --profile local-redis --profile rust-orchestrator --profile init build" not in run_local_migrations
    assert "up -d --no-build" in run_local_compose


def test_local_deploy_syncs_script_built_images_into_compose_env():
    deploy_script = (ROOT / "deploy/deploy.sh").read_text(encoding="utf-8")
    sync_local_core_image_env = _section(
        deploy_script,
        "sync_local_core_image_env() {",
        "build_local_compose_images() {",
    )

    assert 'set_env_value "$deploy_env" "BACKEND_FULL_IMAGE"' in sync_local_core_image_env
    assert 'set_env_value "$deploy_env" "FRONTEND_FULL_IMAGE"' in sync_local_core_image_env
    assert 'set_env_value "$deploy_env" "ORCHESTRATOR_RS_FULL_IMAGE"' in sync_local_core_image_env
    assert 'set_env_value "$deploy_env" "SKILLSPECTOR_FULL_IMAGE"' in sync_local_core_image_env


def test_local_deploy_warns_when_default_sandbox_runtime_image_is_missing():
    deploy_script = (ROOT / "deploy/deploy.sh").read_text(encoding="utf-8")

    assert "warn_if_sandbox_runtime_image_missing()" in deploy_script
    assert 'docker image inspect "$sandbox_image"' in deploy_script
    assert "agent task execution will fail until it is built/pulled" in deploy_script

    run_local_compose = _section(
        deploy_script,
        "run_local_compose() {",
        "run_local_doctor() {",
    )
    run_local_doctor = _section(
        deploy_script,
        "run_local_doctor() {",
        "# 初始化 Docker Buildx",
    )
    assert 'warn_if_sandbox_runtime_image_missing "$SCRIPT_DIR/.env"' in run_local_compose
    assert 'warn_if_sandbox_runtime_image_missing "$SCRIPT_DIR/.env"' in run_local_doctor


def test_rust_orchestrator_compose_service_has_liveness_healthcheck():
    compose = (ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8")
    service = _section(compose, "  orchestrator-rs:", "  worker:")

    assert "healthcheck:" in service
    assert "/dev/tcp/127.0.0.1/9090" in service
    assert "start_period: 60s" in service


def test_agent_runtime_images_use_node_22_for_latest_cli_compatibility():
    runtime_dockerfiles = sorted((ROOT / "deploy/docker").glob("*.Dockerfile"))
    runtime_dockerfiles = [
        path
        for path in runtime_dockerfiles
        if path.name.startswith(("claudecode-", "codex-", "native-"))
    ]

    assert runtime_dockerfiles
    for dockerfile in runtime_dockerfiles:
        content = dockerfile.read_text(encoding="utf-8")
        assert "setup_20.x" not in content, dockerfile
        assert "setup_22.x" in content, dockerfile
