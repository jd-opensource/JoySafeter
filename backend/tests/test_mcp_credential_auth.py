from __future__ import annotations

import pytest

from app.joysafeter_domain.credentials.policies import (
    CredentialPolicyError,
    CredentialPolicyErrorCode,
    canonicalize_mcp_auth_scheme,
    validate_mcp_credential_material,
)
from app.joysafeter_domain.credentials.types import CredentialAuthScheme, canonicalize_auth_scheme

pytestmark = pytest.mark.no_db


@pytest.mark.parametrize(
    "raw",
    [
        "bearer",
        "api_key",
        "oauth",
        "mcp_oauth",
    ],
)
def test_removed_mcp_auth_aliases_are_rejected(raw: str) -> None:
    if raw in {"bearer", "api_key"}:
        canonicalize_auth_scheme(raw)
        with pytest.raises(ValueError, match="unsupported credential auth scheme"):
            canonicalize_mcp_auth_scheme(raw)
    else:
        assert canonicalize_auth_scheme(raw) is CredentialAuthScheme.OAUTH2_LEGACY_DISABLED
        with pytest.raises(CredentialPolicyError) as exc:
            canonicalize_mcp_auth_scheme(raw)
        assert exc.value.code is CredentialPolicyErrorCode.UNSUPPORTED_SCHEME


@pytest.mark.parametrize("raw", ["auto", "basic", ""])
def test_unknown_mcp_auth_scheme_is_rejected(raw: str) -> None:
    with pytest.raises(ValueError, match="unsupported credential auth scheme"):
        canonicalize_mcp_auth_scheme(raw)


@pytest.mark.parametrize(
    ("scheme", "material", "expected"),
    [
        (
            CredentialAuthScheme.STATIC_BEARER,
            {"token_value": " bearer-secret "},
            {"token_value": "bearer-secret"},
        ),
        (
            CredentialAuthScheme.HEADER_API_KEY,
            {"token_value": "api-secret"},
            {"token_value": "api-secret", "header_name": "X-Api-Key"},
        ),
        (
            CredentialAuthScheme.HEADER_API_KEY,
            {"token_value": "api-secret", "header_name": "X-Corp-Key"},
            {"token_value": "api-secret", "header_name": "X-Corp-Key"},
        ),
        (
            CredentialAuthScheme.CUSTOM_HEADER,
            {
                "token_value": "custom-secret",
                "header_name": "X-Service-Authorization",
                "value_prefix": "Token ",
            },
            {
                "token_value": "custom-secret",
                "header_name": "X-Service-Authorization",
                "value_prefix": "Token ",
            },
        ),
    ],
)
def test_mcp_material_is_normalized_by_scheme(
    scheme: CredentialAuthScheme,
    material: dict[str, str],
    expected: dict[str, str],
) -> None:
    assert validate_mcp_credential_material(scheme, material) == expected


@pytest.mark.parametrize(
    ("scheme", "material", "field"),
    [
        (CredentialAuthScheme.STATIC_BEARER, {}, "data.token_value"),
        (CredentialAuthScheme.HEADER_API_KEY, {"token_value": ""}, "data.token_value"),
        (
            CredentialAuthScheme.CUSTOM_HEADER,
            {"token_value": "secret"},
            "data.header_name",
        ),
    ],
)
def test_mcp_material_requires_scheme_fields(
    scheme: CredentialAuthScheme,
    material: dict[str, str],
    field: str,
) -> None:
    with pytest.raises(CredentialPolicyError) as exc:
        validate_mcp_credential_material(scheme, material)

    assert exc.value.code is CredentialPolicyErrorCode.FIELD_MISSING
    assert exc.value.data == {"field": field}


@pytest.mark.parametrize(
    "header_name",
    [
        "Host",
        "content-length",
        "Transfer-Encoding",
        "Connection",
        "Upgrade",
        "TE",
        "Trailer",
        "Keep-Alive",
        "Proxy-Authenticate",
        "Proxy-Authorization",
        "X-Envoy-Original-Path",
        "Bad Header",
        "Bad:Header",
        "Bad\r\nInjected",
    ],
)
def test_mcp_material_rejects_unsafe_header_names(header_name: str) -> None:
    with pytest.raises(CredentialPolicyError) as exc:
        validate_mcp_credential_material(
            CredentialAuthScheme.CUSTOM_HEADER,
            {"token_value": "secret", "header_name": header_name},
        )

    assert exc.value.code is CredentialPolicyErrorCode.FIELD_INVALID
    assert exc.value.data == {"field": "data.header_name"}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("token_value", "secret\r\nX-Evil: yes"),
        ("token_value", "secret\x00suffix"),
        ("value_prefix", "Token\n"),
        ("value_prefix", "Token\x1f"),
    ],
)
def test_mcp_material_rejects_control_characters(field: str, value: str) -> None:
    material = {
        "token_value": "secret",
        "header_name": "X-Service-Authorization",
        "value_prefix": "Token ",
    }
    material[field] = value

    with pytest.raises(CredentialPolicyError) as exc:
        validate_mcp_credential_material(CredentialAuthScheme.CUSTOM_HEADER, material)

    assert exc.value.code is CredentialPolicyErrorCode.FIELD_INVALID
    assert exc.value.data == {"field": f"data.{field}"}


def test_mcp_material_rejects_fields_outside_selected_scheme() -> None:
    with pytest.raises(CredentialPolicyError) as exc:
        validate_mcp_credential_material(
            CredentialAuthScheme.STATIC_BEARER,
            {"token_value": "secret", "header_name": "X-Api-Key"},
        )

    assert exc.value.code is CredentialPolicyErrorCode.FIELD_INVALID
    assert exc.value.data == {"fields": ["header_name"]}
