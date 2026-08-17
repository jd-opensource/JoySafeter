from app.joysafeter_domain.llm.anthropic_auth import (
    AUTH_SCHEME_AUTO,
    AUTH_SCHEME_BEARER,
    AUTH_SCHEME_XAPIKEY,
    is_official_anthropic,
    normalize_anthropic_auth,
    resolve_auth_scheme,
)


def test_official_host_detection():
    assert is_official_anthropic("https://api.anthropic.com") is True
    assert is_official_anthropic("https://api.anthropic.com/") is True
    assert is_official_anthropic("") is True  # 空 = 走官方默认端点
    assert is_official_anthropic("http://ai-api.jdcloud.com/anthropic") is False


def test_resolve_auto_uses_host():
    assert resolve_auth_scheme("https://api.anthropic.com", AUTH_SCHEME_AUTO) == AUTH_SCHEME_XAPIKEY
    assert resolve_auth_scheme("http://ai-api.jdcloud.com/anthropic", AUTH_SCHEME_AUTO) == AUTH_SCHEME_BEARER


def test_resolve_manual_overrides_host():
    # 手动指定压过 host 判定
    assert resolve_auth_scheme("https://api.anthropic.com", AUTH_SCHEME_BEARER) == AUTH_SCHEME_BEARER
    assert resolve_auth_scheme("http://ai-api.jdcloud.com/anthropic", AUTH_SCHEME_XAPIKEY) == AUTH_SCHEME_XAPIKEY


def test_normalize_bearer_moves_key_to_auth_token():
    out = normalize_anthropic_auth(
        {"ANTHROPIC_API_KEY": "pk-secret", "ANTHROPIC_BASE_URL": "http://ai-api.jdcloud.com/anthropic", "ANTHROPIC_MODEL": "m"},
        AUTH_SCHEME_AUTO,
    )
    assert out["ANTHROPIC_AUTH_TOKEN"] == "pk-secret"
    assert "ANTHROPIC_API_KEY" not in out
    assert out["ANTHROPIC_MODEL"] == "m"


def test_normalize_xapikey_keeps_api_key():
    out = normalize_anthropic_auth(
        {"ANTHROPIC_API_KEY": "sk-ant-x", "ANTHROPIC_BASE_URL": "https://api.anthropic.com"},
        AUTH_SCHEME_AUTO,
    )
    assert out["ANTHROPIC_API_KEY"] == "sk-ant-x"
    assert "ANTHROPIC_AUTH_TOKEN" not in out


def test_normalize_is_mutually_exclusive_from_either_carrier():
    # key 可能来自任一字段(编辑回填场景),结果永远只留一个
    out = normalize_anthropic_auth(
        {"ANTHROPIC_AUTH_TOKEN": "tok", "ANTHROPIC_BASE_URL": "http://gw.example.com"},
        AUTH_SCHEME_AUTO,
    )
    assert out["ANTHROPIC_AUTH_TOKEN"] == "tok"
    assert "ANTHROPIC_API_KEY" not in out


def test_normalize_blank_key_leaves_both_absent():
    out = normalize_anthropic_auth({"ANTHROPIC_BASE_URL": "https://api.anthropic.com"}, AUTH_SCHEME_AUTO)
    assert "ANTHROPIC_API_KEY" not in out
    assert "ANTHROPIC_AUTH_TOKEN" not in out
