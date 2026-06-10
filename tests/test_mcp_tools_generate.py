import pytest

from forgelab.mcp import tools
from forgelab.sdk import load
from forgelab.spec import SPEC_VERSION

_DOC = {
    "forgelab_version": SPEC_VERSION,
    "domain": "hardware",
    "meta": {"name": "blinky", "generator": "forgelab-sdk"},
    "nodes": [{"id": "r1", "type": "component"}],
}


class _FakeAgent:
    def __init__(self):
        self.calls = []

    def design(self, prompt, *, domain):
        self.calls.append((prompt, domain))
        return load(_DOC)


def test_generate_missing_api_key_is_graceful(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    called = False

    def _boom(model):
        nonlocal called
        called = True
        raise AssertionError("agent must not be constructed without a key")

    monkeypatch.setattr(tools, "_make_agent", _boom)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY is not set"):
        tools.generate_document("a blinky board", "hardware")
    assert called is False


def test_generate_happy_path_with_fake_agent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    fake = _FakeAgent()
    monkeypatch.setattr(tools, "_make_agent", lambda model: fake)
    result = tools.generate_document("a blinky board", "hardware", model="claude-x")
    assert result["domain"] == "hardware"
    assert fake.calls == [("a blinky board", "hardware")]


def test_generate_missing_agent_extra_is_graceful(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    def _no_extra(model):
        raise ImportError("no anthropic")

    monkeypatch.setattr(tools, "_make_agent", _no_extra)
    with pytest.raises(ValueError, match="agent extra"):
        tools.generate_document("a blinky board", "hardware")
