from app.joysafeter_orchestrator.kernel import harness_input_builder as hib


def test_everos_base_url_defaults_to_compose_service(monkeypatch):
    monkeypatch.delenv("EVEROS_BASE_URL", raising=False)

    assert hib._resolve_everos_base_url() == "http://everos:8003"


def test_everos_base_url_can_be_overridden(monkeypatch):
    monkeypatch.setenv("EVEROS_BASE_URL", "http://memory.local:18003")

    assert hib._resolve_everos_base_url() == "http://memory.local:18003"


def test_append_everos_system_prompt_adds_service_note():
    base = "You are a security assistant."
    out = hib._append_everos_system_prompt(base, "http://everos:8003")

    assert "You are a security assistant." in out
    assert "EverOS memory service" in out
    assert "http://everos:8003" in out
