import json
import sys
from pathlib import Path

import pytest

from forgelab.sdk.agent import ForgeAgent

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _hardware_payload():
    return json.loads((_EXAMPLES / "hardware" / "blinky.forge.json").read_text())


class _FakeBlock:
    def __init__(self, payload):
        self.type = "tool_use"
        self.name = "emit_forgelab"
        self.input = payload


class _FakeMessage:
    def __init__(self, blocks):
        self.content = blocks


class _FakeMessages:
    def __init__(self, payload, captured):
        self._payload = payload
        self._captured = captured

    def create(self, **kwargs):
        self._captured.update(kwargs)
        return _FakeMessage([_FakeBlock(self._payload)])


class _FakeClient:
    def __init__(self, payload, captured):
        self.messages = _FakeMessages(payload, captured)


def test_design_returns_validated_document_and_forces_tool():
    captured: dict = {}
    agent = ForgeAgent(client=_FakeClient(_hardware_payload(), captured))
    document = agent.design("a blinky board", domain="hardware")

    assert document.domain.value == "hardware"
    assert captured["model"] == "claude-opus-4-8"
    assert captured["tool_choice"] == {"type": "tool", "name": "emit_forgelab"}
    assert captured["tools"][0]["name"] == "emit_forgelab"
    assert captured["tools"][0]["input_schema"]["properties"]["domain"] == {"const": "hardware"}


def test_model_is_configurable():
    captured: dict = {}
    agent = ForgeAgent(model="claude-sonnet-4-6", client=_FakeClient(_hardware_payload(), captured))
    agent.design("a blinky board", domain="hardware")
    assert captured["model"] == "claude-sonnet-4-6"


def test_missing_anthropic_raises_friendly(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)
    with pytest.raises(ImportError, match=r"forgelab\[agent\]"):
        ForgeAgent()
