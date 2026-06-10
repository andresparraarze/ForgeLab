# ForgeLab MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `forgelab/mcp/` — a thin MCP server (official MCP SDK / FastMCP) exposing ForgeLab's validate/schema/prompts, import/export, generate, and discovery capabilities as tools over stdio (local) and OAuth-protected Streamable HTTP (remote), reusing the `forgelab.auth` module's three scopes.

**Architecture:** Plain tool callables in `tools.py` wrap `forgelab.core`/`sdk`/registry. A `register()` adds them to a `FastMCP` built by `create_server(auth_settings)`. An auth bridge maps the MCP SDK's `TokenVerifier` to `forgelab.auth` and enforces per-tool scopes via `get_access_token()`. A CLI runs either transport. MCP SDK imports are confined to `forgelab/mcp/`.

**Tech Stack:** Python 3.11+, the official MCP SDK (`mcp>=1.12`, FastMCP), Pydantic v2, `forgelab.auth`, `forgelab.sdk`, Pytest. New optional `[mcp]` extra. Run tooling with `PATH="$PWD/.venv/bin:$PATH"` prefix.

**Boundary rule (must hold):** `forgelab/mcp/` may import `forgelab.core`, `forgelab.spec`, `forgelab.sdk`, `forgelab.auth`, and `mcp` — but NEVER `forgelab.importers` or `forgelab.exporters` (reach those through the registry). The `mcp` SDK import appears ONLY under `forgelab/mcp/`.

**Error convention:** `validate_document` returns `{"valid": bool, "error"?: str}` (a `false` is a normal result). Every other tool raises a `ValueError` with a clear, actionable message on expected failures (unknown format, unimplemented stub, missing `ANTHROPIC_API_KEY`, missing `[agent]` extra, bad input) — FastMCP surfaces the message as an error result without leaking a traceback.

---

## File structure

- Create `forgelab/mcp/__init__.py` — exports `create_server`.
- Create `forgelab/mcp/content.py` — `encode_bytes` / `decode_content` (no SDK import).
- Create `forgelab/mcp/auth_bridge.py` — `ForgeLabTokenVerifier`, `require_scope`.
- Create `forgelab/mcp/tools.py` — the 8 tool callables + module registry.
- Create `forgelab/mcp/server.py` — `create_server(auth_settings, *, host, port)` + `_register`.
- Create `forgelab/mcp/__main__.py` — CLI (`main`, `_build`).
- Modify `forgelab/core/registry.py` — add `tool_names()` accessor.
- Modify `pyproject.toml` — `[mcp]` extra, `mcp` in `[dev]`, `[project.scripts]`.
- Create tests: `tests/test_mcp_content.py`, `tests/test_registry_tool_names.py`, `tests/test_mcp_auth_bridge.py`, `tests/test_mcp_tools_read.py`, `tests/test_mcp_tools_transfer.py`, `tests/test_mcp_tools_generate.py`, `tests/test_mcp_server.py`, `tests/test_mcp_cli.py`.
- Modify `README.md`, `CHANGELOG.md`.

---

## Task 1: `[mcp]` extra + content codec

**Files:**
- Modify: `pyproject.toml`
- Create: `forgelab/mcp/__init__.py`, `forgelab/mcp/content.py`
- Test: `tests/test_mcp_content.py`

- [ ] **Step 1: Add the extra and dev dep**

In `pyproject.toml` under `[project.optional-dependencies]` add:
```toml
mcp = ["mcp>=1.12"]
```
and append `"mcp>=1.12"` to the `dev` list.

- [ ] **Step 2: Install**

Run: `PATH="$PWD/.venv/bin:$PATH" pip install -e ".[dev]"`
Expected: installs `mcp`.

- [ ] **Step 3: Create the package init**

Create `forgelab/mcp/__init__.py`:
```python
"""ForgeLab MCP server — exposes ForgeLab as MCP tools over stdio and HTTP.

Frontend peer to ``forgelab.api``: depends on core/spec/sdk/auth and reaches
importers/exporters only through the registry. The ``mcp`` SDK is confined to
this package.
"""

from forgelab.mcp.server import create_server

__all__ = ["create_server"]
```
NOTE: this imports `create_server` from `server.py`, which does not exist until Task 5. That is fine because no task imports `forgelab.mcp` (the package root) before Task 5 — Tasks 1-4 import the specific submodules (`forgelab.mcp.content`, `forgelab.mcp.auth_bridge`, `forgelab.mcp.tools`) directly. If you want the suite green at every commit, temporarily make `__init__.py` empty now and add the export in Task 5. Either approach is acceptable; prefer the empty-now approach to keep all intermediate test runs green:
```python
"""ForgeLab MCP server — exposes ForgeLab as MCP tools over stdio and HTTP.

Frontend peer to ``forgelab.api``: depends on core/spec/sdk/auth and reaches
importers/exporters only through the registry. The ``mcp`` SDK is confined to
this package.
"""
```
Use the empty-docstring version for this task; Task 5 adds the `create_server` export.

- [ ] **Step 4: Write the failing test**

Create `tests/test_mcp_content.py`:
```python
import pytest

from forgelab.mcp.content import decode_content, encode_bytes


def test_text_round_trips_as_utf8():
    enc = encode_bytes(b"(kicad_pcb (version 20211014))")
    assert enc["encoding"] == "utf-8"
    assert enc["content"] == "(kicad_pcb (version 20211014))"
    assert decode_content(enc["content"], enc["encoding"]) == b"(kicad_pcb (version 20211014))"


def test_binary_round_trips_as_base64():
    raw = bytes([0x50, 0x4B, 0x03, 0x04, 0x80, 0xFF, 0x00])  # zip header + non-utf8
    enc = encode_bytes(raw)
    assert enc["encoding"] == "base64"
    assert decode_content(enc["content"], enc["encoding"]) == raw


def test_decode_rejects_unknown_encoding():
    with pytest.raises(ValueError, match="unsupported encoding"):
        decode_content("x", "rot13")
```

- [ ] **Step 5: Run it to confirm failure**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest tests/test_mcp_content.py -q`
Expected: FAIL (ModuleNotFoundError: forgelab.mcp.content).

- [ ] **Step 6: Implement `content.py`**

Create `forgelab/mcp/content.py`:
```python
"""Encode/decode native file bytes for MCP transport (text or base64)."""

from __future__ import annotations

import base64


def encode_bytes(data: bytes) -> dict[str, str]:
    """Encode bytes as UTF-8 text when possible, else base64.

    Returns ``{"encoding": "utf-8"|"base64", "content": <str>}``.
    """
    try:
        return {"encoding": "utf-8", "content": data.decode("utf-8")}
    except UnicodeDecodeError:
        return {"encoding": "base64", "content": base64.b64encode(data).decode("ascii")}


def decode_content(content: str, encoding: str) -> bytes:
    """Inverse of :func:`encode_bytes`."""
    if encoding == "utf-8":
        return content.encode("utf-8")
    if encoding == "base64":
        return base64.b64decode(content)
    raise ValueError(f"unsupported encoding: {encoding!r} (expected 'utf-8' or 'base64')")
```

- [ ] **Step 7: Run tests to confirm pass**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest tests/test_mcp_content.py -q`
Expected: PASS (3 passed).

- [ ] **Step 8: Lint/type and commit**

Run: `PATH="$PWD/.venv/bin:$PATH" ruff check forgelab/mcp tests/test_mcp_content.py && PATH="$PWD/.venv/bin:$PATH" ruff format forgelab/mcp tests/test_mcp_content.py && PATH="$PWD/.venv/bin:$PATH" pyright forgelab/mcp/content.py`
```bash
git add pyproject.toml forgelab/mcp/__init__.py forgelab/mcp/content.py tests/test_mcp_content.py
git commit -m "feat(mcp): [mcp] extra + content (utf-8/base64) codec"
```

---

## Task 2: `Registry.tool_names()` accessor

**Files:**
- Modify: `forgelab/core/registry.py`
- Test: `tests/test_registry_tool_names.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_registry_tool_names.py`:
```python
from forgelab.core import Registry, default_registry
from forgelab.exporters.base import Exporter
from forgelab.importers.base import Importer
from forgelab.spec import ForgeDocument


def test_tool_names_reports_import_export_availability():
    class ImpOnly(Importer):
        tool_name = "imp"

        def to_ir(self, source: bytes) -> ForgeDocument:  # pragma: no cover
            raise NotImplementedError

    class ExpOnly(Exporter):
        tool_name = "exp"

        def from_ir(self, document: ForgeDocument) -> bytes:  # pragma: no cover
            raise NotImplementedError

    reg = Registry()
    reg.register_importer(ImpOnly)
    reg.register_exporter(ExpOnly)
    assert reg.tool_names() == {
        "exp": {"import": False, "export": True},
        "imp": {"import": True, "export": False},
    }


def test_default_registry_lists_real_tools():
    names = default_registry().tool_names()
    assert names["kicad"] == {"import": True, "export": True}
    assert names["gltf"]["export"] is True
    assert names["freecad"]["import"] is True
```

- [ ] **Step 2: Run it to confirm failure**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest tests/test_registry_tool_names.py -q`
Expected: FAIL (`Registry` has no attribute `tool_names`).

- [ ] **Step 3: Add the accessor**

In `forgelab/core/registry.py`, add this method to the `Registry` class (after `get_exporter`):
```python
    def tool_names(self) -> dict[str, dict[str, bool]]:
        """Map every registered tool to its import/export availability."""
        names = set(self._importers) | set(self._exporters)
        return {
            name: {
                "import": name in self._importers,
                "export": name in self._exporters,
            }
            for name in sorted(names)
        }
```

- [ ] **Step 4: Run tests to confirm pass**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest tests/test_registry_tool_names.py -q`
Expected: PASS (2 passed). If the second test fails on a tool name, run `PATH="$PWD/.venv/bin:$PATH" python -c "from forgelab.core import default_registry; print(default_registry().tool_names())"` and adjust the asserted names to the real registered tools (kicad/gltf/freecad are expected).

- [ ] **Step 5: Lint/type and commit**

Run: `PATH="$PWD/.venv/bin:$PATH" ruff check forgelab/core tests/test_registry_tool_names.py && PATH="$PWD/.venv/bin:$PATH" pyright forgelab/core/registry.py`
```bash
git add forgelab/core/registry.py tests/test_registry_tool_names.py
git commit -m "feat(core): Registry.tool_names() read accessor for discovery"
```

---

## Task 3: Auth bridge (`TokenVerifier` + `require_scope`)

**Files:**
- Create: `forgelab/mcp/auth_bridge.py`
- Test: `tests/test_mcp_auth_bridge.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mcp_auth_bridge.py`:
```python
import asyncio

import pytest
from mcp.server.auth.provider import AccessToken

from forgelab.auth.config import AuthSettings
from forgelab.auth.verifier import issue_token
from forgelab.mcp import auth_bridge
from forgelab.mcp.auth_bridge import ForgeLabTokenVerifier, require_scope


def _settings():
    return AuthSettings(enabled=True, mode="dev", dev_secret="a" * 32)


def test_verify_token_maps_valid_dev_token():
    s = _settings()
    token = issue_token(s, sub="svc", client_id="svc", scopes={"forge:read", "forge:export"})
    access = asyncio.run(ForgeLabTokenVerifier(s).verify_token(token))
    assert access is not None
    assert access.client_id == "svc"
    assert access.subject == "svc"
    assert set(access.scopes) == {"forge:read", "forge:export"}


def test_verify_token_returns_none_for_garbage():
    access = asyncio.run(ForgeLabTokenVerifier(_settings()).verify_token("not-a-token"))
    assert access is None


def test_require_scope_allows_when_no_auth_context():
    # Outside an authenticated request get_access_token() returns None -> local/trusted.
    assert require_scope("forge:read") is None


def test_require_scope_allows_when_scope_present(monkeypatch):
    monkeypatch.setattr(
        auth_bridge, "get_access_token",
        lambda: AccessToken(token="t", client_id="c", scopes=["forge:read", "forge:export"]),
    )
    assert require_scope("forge:export") is None


def test_require_scope_rejects_when_scope_missing(monkeypatch):
    monkeypatch.setattr(
        auth_bridge, "get_access_token",
        lambda: AccessToken(token="t", client_id="c", scopes=["forge:read"]),
    )
    with pytest.raises(PermissionError, match="missing required scope: forge:export"):
        require_scope("forge:export")
```

- [ ] **Step 2: Run it to confirm failure**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest tests/test_mcp_auth_bridge.py -q`
Expected: FAIL (ModuleNotFoundError: forgelab.mcp.auth_bridge).

- [ ] **Step 3: Implement `auth_bridge.py`**

Create `forgelab/mcp/auth_bridge.py`:
```python
"""Bridge the MCP SDK's resource-server auth to forgelab.auth + per-tool scopes."""

from __future__ import annotations

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier

from forgelab.auth import AuthError, AuthSettings, build_verifier


class ForgeLabTokenVerifier(TokenVerifier):
    """Validate bearer tokens with forgelab.auth, returning the SDK's AccessToken."""

    def __init__(self, settings: AuthSettings) -> None:
        self._verifier = build_verifier(settings)

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            principal = self._verifier.verify(token)
        except AuthError:
            return None
        return AccessToken(
            token=token,
            client_id=principal.client_id,
            scopes=sorted(principal.scopes),
            subject=principal.sub,
            claims=dict(principal.claims),
        )


def require_scope(scope: str) -> None:
    """Enforce a scope for the current call.

    Over stdio (no auth) ``get_access_token()`` is ``None`` -> allowed. Over the
    authenticated HTTP transport a token is always present; raise if it lacks the
    required scope.
    """
    access = get_access_token()
    if access is None:
        return
    if scope not in access.scopes:
        raise PermissionError(f"missing required scope: {scope}")
```

- [ ] **Step 4: Run tests to confirm pass**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest tests/test_mcp_auth_bridge.py -q`
Expected: PASS (5 passed). If `get_access_token()` raises instead of returning `None` outside a request (unlikely), wrap it: `try: access = get_access_token(); except LookupError: return` — but verify the default-None behavior first; do not add the guard unless a test actually fails.

- [ ] **Step 5: Lint/type and commit**

Run: `PATH="$PWD/.venv/bin:$PATH" ruff check forgelab/mcp tests/test_mcp_auth_bridge.py && PATH="$PWD/.venv/bin:$PATH" ruff format forgelab/mcp/auth_bridge.py tests/test_mcp_auth_bridge.py && PATH="$PWD/.venv/bin:$PATH" pyright forgelab/mcp/auth_bridge.py`
```bash
git add forgelab/mcp/auth_bridge.py tests/test_mcp_auth_bridge.py
git commit -m "feat(mcp): auth bridge (TokenVerifier + require_scope)"
```

---

## Task 4: Read + discovery tools

**Files:**
- Create: `forgelab/mcp/tools.py`
- Test: `tests/test_mcp_tools_read.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mcp_tools_read.py`:
```python
import pytest

from forgelab.mcp import tools
from forgelab.spec import SPEC_VERSION


def _hardware_doc():
    return {
        "forgelab_version": SPEC_VERSION,
        "domain": "hardware",
        "meta": {"name": "blinky", "generator": "test"},
        "nodes": [{"id": "r1", "type": "component"}],
    }


def test_validate_document_accepts_valid():
    assert tools.validate_document(_hardware_doc()) == {"valid": True}


def test_validate_document_reports_invalid():
    bad = _hardware_doc()
    bad["forgelab_version"] = "999.0.0"
    result = tools.validate_document(bad)
    assert result["valid"] is False
    assert "error" in result


def test_get_domain_schema_pins_domain():
    schema = tools.get_domain_schema("hardware")
    assert schema["properties"]["domain"] == {"const": "hardware"}


def test_get_domain_schema_unknown_raises():
    with pytest.raises(ValueError, match="unknown domain"):
        tools.get_domain_schema("nope")


def test_get_prompt_returns_system_and_few_shot():
    p = tools.get_prompt("mechanical")
    assert isinstance(p["system"], str) and p["system"]
    assert "few_shot" in p


def test_list_domains():
    assert tools.list_domains() == ["hardware", "mechanical", "threed"]


def test_list_formats_reports_registered_tools():
    formats = tools.list_formats()
    assert formats["kicad"]["export"] is True
    assert formats["freecad"]["import"] is True
```

- [ ] **Step 2: Run it to confirm failure**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest tests/test_mcp_tools_read.py -q`
Expected: FAIL (ModuleNotFoundError: forgelab.mcp.tools).

- [ ] **Step 3: Implement `tools.py` (read + discovery)**

Create `forgelab/mcp/tools.py`:
```python
"""ForgeLab MCP tool callables.

Plain functions wrapping the core compiler, registry, and AI SDK. ``server.py``
registers them with FastMCP. Each enforces its scope via ``require_scope`` (a
no-op over the unauthenticated stdio transport).
"""

from __future__ import annotations

from typing import Any

from forgelab.core import UnknownToolError, default_registry, validate
from forgelab.mcp.auth_bridge import require_scope
from forgelab.sdk import DOMAIN_VOCAB, domain_schema, few_shot, system_prompt

_registry = default_registry()


def validate_document(document: dict[str, Any]) -> dict[str, Any]:
    """Validate a ForgeLab document. Returns {"valid": bool, "error"?: str}."""
    require_scope("forge:read")
    try:
        validate(document)
    except Exception as exc:  # any validation failure is reported to the caller
        return {"valid": False, "error": str(exc)}
    return {"valid": True}


def get_domain_schema(domain: str) -> dict[str, Any]:
    """Return the JSON Schema for a ForgeLab domain."""
    require_scope("forge:read")
    try:
        return domain_schema(domain)
    except KeyError as exc:
        raise ValueError(f"unknown domain: {domain!r}") from exc


def get_prompt(domain: str) -> dict[str, Any]:
    """Return the system prompt and a few-shot example for a domain."""
    require_scope("forge:read")
    try:
        return {"system": system_prompt(domain), "few_shot": few_shot(domain)}
    except KeyError as exc:
        raise ValueError(f"unknown domain: {domain!r}") from exc


def list_domains() -> list[str]:
    """List the ForgeLab domains the server understands."""
    require_scope("forge:read")
    return sorted(DOMAIN_VOCAB)


def list_formats() -> dict[str, dict[str, bool]]:
    """List registered format tools and their import/export availability."""
    require_scope("forge:read")
    return _registry.tool_names()
```

- [ ] **Step 4: Run tests to confirm pass**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest tests/test_mcp_tools_read.py -q`
Expected: PASS (7 passed). If `system_prompt`/`few_shot` raise something other than `KeyError` for an unknown domain, the `get_prompt` unknown path isn't exercised by these tests, so no change is needed; leave the `KeyError` wrap as-is (it matches `domain_schema`'s behavior).

- [ ] **Step 5: Lint/type and commit**

Run: `PATH="$PWD/.venv/bin:$PATH" ruff check forgelab/mcp tests/test_mcp_tools_read.py && PATH="$PWD/.venv/bin:$PATH" ruff format forgelab/mcp/tools.py tests/test_mcp_tools_read.py && PATH="$PWD/.venv/bin:$PATH" pyright forgelab/mcp/tools.py`
```bash
git add forgelab/mcp/tools.py tests/test_mcp_tools_read.py
git commit -m "feat(mcp): validate/schema/prompt/list tools (forge:read)"
```

---

## Task 5: Import + export tools

**Files:**
- Modify: `forgelab/mcp/tools.py`, `forgelab/mcp/__init__.py`
- Test: `tests/test_mcp_tools_transfer.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mcp_tools_transfer.py`:
```python
import json
from pathlib import Path

import pytest

from forgelab.core import Registry, validate
from forgelab.exporters.base import Exporter
from forgelab.mcp import tools
from forgelab.spec import ForgeDocument, SPEC_VERSION

_EXAMPLE = Path("examples/mechanical/box-with-hole.forge.json")


def _hardware_doc():
    return {
        "forgelab_version": SPEC_VERSION,
        "domain": "hardware",
        "meta": {"name": "blinky", "generator": "test"},
        "nodes": [{"id": "r1", "type": "component"}],
    }


def test_export_hardware_is_utf8_text():
    out = tools.export_document(_hardware_doc(), "kicad")
    assert out["tool"] == "kicad"
    assert out["encoding"] == "utf-8"
    assert "kicad_pcb" in out["content"]


def test_freecad_round_trip_via_base64():
    doc = json.loads(_EXAMPLE.read_text())
    out = tools.export_document(doc, "freecad")
    assert out["encoding"] == "base64"
    back = tools.import_file("freecad", out["content"], out["encoding"])
    assert back == validate(doc).model_dump(mode="json")


def test_export_unknown_tool_raises():
    with pytest.raises(ValueError, match="No exporter registered"):
        tools.export_document(_hardware_doc(), "nope")


def test_import_unknown_tool_raises():
    with pytest.raises(ValueError, match="No importer registered"):
        tools.import_file("nope", "data", "utf-8")


def test_export_not_implemented_is_clear(monkeypatch):
    class Stub(Exporter):
        tool_name = "stub"

        def from_ir(self, document: ForgeDocument) -> bytes:
            raise NotImplementedError("stub exporter")

    reg = Registry()
    reg.register_exporter(Stub)
    monkeypatch.setattr(tools, "_registry", reg)
    with pytest.raises(ValueError, match="not implemented"):
        tools.export_document(_hardware_doc(), "stub")


def test_export_invalid_document_is_clear():
    bad = _hardware_doc()
    bad["forgelab_version"] = "999.0.0"
    with pytest.raises(ValueError, match="invalid document"):
        tools.export_document(bad, "kicad")
```

- [ ] **Step 2: Run it to confirm failure**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest tests/test_mcp_tools_transfer.py -q`
Expected: FAIL (`tools` has no attribute `export_document`).

- [ ] **Step 3: Append import/export to `tools.py`**

Add this import to the top of `forgelab/mcp/tools.py` (with the others):
```python
from forgelab.mcp.content import decode_content, encode_bytes
```
Append these functions to the end of `forgelab/mcp/tools.py`:
```python
def export_document(document: dict[str, Any], tool: str) -> dict[str, Any]:
    """Export a ForgeLab document to a format tool's native file.

    Returns {"tool", "encoding": "utf-8"|"base64", "content": <str>}.
    """
    require_scope("forge:export")
    try:
        doc = validate(document)
    except Exception as exc:
        raise ValueError(f"invalid document: {exc}") from exc
    try:
        exporter = _registry.get_exporter(tool)
    except UnknownToolError as exc:
        raise ValueError(str(exc)) from exc
    try:
        data = exporter().from_ir(doc)
    except NotImplementedError as exc:
        raise ValueError(f"export not implemented for {tool!r}: {exc}") from exc
    return {"tool": tool, **encode_bytes(data)}


def import_file(tool: str, content: str, encoding: str = "utf-8") -> dict[str, Any]:
    """Import a format tool's native file into a ForgeLab document (as a dict)."""
    require_scope("forge:export")
    try:
        importer = _registry.get_importer(tool)
    except UnknownToolError as exc:
        raise ValueError(str(exc)) from exc
    source = decode_content(content, encoding)
    document = importer().to_ir(source)
    return document.model_dump(mode="json")
```

- [ ] **Step 4: Add the package export**

Replace `forgelab/mcp/__init__.py` with:
```python
"""ForgeLab MCP server — exposes ForgeLab as MCP tools over stdio and HTTP.

Frontend peer to ``forgelab.api``: depends on core/spec/sdk/auth and reaches
importers/exporters only through the registry. The ``mcp`` SDK is confined to
this package.
"""

from forgelab.mcp.server import create_server

__all__ = ["create_server"]
```
NOTE: `server.py` is created in the NEXT task. To keep this task's commit importable, do this `__init__.py` change in Task 6 (Step where `server.py` exists). For THIS task, leave `__init__.py` as the empty docstring from Task 1 and only commit `tools.py` + the test. (The test imports `forgelab.mcp.tools` directly, not `forgelab.mcp`, so it passes without `create_server`.)

Correction: do NOT modify `__init__.py` in this task. Keep it empty-docstring. The `create_server` export lands in Task 6 after `server.py` exists.

- [ ] **Step 5: Run tests to confirm pass**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest tests/test_mcp_tools_transfer.py -q`
Expected: PASS (6 passed). If `test_freecad_round_trip_via_base64` fails because the example path differs, run `ls examples/mechanical/` and fix `_EXAMPLE`. The round-trip equality relies on the FreeCAD IR-level identity guarantee (already verified in the FreeCAD suite).

- [ ] **Step 6: Lint/type and commit**

Run: `PATH="$PWD/.venv/bin:$PATH" ruff check forgelab/mcp tests/test_mcp_tools_transfer.py && PATH="$PWD/.venv/bin:$PATH" ruff format forgelab/mcp/tools.py tests/test_mcp_tools_transfer.py && PATH="$PWD/.venv/bin:$PATH" pyright forgelab/mcp/tools.py`
```bash
git add forgelab/mcp/tools.py tests/test_mcp_tools_transfer.py
git commit -m "feat(mcp): import/export tools with utf-8/base64 content (forge:export)"
```

---

## Task 6: Generate tool + `create_server`

**Files:**
- Modify: `forgelab/mcp/tools.py`, `forgelab/mcp/__init__.py`
- Create: `forgelab/mcp/server.py`
- Test: `tests/test_mcp_tools_generate.py`, `tests/test_mcp_server.py`

- [ ] **Step 1: Write the failing generate test**

Create `tests/test_mcp_tools_generate.py`:
```python
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
```

- [ ] **Step 2: Run it to confirm failure**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest tests/test_mcp_tools_generate.py -q`
Expected: FAIL (`tools` has no attribute `generate_document` / `_make_agent`).

- [ ] **Step 3: Append generate to `tools.py`**

Add these imports to the top of `forgelab/mcp/tools.py`:
```python
import os

from forgelab.sdk import ForgeAgent
```
Append to the end of `forgelab/mcp/tools.py`:
```python
def _make_agent(model: str) -> ForgeAgent:
    """Construct a ForgeAgent. Indirection so tests can inject a fake agent."""
    return ForgeAgent(model=model)


def generate_document(prompt: str, domain: str, model: str = "claude-opus-4-8") -> dict[str, Any]:
    """Generate a validated ForgeLab document from a natural-language prompt."""
    require_scope("forge:generate")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError("generation unavailable: ANTHROPIC_API_KEY is not set on the server")
    try:
        agent = _make_agent(model)
    except ImportError as exc:
        raise ValueError(
            'generation unavailable: install the agent extra (pip install "forgelab[agent]")'
        ) from exc
    document = agent.design(prompt, domain=domain)
    return document.model_dump(mode="json")
```

- [ ] **Step 4: Run the generate test to confirm pass**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest tests/test_mcp_tools_generate.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Write the failing server test**

Create `tests/test_mcp_server.py`:
```python
import asyncio

from forgelab.auth.config import AuthSettings
from forgelab.mcp.server import create_server

_EXPECTED = {
    "validate_document",
    "get_domain_schema",
    "get_prompt",
    "list_domains",
    "list_formats",
    "export_document",
    "import_file",
    "generate_document",
}


def _tool_names(server):
    return {t.name for t in asyncio.run(server.list_tools())}


def test_stdio_server_registers_all_tools():
    server = create_server(None)
    assert _tool_names(server) == _EXPECTED


def test_http_server_builds_with_auth_and_all_tools():
    settings = AuthSettings(enabled=True, mode="dev", dev_secret="a" * 32)
    server = create_server(settings)
    assert _tool_names(server) == _EXPECTED
    assert server.name == "forgelab"
```

- [ ] **Step 6: Run it to confirm failure**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest tests/test_mcp_server.py -q`
Expected: FAIL (ModuleNotFoundError: forgelab.mcp.server).

- [ ] **Step 7: Implement `server.py`**

Create `forgelab/mcp/server.py`:
```python
"""Assemble the ForgeLab MCP server (FastMCP) for stdio or Streamable HTTP."""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from forgelab.auth import AuthSettings
from forgelab.mcp import tools
from forgelab.mcp.auth_bridge import ForgeLabTokenVerifier

_TOOLS = [
    tools.validate_document,
    tools.get_domain_schema,
    tools.get_prompt,
    tools.list_domains,
    tools.list_formats,
    tools.export_document,
    tools.import_file,
    tools.generate_document,
]


def _register(mcp: FastMCP) -> None:
    for fn in _TOOLS:
        mcp.add_tool(fn)


def create_server(
    auth_settings: AuthSettings | None = None, *, host: str = "127.0.0.1", port: int = 8001
) -> FastMCP:
    """Build the MCP server.

    With an enabled ``auth_settings`` the Streamable HTTP transport is configured
    as an OAuth resource server (token verifier + protected-resource metadata).
    Otherwise an unauthenticated server (for stdio) is returned. ``host``/``port``
    apply only to the HTTP transport.
    """
    if auth_settings is not None and auth_settings.enabled:
        from mcp.server.auth.settings import AuthSettings as McpAuthSettings
        from pydantic import AnyHttpUrl

        issuer = os.environ.get("FORGELAB_MCP_ISSUER_URL", "http://localhost:8000")
        resource = os.environ.get("FORGELAB_MCP_RESOURCE_URL", "http://localhost:8001")
        mcp = FastMCP(
            "forgelab",
            host=host,
            port=port,
            stateless_http=True,
            json_response=True,
            token_verifier=ForgeLabTokenVerifier(auth_settings),
            auth=McpAuthSettings(
                issuer_url=AnyHttpUrl(issuer),
                resource_server_url=AnyHttpUrl(resource),
                required_scopes=[],
            ),
        )
    else:
        mcp = FastMCP("forgelab")
    _register(mcp)
    return mcp
```

- [ ] **Step 8: Add the package export**

Replace `forgelab/mcp/__init__.py` with:
```python
"""ForgeLab MCP server — exposes ForgeLab as MCP tools over stdio and HTTP.

Frontend peer to ``forgelab.api``: depends on core/spec/sdk/auth and reaches
importers/exporters only through the registry. The ``mcp`` SDK is confined to
this package.
"""

from forgelab.mcp.server import create_server

__all__ = ["create_server"]
```

- [ ] **Step 9: Run both new test files to confirm pass**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest tests/test_mcp_tools_generate.py tests/test_mcp_server.py -q`
Expected: PASS (5 passed). If `mcp.add_tool` is not the correct registration call for the installed SDK version, use `mcp.tool()(fn)` instead (the decorator form applied directly); verify with `PATH="$PWD/.venv/bin:$PATH" python -c "from mcp.server.fastmcp import FastMCP; m=FastMCP('x'); print(hasattr(m,'add_tool'))"`. If `server.list_tools()` raises (needs a running session in some versions), fall back to asserting registration via `server._tool_manager.list_tools()` and report the deviation.

- [ ] **Step 10: Lint/type and commit**

Run: `PATH="$PWD/.venv/bin:$PATH" ruff check forgelab/mcp tests/test_mcp_tools_generate.py tests/test_mcp_server.py && PATH="$PWD/.venv/bin:$PATH" ruff format forgelab/mcp tests/test_mcp_tools_generate.py tests/test_mcp_server.py && PATH="$PWD/.venv/bin:$PATH" pyright forgelab/mcp`
```bash
git add forgelab/mcp/tools.py forgelab/mcp/server.py forgelab/mcp/__init__.py tests/test_mcp_tools_generate.py tests/test_mcp_server.py
git commit -m "feat(mcp): generate tool (graceful no-key error) + create_server"
```

---

## Task 7: CLI entry point

**Files:**
- Create: `forgelab/mcp/__main__.py`
- Modify: `pyproject.toml`
- Test: `tests/test_mcp_cli.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mcp_cli.py`:
```python
from forgelab.mcp import __main__ as cli


def test_build_defaults_to_stdio():
    server, args = cli._build([])
    assert args.transport == "stdio"
    assert server.name == "forgelab"


def test_build_http_parses_host_port():
    server, args = cli._build(["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "9000"])
    assert args.transport == "streamable-http"
    assert args.host == "0.0.0.0"
    assert args.port == 9000


def test_main_dispatches_transport_to_run(monkeypatch):
    recorded = {}

    class FakeServer:
        def run(self, transport):
            recorded["transport"] = transport

    monkeypatch.setattr(cli, "create_server", lambda *a, **k: FakeServer())
    cli.main(["--transport", "stdio"])
    assert recorded["transport"] == "stdio"
```

- [ ] **Step 2: Run it to confirm failure**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest tests/test_mcp_cli.py -q`
Expected: FAIL (ModuleNotFoundError: forgelab.mcp.__main__).

- [ ] **Step 3: Implement `__main__.py`**

Create `forgelab/mcp/__main__.py`:
```python
"""CLI: run the ForgeLab MCP server over stdio or Streamable HTTP."""

from __future__ import annotations

import argparse
import os

from forgelab.auth import AuthSettings
from forgelab.mcp.server import create_server


def _build(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(prog="forgelab-mcp", description="ForgeLab MCP server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args(argv)
    if args.transport == "stdio":
        server = create_server(None)
    else:
        server = create_server(AuthSettings.from_env(os.environ), host=args.host, port=args.port)
    return server, args


def main(argv: list[str] | None = None) -> None:
    server, args = _build(argv)
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Add the console script**

In `pyproject.toml`, after the `[project.urls]` block (or anywhere top-level), add:
```toml
[project.scripts]
forgelab-mcp = "forgelab.mcp.__main__:main"
```

- [ ] **Step 5: Run tests to confirm pass**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest tests/test_mcp_cli.py -q`
Expected: PASS (3 passed). `test_build_http_parses_host_port` builds a real FastMCP with auth disabled (env unset → `enabled=False` → plain server), so it does not bind a socket.

- [ ] **Step 6: Lint/type and commit**

Run: `PATH="$PWD/.venv/bin:$PATH" ruff check forgelab/mcp tests/test_mcp_cli.py && PATH="$PWD/.venv/bin:$PATH" ruff format forgelab/mcp/__main__.py tests/test_mcp_cli.py && PATH="$PWD/.venv/bin:$PATH" pyright forgelab/mcp/__main__.py`
```bash
git add forgelab/mcp/__main__.py pyproject.toml tests/test_mcp_cli.py
git commit -m "feat(mcp): CLI entry (stdio | streamable-http) + console script"
```

---

## Task 8: Full suite, lint/type, boundary checks, docs

**Files:**
- Modify: `README.md`, `CHANGELOG.md`

- [ ] **Step 1: Full suite**

Run: `PATH="$PWD/.venv/bin:$PATH" pytest -q`
Expected: all pass (190 prior + ~29 new). If anything fails, STOP and report BLOCKED.

- [ ] **Step 2: Lint/format/type-check**

Run:
```bash
PATH="$PWD/.venv/bin:$PATH" ruff check forgelab tests
PATH="$PWD/.venv/bin:$PATH" ruff format --check forgelab tests
PATH="$PWD/.venv/bin:$PATH" pyright
```
All clean. If `ruff format --check` flags files, run `ruff format forgelab tests`, re-run the suite, and note it.

- [ ] **Step 3: Boundary verification**

Run:
```bash
grep -rEn "import forgelab\.(importers|exporters)" forgelab/mcp/ || echo "OK: mcp reaches importers/exporters only via the registry"
grep -rEl "from mcp|import mcp" forgelab/ | grep -v "forgelab/mcp/" || echo "OK: mcp SDK confined to forgelab/mcp/"
```
Expected: both print their OK line. Report the actual output.

- [ ] **Step 4: Update CHANGELOG.md**

In `CHANGELOG.md` under `## [Unreleased]` → `### Added`, add at the top:
```markdown
- MCP server (`forgelab/mcp/`): exposes ForgeLab as MCP tools over stdio (local)
  and OAuth-protected Streamable HTTP (remote) using the official MCP SDK. Tools:
  `validate_document`, `get_domain_schema`, `get_prompt`, `list_domains`,
  `list_formats` (`forge:read`); `export_document`, `import_file`
  (`forge:export`); `generate_document` (`forge:generate`, returns a clear error
  when `ANTHROPIC_API_KEY` is unset). Reuses the `forgelab.auth` module as the
  resource-server verifier. Run with `forgelab-mcp --transport stdio|streamable-http`.
  Optional `[mcp]` extra.
- `Registry.tool_names()` read accessor reporting per-tool import/export availability.
```

- [ ] **Step 5: Update README.md**

Read `README.md`; near the Authentication / REST API section add an "MCP server" subsection with this content (use real triple-backtick fences):
````markdown
### MCP server (optional)

ForgeLab ships an MCP server so agents (Claude Code, Hermes, OpenClaw) can use it
directly. Install the extra and run it:

```bash
pip install "forgelab[mcp]"

# Local (stdio, no auth):
forgelab-mcp --transport stdio

# Remote (Streamable HTTP, OAuth-protected — reuses FORGELAB_AUTH_* config):
FORGELAB_AUTH_ENABLED=true forgelab-mcp --transport streamable-http --port 8001
```

Tools: `validate_document`, `get_domain_schema`, `get_prompt`, `list_domains`,
`list_formats` (scope `forge:read`); `export_document`, `import_file`
(`forge:export`); `generate_document` (`forge:generate`). Over stdio all tools are
available locally; over HTTP each tool requires its scope on the bearer token.
`generate_document` needs a server-side `ANTHROPIC_API_KEY` and returns a clear
error if it is unset.
````
If README has an extras list mentioning `[agent]`/`[api]`/`[auth]`, add `[mcp]`.

- [ ] **Step 6: Verify README fences and commit**

Re-read the edited section to confirm code fences are balanced. Then:
```bash
git add README.md CHANGELOG.md
git commit -m "docs: document the MCP server"
```

## Notes
- Do NOT bump `SPEC_VERSION` — the MCP server adds no IR/spec change.
- The ANTHROPIC_API_KEY graceful error is delivered as a raised `ValueError` with a clear message (FastMCP returns it as an error result, no traceback).

---

## Self-review notes (for the implementer)

- **Spec coverage:** `[mcp]` extra + content codec (T1); registry accessor for `list_formats` (T2); auth bridge + per-tool scopes (T3); read/discovery tools (T4); import/export with the `{encoding, content}` shape (T5); generate with the `ANTHROPIC_API_KEY` graceful error + `create_server` two-transport assembly (T6); CLI + console script (T7); suite/lint/type/boundary/docs (T8). MCP resources/prompts primitives, token issuance, and new domains are intentionally out of scope.
- **Type/name consistency:** the 8 tool names in `server.py` `_TOOLS`, `tests/test_mcp_server.py` `_EXPECTED`, and the `tools.py` function names all match. `create_server(auth_settings=None, *, host, port)`, `require_scope(scope)`, `encode_bytes`/`decode_content`, `Registry.tool_names()`, `_make_agent(model)` are used identically across tasks.
- **Boundary:** `forgelab/mcp/` imports core/spec/sdk/auth/mcp only — never `forgelab.importers`/`forgelab.exporters`; `mcp` SDK confined to `forgelab/mcp/` (verified in T8 Step 3).
- **SDK-version guards:** T6 Step 9 gives fallbacks if `add_tool`/`list_tools` differ in the installed `mcp` version; the implementer should report any deviation rather than silently changing test expectations.
