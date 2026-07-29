from __future__ import annotations

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SH = PROJECT_ROOT / "deploy" / "deploy.sh"
DOCKER_DIR = PROJECT_ROOT / "deploy" / "docker"


def _deploy_runner_targets() -> dict[str, str]:
    deploy_body = DEPLOY_SH.read_text()
    targets = dict(re.findall(r"(linux/(?:amd64|arm64)\))\s*echo \"([^\"]+)\"", deploy_body))
    return {platform.rstrip(")"): target for platform, target in targets.items()}


def test_runtime_dockerfiles_copy_runner_binary_built_by_deploy_script() -> None:
    targets = _deploy_runner_targets()

    assert targets == {
        "linux/amd64": "x86_64-unknown-linux-gnu",
        "linux/arm64": "aarch64-unknown-linux-gnu",
    }

    expected_by_suffix = {
        "amd64": targets["linux/amd64"],
        "arm64": targets["linux/arm64"],
    }

    for dockerfile in DOCKER_DIR.glob("*-*.Dockerfile"):
        suffix = dockerfile.stem.rsplit("-", 1)[-1]
        if suffix not in expected_by_suffix:
            continue

        body = dockerfile.read_text()
        expected_copy = f"COPY target/{expected_by_suffix[suffix]}/release/joysafeter-runner "
        assert expected_copy in body, f"{dockerfile.name} must copy the runner target built by deploy.sh"


def test_deploy_script_builds_every_runtime_engine_image() -> None:
    body = DEPLOY_SH.read_text()
    runtime_cases = {
        (engine, platform): dockerfile
        for engine, platform, dockerfile in re.findall(
            r"(claudecode|codex|native):linux/(amd64|arm64)\) echo \"\$SCRIPT_DIR/docker/([^\"]+)\"",
            body,
        )
    }

    assert runtime_cases == {
        ("claudecode", "amd64"): "claudecode-amd64.Dockerfile",
        ("claudecode", "arm64"): "claudecode-arm64.Dockerfile",
        ("codex", "amd64"): "codex-amd64.Dockerfile",
        ("codex", "arm64"): "codex-arm64.Dockerfile",
        ("native", "amd64"): "native-amd64.Dockerfile",
        ("native", "arm64"): "native-arm64.Dockerfile",
    }
    assert "--native-only" in body
    assert 'BUILD_NATIVE=true' in body
    assert 'build_runtime_image "Native 运行镜像" "native" "$NATIVE_FULL_IMAGE"' in body


def test_runner_runtime_dockerfiles_use_token_scrubbing_entrypoints() -> None:
    expected_entrypoints = {
        "claudecode-amd64.Dockerfile": "runner-entrypoint.sh",
        "claudecode-arm64.Dockerfile": "runner-entrypoint.sh",
        "native-amd64.Dockerfile": "runner-entrypoint.sh",
        "native-arm64.Dockerfile": "runner-entrypoint.sh",
        "codex-amd64.Dockerfile": "codex-entrypoint.sh",
        "codex-arm64.Dockerfile": "codex-entrypoint.sh",
    }

    for filename, entrypoint in expected_entrypoints.items():
        body = (DOCKER_DIR / filename).read_text()

        assert f"COPY deploy/docker/{entrypoint} " in body
        assert f'ENTRYPOINT ["{entrypoint}"]' in body
        assert 'ENTRYPOINT ["joysafeter-runner"]' not in body
