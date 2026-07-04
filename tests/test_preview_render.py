"""preview_render + critique_render: the render-critique loop primitives.

ForgeLab's threed domain stores baked triangle meshes (there are no separate
primitive_shape/csg_op node types to resolve), so preview_render draws
mesh/object nodes directly; objects carrying Blender modifier stacks render
their base meshes, since modifiers are evaluated by Blender itself.
"""

import json

import pytest

from forgelab.mcp import tools
from forgelab.spec import SPEC_VERSION

# A 1x1 transparent PNG (enough for the vision-call plumbing tests).
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000154a24f8f0000000049454e44ae426082"
)

_CRITIQUE = {
    "matches_intent": False,
    "score": 6,
    "issues": [
        {
            "severity": "critical",
            "description": "the greenhouse is too squat",
            "likely_cause": "roof object's Y scale is too small",
        }
    ],
    "suggested_changes": ["increase greenhouse height by ~30%"],
}


def _cube_positions():
    pts = []
    for x in (-1.0, 1.0):
        for y in (-1.0, 1.0):
            for z in (-1.0, 1.0):
                pts += [x, y, z]
    return pts


# 12 triangles over the 8 corners (indices bit-order: x*4 + y*2 + z).
_CUBE_INDICES = [
    0,
    1,
    3,
    0,
    3,
    2,  # x = -1
    4,
    6,
    7,
    4,
    7,
    5,  # x = +1
    0,
    4,
    5,
    0,
    5,
    1,  # y = -1
    2,
    3,
    7,
    2,
    7,
    6,  # y = +1
    0,
    2,
    6,
    0,
    6,
    4,  # z = -1
    1,
    5,
    7,
    1,
    7,
    3,  # z = +1
]


def _cube_doc(modifiers=None, with_mesh=True):
    object_props = {
        "name": "Cube",
        "transform": {
            "translation": [0.0, 1.0, 0.0],
            "rotation": [0.0, 0.0, 0.0, 1.0],
            "scale": [1.0, 1.0, 1.0],
        },
        "mesh": "mesh_cube" if with_mesh else "",
    }
    if modifiers:
        object_props["modifiers"] = modifiers
    nodes = [
        {"id": "scene", "type": "scene", "props": {"name": "S"}},
        {
            "id": "mat_red",
            "type": "material",
            "props": {"name": "Red", "base_color": [0.8, 0.1, 0.1, 1.0]},
        },
        {"id": "obj_cube", "type": "object", "props": object_props},
    ]
    if with_mesh:
        nodes.insert(
            2,
            {
                "id": "mesh_cube",
                "type": "mesh",
                "props": {
                    "name": "CubeMesh",
                    "primitives": [
                        {
                            "positions": _cube_positions(),
                            "indices": _CUBE_INDICES,
                            "material": "mat_red",
                        }
                    ],
                },
            },
        )
    return {
        "forgelab_version": SPEC_VERSION,
        "domain": "threed",
        "meta": {"name": "preview-test", "generator": "test"},
        "nodes": nodes,
    }


def _write_doc(tmp_path, doc, name="scene.forge.json"):
    (tmp_path / name).write_text(json.dumps(doc))
    return name


# ------------------------------------------------------------- preview_render


def test_preview_render_cube_produces_png_with_correct_triangle_count(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGELAB_OUTPUT_DIR", str(tmp_path))
    src = _write_doc(tmp_path, _cube_doc())
    result = tools.preview_render(src, "preview.png")
    assert result["rendered"] is True
    assert result["triangle_count"] == 12
    assert result["views"] == ["front-3/4", "side", "rear-3/4"]
    data = (tmp_path / "preview.png").read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(data) > 5000  # a real multi-panel figure, not a stub


def test_preview_render_object_with_modifier_stack_renders_base_mesh(tmp_path, monkeypatch):
    # Modifiers (incl. boolean) are procedural Blender-side geometry; the
    # preview draws the baked base mesh and must not crash on their presence.
    monkeypatch.setenv("FORGELAB_OUTPUT_DIR", str(tmp_path))
    doc = _cube_doc(
        modifiers=[
            {"type": "subsurf", "levels": 2},
            {"type": "boolean", "operation": "difference", "target": "obj_cube"},
        ]
    )
    src = _write_doc(tmp_path, doc)
    result = tools.preview_render(src, "preview.png", views=1)
    assert result["rendered"] is True
    assert result["triangle_count"] == 12
    assert result["views"] == ["front-3/4"]


def test_preview_render_empty_scene_errors_clearly(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGELAB_OUTPUT_DIR", str(tmp_path))
    src = _write_doc(tmp_path, _cube_doc(with_mesh=False))
    with pytest.raises(ValueError, match="no triangle geometry"):
        tools.preview_render(src, "preview.png")


def test_preview_render_rejects_non_threed_documents(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGELAB_OUTPUT_DIR", str(tmp_path))
    doc = _cube_doc()
    doc["domain"] = "mechanical"
    doc["nodes"] = [{"id": "b", "type": "body", "props": {"name": "B"}}]
    src = _write_doc(tmp_path, doc)
    with pytest.raises(ValueError, match="threed documents only"):
        tools.preview_render(src, "preview.png")


def test_preview_render_missing_extra_gives_install_instruction(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGELAB_OUTPUT_DIR", str(tmp_path))
    src = _write_doc(tmp_path, _cube_doc())

    def no_preview():
        raise ImportError("No module named 'matplotlib'")

    monkeypatch.setattr(tools, "_import_preview", no_preview)
    with pytest.raises(ValueError, match=r'pip install "forgelab\[preview\]"'):
        tools.preview_render(src, "preview.png")


def test_transforms_are_applied_to_world_positions():
    from forgelab.core import validate
    from forgelab.preview import collect_triangles

    doc = _cube_doc()
    doc["nodes"][-1]["props"]["transform"] = {
        "translation": [10.0, 0.0, 0.0],
        "rotation": [0.0, 0.0, 0.0, 1.0],
        "scale": [2.0, 1.0, 1.0],
    }
    triangles, colors = collect_triangles(validate(doc))
    xs = [p[0] for tri in triangles for p in tri]
    assert min(xs) == pytest.approx(8.0) and max(xs) == pytest.approx(12.0)
    assert colors[0] == (0.8, 0.1, 0.1, 1.0)  # material resolved to base_color


# ------------------------------------------------------------ critique_render


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


def _install_client(monkeypatch, text):
    client = _FakeClient(text)
    monkeypatch.setattr(tools, "_make_vision_client", lambda: client)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    return client


def _render_png(tmp_path, name="render.png"):
    (tmp_path / name).write_bytes(_PNG)
    return str(tmp_path / name)


def test_critique_render_returns_parsed_structured_feedback(tmp_path, monkeypatch):
    client = _install_client(monkeypatch, json.dumps(_CRITIQUE))
    result = tools.critique_render(_render_png(tmp_path), "a sleek sports car")
    assert result["matches_intent"] is False
    assert result["score"] == 6
    assert result["issues"][0]["severity"] == "critical"
    assert result["suggested_changes"] == ["increase greenhouse height by ~30%"]
    # Intent-only: exactly one image block plus the text block was sent.
    content = client.messages.calls[0]["messages"][0]["content"]
    assert [b["type"] for b in content] == ["image", "text"]
    assert "sports car" in content[-1]["text"]


def test_critique_render_tolerates_fenced_and_prose_wrapped_json(tmp_path, monkeypatch):
    wrapped = "Here is my assessment:\n```json\n" + json.dumps(_CRITIQUE) + "\n```\nHope it helps!"
    _install_client(monkeypatch, wrapped)
    result = tools.critique_render(_render_png(tmp_path), "a sleek sports car")
    assert result["score"] == 6
    assert result["matches_intent"] is False


def test_critique_render_sends_reference_image_when_provided(tmp_path, monkeypatch):
    client = _install_client(monkeypatch, json.dumps(_CRITIQUE))
    reference = str(tmp_path / "ref.png")
    (tmp_path / "ref.png").write_bytes(_PNG)
    tools.critique_render(_render_png(tmp_path), "match the reference", reference)
    content = client.messages.calls[0]["messages"][0]["content"]
    assert [b["type"] for b in content] == ["image", "image", "text"]
    assert "reference image" in client.messages.calls[0]["system"]


def test_critique_render_without_api_key_errors_clearly(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY is not set"):
        tools.critique_render(_render_png(tmp_path), "anything")


def test_critique_render_requires_an_intent(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with pytest.raises(ValueError, match="intent"):
        tools.critique_render(_render_png(tmp_path), "   ")


# ---------------------------------------------------------- generation_status


def test_generation_status_reports_preview_and_critique(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    status = tools.generation_status()
    assert status["critique_render"] is False  # no API key
    assert status["preview_render"] is True  # matplotlib installed in dev env
    monkeypatch.setattr(tools, "_preview_extra_installed", lambda: False)
    status = tools.generation_status()
    assert status["preview_render"] is False
    assert "forgelab[preview]" in status["preview_reason"]


def test_critique_render_prose_response_raises_actionable_error(tmp_path, monkeypatch):
    # A pure-prose response (no JSON object at all) must surface as the
    # tool's ValueError, not leak the SDK-internal LLMOutputError.
    _install_client(monkeypatch, "I cannot critique this render, sorry.")
    with pytest.raises(ValueError, match="did not return parseable critique JSON"):
        tools.critique_render(_render_png(tmp_path), "a sleek sports car")
