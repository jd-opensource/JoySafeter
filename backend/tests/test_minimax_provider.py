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
    assert props["region"]["enum"] == ["global", "cn"]
    assert props["protocol_type"]["enum"] == ["openai", "anthropic"]
    assert props["region"]["default"] == "global"
    assert props["protocol_type"]["default"] == "openai"


def test_predefined_models(provider):
    base, _ = _load_providers()
    models = provider.get_model_list(base.ModelType.CHAT)
    names = [m["name"] for m in models]
    assert names == ["MiniMax-M3", "MiniMax-M2.7"]
    for m in models:
        assert m["is_available"] is True
        assert m["display_name"]
        assert m["description"]


def test_create_openai_global_default_base_url(provider):
    base, _ = _load_providers()
    inst = provider.create_model_instance(
        "MiniMax-M3", base.ModelType.CHAT, {"api_key": "k", "protocol_type": "openai"}
    )
    assert inst.openai_api_base == "https://api.minimax.io/v1"


def test_create_openai_china_region_base_url(provider):
    base, _ = _load_providers()
    inst = provider.create_model_instance(
        "MiniMax-M3", base.ModelType.CHAT, {"api_key": "k", "protocol_type": "openai", "region": "cn"}
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
        "MiniMax-M3", base.ModelType.CHAT, {"api_key": "k", "protocol_type": "anthropic", "region": "cn"}
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
