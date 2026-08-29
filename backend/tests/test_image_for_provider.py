import os

import pytest

# The shared settings module instantiates a module-level ``Settings()`` at
# import time, which requires SECRET_KEY. Set a dummy value before importing so
# this import-safe unit test can run without the full CI secret environment.
os.environ.setdefault("SECRET_KEY", "test-secret")

from app.joysafeter_shared.config.settings import JoySafeterConfig  # noqa: E402

pytestmark = pytest.mark.no_db


def test_image_for_provider_pi():
    cfg = JoySafeterConfig(image_pi="joysafeter-pi:latest")
    assert cfg.image_for_provider("pi") == "joysafeter-pi:latest"


@pytest.mark.parametrize(
    ("engine_kind", "env_var"),
    (
        ("codex", "JOYSAFETER_IMAGE_CODEX"),
        ("native", "JOYSAFETER_IMAGE_NATIVE"),
        ("pi", "JOYSAFETER_IMAGE_PI"),
    ),
)
def test_image_for_provider_rejects_missing_engine_image(engine_kind: str, env_var: str):
    cfg = JoySafeterConfig(
        image_codex="",
        image_native="",
        image_pi="",
        image_claude="joysafeter-claudecode:latest",
        sandbox_image="joysafeter-default:latest",
    )

    with pytest.raises(ValueError, match=env_var):
        cfg.image_for_provider(engine_kind)


def test_image_for_provider_claude_keeps_explicit_legacy_default():
    cfg = JoySafeterConfig(
        image_claude="",
        sandbox_image="joysafeter-default:latest",
    )

    assert cfg.image_for_provider("claude") == "joysafeter-default:latest"
