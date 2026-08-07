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


def test_image_for_provider_pi_no_fallback_to_other_engine_image():
    # pi must NOT fall back to another engine's image; only the shared
    # sandbox_image default when image_pi is unset.
    cfg = JoySafeterConfig(
        image_pi="",
        image_claude="joysafeter-claudecode:latest",
        sandbox_image="joysafeter-default:latest",
    )
    assert cfg.image_for_provider("pi") == "joysafeter-default:latest"
