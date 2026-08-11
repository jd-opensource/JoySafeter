"""
Tests for the MiniMax provider — schema, predefined models, region/protocol
base-URL resolution, and create_model_instance wiring.

These tests import the provider module directly (bypassing the DB-backed
app.core package init) so they run without a database.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

PROVIDERS_DIR = Path(__file__).resolve().parents[1] / "app" / "core" / "model" / "providers"


def _load_providers():
    """Load the provider modules directly, stubbing out the DB-backed app.core package init."""
    for name in ["app", "app.core", "app.core.model", "app.core.model.providers"]:
        if name not in sys.modules:
            m = types.ModuleType(name)
            m.__path__ = []
            sys.modules[name] = m
    sys.modules["app.core.model.providers"].__path__ = [str(PROVIDERS_DIR)]

    def _load(fullname, filename):
        spec = importlib.util.spec_from_file_location(fullname, PROVIDERS_DIR / filename)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[fullname] = mod
        spec.loader.exec_module(mod)
        return mod

    base = _load("app.core.model.providers.base", "base.py")
    _load("app.core.model.providers.OpenaiApiCompatible", "OpenaiApiCompatible.py")
    minimax_mod = _load("app.core.model.providers.MiniMax", "MiniMax.py")
    return base, minimax_mod


@pytest.fixture(scope="module")
def provider():
    _, minimax_mod = _load_providers()
    return minimax_mod.MiniMaxProvider()


def test_provider_identity(provider):
    assert provider.provider_name == "minimax"
    assert provider.display_name == "MiniMax"
    assert provider.provider_type == "system"


def test_credential_schema(provider):
    schema = provider.get_credential_schema()
    assert schema["required"] == ["api_key"]
    props = schema["properties"]
    assert set(props) == {"api_key", "region", "protocol_type", "base_url"}
    assert props["region"]["enum"] == ["global_en", "cn_zh"]
    assert props["protocol_type"]["enum"] == ["openai", "anthropic"]
    assert props["region"]["default"] == "global_en"
    assert props["protocol_type"]["default"] == "openai"


def test_predefined_models(provider):
    base, _ = _load_providers()
    models = provider.get_model_list(base.ModelType.CHAT)
    assert models == [
        {
            "name": "MiniMax-M3",
            "display_name": "MiniMax M3",
            "description": "MiniMax flagship multimodal model with a 1M context window, adaptive thinking, and prompt caching",
            "context_window": 1_000_000,
            "pricing_usd_per_million_tokens": {
                "input": 0.6,
                "output": 2.4,
                "cache_read": 0.12,
                "cache_write": None,
            },
            "input_modalities": ["text", "image", "video"],
            "thinking": ["adaptive", "disabled"],
            "is_available": True,
        },
        {
            "name": "MiniMax-M2.7",
            "display_name": "MiniMax M2.7",
            "description": "MiniMax text model with always-on thinking and a 204K context window",
            "context_window": 204_800,
            "pricing_usd_per_million_tokens": {
                "input": 0.3,
                "output": 1.2,
                "cache_read": 0.06,
                "cache_write": 0.375,
            },
            "input_modalities": ["text"],
            "thinking": ["always_on"],
            "is_available": True,
        },
    ]


def test_create_openai_global_default_base_url(provider):
    base, _ = _load_providers()
    inst = provider.create_model_instance(
        "MiniMax-M3", base.ModelType.CHAT, {"api_key": "k", "protocol_type": "openai"}
    )
    assert inst.openai_api_base == "https://api.minimax.io/v1"


def test_create_openai_china_region_base_url(provider):
    base, _ = _load_providers()
    inst = provider.create_model_instance(
        "MiniMax-M3", base.ModelType.CHAT, {"api_key": "k", "protocol_type": "openai", "region": "cn_zh"}
    )
    assert inst.openai_api_base == "https://api.minimaxi.com/v1"


def test_create_anthropic_global_default_base_url(provider):
    base, _ = _load_providers()
    inst = provider.create_model_instance(
        "MiniMax-M3", base.ModelType.CHAT, {"api_key": "k", "protocol_type": "anthropic"}
    )
    assert inst.anthropic_api_url == "https://api.minimax.io/anthropic"


def test_create_anthropic_china_region_base_url(provider):
    base, _ = _load_providers()
    inst = provider.create_model_instance(
        "MiniMax-M3", base.ModelType.CHAT, {"api_key": "k", "protocol_type": "anthropic", "region": "cn_zh"}
    )
    assert inst.anthropic_api_url == "https://api.minimaxi.com/anthropic"


def test_create_openai_explicit_base_url_override(provider):
    base, _ = _load_providers()
    inst = provider.create_model_instance(
        "MiniMax-M3",
        base.ModelType.CHAT,
        {"api_key": "k", "protocol_type": "openai", "base_url": "https://custom.example/v1"},
    )
    assert inst.openai_api_base == "https://custom.example/v1"


def test_create_unknown_region_falls_back_to_global(provider):
    base, _ = _load_providers()
    inst = provider.create_model_instance("MiniMax-M3", base.ModelType.CHAT, {"api_key": "k", "region": "mars"})
    assert inst.openai_api_base == "https://api.minimax.io/v1"


def test_create_unsupported_model_type_raises(provider):
    base, _ = _load_providers()
    with pytest.raises(ValueError):
        provider.create_model_instance("MiniMax-M3", base.ModelType.EMBEDDING, {"api_key": "k"})


def test_create_missing_api_key_raises(provider):
    base, _ = _load_providers()
    with pytest.raises(ValueError):
        provider.create_model_instance("MiniMax-M3", base.ModelType.CHAT, {"api_key": ""})


def test_get_predefined_models(provider):
    base, _ = _load_providers()
    models = provider.get_predefined_models(base.ModelType.CHAT)
    assert [m["name"] for m in models] == ["MiniMax-M3", "MiniMax-M2.7"]
    assert provider.get_predefined_models(base.ModelType.EMBEDDING) == []
