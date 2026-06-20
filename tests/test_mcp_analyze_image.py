"""analyze_image: photo -> ForgeLab document skeleton via the vision API."""

import json

import pytest

from forgelab.mcp import tools
from forgelab.spec import SPEC_VERSION

# A 1x1 transparent PNG.
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000154a24f8f0000000049454e44ae426082"
)

_DOC = {
    "forgelab_version": SPEC_VERSION,
    "domain": "hardware",
    "meta": {"name": "from-photo", "generator": "forgelab-vision"},
    "nodes": [{"id": "U1-estimated", "type": "component"}],
}


class _TextBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class _FakeMessage:
    def __init__(self, text):
        self.content = [_TextBlock(text)]


class _FakeMessages:
    def __init__(self, text):
        self._text = text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeMessage(self._text)


class _FakeClient:
    def __init__(self, text):
        self.messages = _FakeMessages(text)


def _image(tmp_path, name="board.png", data=_PNG):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def _install_client(monkeypatch, text):
    client = _FakeClient(text)
    monkeypatch.setattr(tools, "_make_vision_client", lambda: client)
    return client


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #
def test_analyze_image_is_registered():
    from forgelab.mcp.server import _TOOLS

    assert tools.analyze_image in _TOOLS


def test_generation_status_reports_image_analysis(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(tools, "_agent_extra_installed", lambda: True)
    status = tools.generation_status()
    assert status["analyze_image"] is True
    assert status["generate_document"] is True

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    down = tools.generation_status()
    assert down["analyze_image"] is False


# --------------------------------------------------------------------------- #
# error paths
# --------------------------------------------------------------------------- #
def test_analyze_image_missing_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def _boom():
        raise AssertionError("client must not be built without a key")

    monkeypatch.setattr(tools, "_make_vision_client", _boom)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY is not set"):
        tools.analyze_image(_image(tmp_path), "hardware")


def test_analyze_image_unknown_domain(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    with pytest.raises(ValueError, match="unknown domain"):
        tools.analyze_image(_image(tmp_path), "not-a-domain")


def test_analyze_image_missing_agent_extra(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    def _no_extra():
        raise ImportError("no anthropic")

    monkeypatch.setattr(tools, "_make_vision_client", _no_extra)
    with pytest.raises(ValueError, match="agent extra"):
        tools.analyze_image(_image(tmp_path), "hardware")


def test_analyze_image_unsupported_image_type(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    with pytest.raises(ValueError, match="unsupported image type"):
        tools.analyze_image(_image(tmp_path, name="board.bmp"), "hardware")


# --------------------------------------------------------------------------- #
# happy path with a mocked vision response
# --------------------------------------------------------------------------- #
def test_analyze_image_returns_document_skeleton(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    client = _install_client(monkeypatch, json.dumps(_DOC))

    result = tools.analyze_image(_image(tmp_path), "hardware", hints="100x60mm, 4-layer")

    assert result == _DOC
    # The image and the hints both reached the API call.
    (call,) = client.messages.calls
    assert call["model"] == "claude-sonnet-4-6"
    content = call["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/png"
    assert "100x60mm, 4-layer" in content[1]["text"]


def test_analyze_image_tolerates_code_fences(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    fenced = "Here is the document:\n```json\n" + json.dumps(_DOC) + "\n```"
    _install_client(monkeypatch, fenced)
    result = tools.analyze_image(_image(tmp_path), "hardware")
    assert result["nodes"][0]["id"] == "U1-estimated"


def test_analyze_image_non_json_response_errors(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    _install_client(monkeypatch, "I could not analyze that image, sorry.")
    with pytest.raises(ValueError, match="did not return valid JSON"):
        tools.analyze_image(_image(tmp_path), "hardware")
