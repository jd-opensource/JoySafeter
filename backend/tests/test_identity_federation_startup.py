import pytest

from app.joysafeter_api import startup as startup_module
from app.joysafeter_identity_federation.bootstrap import (
    get_identity_federation_configuration,
    initialize_identity_federation_configuration,
)
from app.joysafeter_identity_federation.domain.errors import (
    ConfigurationIssue,
    FederationConfigurationError,
)
from app.joysafeter_shared.config.settings import settings


def _configure_empty_federation(monkeypatch, tmp_path) -> None:
    path = tmp_path / "providers.yaml"
    path.write_text(
        """
version: 1
providers: {}
settings:
  default_redirect_url: /managed/quickstart
  allow_registration: true
  auto_link_by_email: true
""".strip()
    )
    monkeypatch.setattr(settings, "identity_federation_config_path", str(path))
    monkeypatch.setattr(settings, "identity_federation_providers", "")
    monkeypatch.setattr(settings, "identity_federation_login_mode", "chooser")


@pytest.mark.no_db
def test_initialize_caches_one_immutable_configuration(monkeypatch, tmp_path) -> None:
    _configure_empty_federation(monkeypatch, tmp_path)

    first = initialize_identity_federation_configuration(force=True)
    second = get_identity_federation_configuration()

    assert second is first
    assert first.registry.list_public() == ()


@pytest.mark.no_db
def test_initialize_propagates_configuration_error(monkeypatch, tmp_path) -> None:
    path = tmp_path / "providers.yaml"
    path.write_text("providers: {jd: {protocol: unknown}}")
    monkeypatch.setattr(settings, "identity_federation_config_path", str(path))
    monkeypatch.setattr(settings, "identity_federation_providers", "jd")

    with pytest.raises(FederationConfigurationError):
        initialize_identity_federation_configuration(force=True)


@pytest.mark.asyncio
@pytest.mark.no_db
async def test_api_startup_does_not_swallow_federation_configuration_error(monkeypatch) -> None:
    error = FederationConfigurationError(
        [ConfigurationIssue("jd", "client_secret", "FEDERATION_ENV_UNRESOLVED", "JD_CLIENT_SECRET is unset")]
    )

    def _raise() -> None:
        raise error

    monkeypatch.setattr(startup_module, "initialize_identity_federation_configuration", _raise)

    with pytest.raises(FederationConfigurationError) as exc_info:
        await startup_module.run_api_startup()

    assert exc_info.value is error
