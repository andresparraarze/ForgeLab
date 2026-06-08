# ForgeLab Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the ForgeLab open-source repository — a JSON-based universal design IR + compiler — with a real (minimal) spec backbone, one working end-to-end validation slice, documented stubs for importers/exporters/SDK, a FastAPI compiler-as-a-service, and standard tooling (Ruff, Pyright, Pytest, CI).

**Architecture:** Single installable `forgelab` package with submodules: `spec` (Pydantic v2 IR + versioning), `core` (registry + validate/transform pipeline), `importers` and `exporters` (ABCs + domain stubs that depend on `spec` only), `sdk` (agent helpers), and `api` (FastAPI thin layer over `core`). Documents declare conformance via a required `forgelab_version` field.

**Tech Stack:** Python 3.11+ (dev on 3.14), Pydantic v2, FastAPI, Starlette TestClient, Ruff, Pyright, Pytest, GitHub Actions.

---

## File Structure

Created in this plan:

- `pyproject.toml` — package metadata, deps, Ruff/Pyright/Pytest config
- `LICENSE` — Apache 2.0
- `README.md` — vision + quickstart
- `CONTRIBUTING.md`, `CHANGELOG.md`, `.gitignore`
- `forgelab/__init__.py` — package root, exports `SPEC_VERSION`, `__version__`
- `forgelab/spec/__init__.py` — re-exports spec models + `SPEC_VERSION`
- `forgelab/spec/version.py` — `SPEC_VERSION`, version-compat helpers
- `forgelab/spec/models.py` — `ForgeDocument`, `Node`, `DocumentMeta`, `Domain`
- `forgelab/spec/schema.py` — JSON Schema export helper
- `forgelab/core/__init__.py` — re-exports `validate`, registry, errors
- `forgelab/core/errors.py` — `ForgeError`, `IncompatibleVersionError`, `UnknownToolError`
- `forgelab/core/validate.py` — `validate(doc)` over the spec + version check
- `forgelab/core/registry.py` — importer/exporter registry
- `forgelab/core/pipeline.py` — `compile_` import→validate→transform→export orchestration
- `forgelab/importers/base.py` — `Importer` ABC
- `forgelab/importers/{hardware,mechanical,threed}.py` — domain stubs
- `forgelab/exporters/base.py` — `Exporter` ABC
- `forgelab/exporters/{hardware,mechanical,threed}.py` — domain stubs
- `forgelab/sdk/__init__.py` — agent helper functions
- `forgelab/api/__init__.py`, `forgelab/api/app.py` — FastAPI app
- `examples/hardware/blinky.forge.json` — sample valid document
- `tests/test_spec.py`, `tests/test_core.py`, `tests/test_api.py`, `tests/test_stubs.py`
- `.github/workflows/ci.yml` — lint + typecheck + test

Boundary rule enforced by imports: `importers`/`exporters` import from `forgelab.spec` only; `api`/`sdk` import from `forgelab.core`.

---

## Task 1: Project metadata and tooling config

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "forgelab"
version = "0.1.0"
description = "The LLVM of design — a universal JSON design interchange format and compiler for AI agents."
readme = "README.md"
requires-python = ">=3.11"
license = { text = "Apache-2.0" }
authors = [{ name = "ForgeLab Contributors" }]
keywords = ["design", "compiler", "intermediate-representation", "cad", "eda", "ai-agents"]
classifiers = [
  "Development Status :: 3 - Alpha",
  "Intended Audience :: Developers",
  "License :: OSI Approved :: Apache Software License",
  "Programming Language :: Python :: 3 :: Only",
  "Topic :: Software Development :: Compilers",
]
dependencies = [
  "pydantic>=2.6",
  "fastapi>=0.110",
]

[project.optional-dependencies]
api = ["uvicorn>=0.27"]
dev = [
  "pytest>=8.0",
  "httpx>=0.27",
  "ruff>=0.4",
  "pyright>=1.1.350",
]

[project.urls]
Homepage = "https://github.com/forgelab/forgelab"
Repository = "https://github.com/forgelab/forgelab"

[tool.hatch.build.targets.wheel]
packages = ["forgelab"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "W"]

[tool.pyright]
include = ["forgelab"]
pythonVersion = "3.11"
typeCheckingMode = "standard"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 2: Write `.gitignore`**

```gitignore
__pycache__/
*.py[cod]
*.egg-info/
.eggs/
build/
dist/
.venv/
venv/
.pytest_cache/
.ruff_cache/
.pyright/
*.json.schema
```

- [ ] **Step 3: Create venv and install dev deps**

Run: `python3 -m venv .venv && .venv/bin/pip install -e ".[dev,api]"`
Expected: installs forgelab editable + pydantic, fastapi, pytest, httpx, ruff, pyright.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml .gitignore
git commit -m "build: add project metadata and tooling config"
```

---

## Task 2: Spec version module

**Files:**
- Create: `forgelab/__init__.py`
- Create: `forgelab/spec/__init__.py`
- Create: `forgelab/spec/version.py`
- Test: `tests/test_spec.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_spec.py`:

```python
from forgelab.spec.version import SPEC_VERSION, is_compatible


def test_spec_version_is_semver_string():
    assert isinstance(SPEC_VERSION, str)
    parts = SPEC_VERSION.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)


def test_same_major_is_compatible():
    major = SPEC_VERSION.split(".")[0]
    assert is_compatible(f"{major}.0.0") is True


def test_different_major_is_incompatible():
    assert is_compatible("999.0.0") is False


def test_malformed_version_is_incompatible():
    assert is_compatible("not-a-version") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_spec.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'forgelab.spec.version'`

- [ ] **Step 3: Write the package root and version module**

Create `forgelab/__init__.py`:

```python
"""ForgeLab — the universal design interchange format and compiler."""

from forgelab.spec.version import SPEC_VERSION

__all__ = ["SPEC_VERSION", "__version__"]
__version__ = "0.1.0"
```

Create `forgelab/spec/version.py`:

```python
"""ForgeLab spec versioning.

Every ForgeDocument declares a ``forgelab_version`` so tools can reason about
long-term compatibility. Compatibility is determined by the major version:
documents with a different major version than the running library are rejected.
"""

SPEC_VERSION = "0.1.0"


def is_compatible(version: str) -> bool:
    """Return True if ``version`` shares this library's spec major version."""
    try:
        doc_major = int(version.split(".")[0])
        spec_major = int(SPEC_VERSION.split(".")[0])
    except (ValueError, IndexError):
        return False
    return doc_major == spec_major
```

Create `forgelab/spec/__init__.py`:

```python
"""The ForgeLab intermediate representation (IR)."""

from forgelab.spec.version import SPEC_VERSION, is_compatible

__all__ = ["SPEC_VERSION", "is_compatible"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_spec.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add forgelab/__init__.py forgelab/spec/__init__.py forgelab/spec/version.py tests/test_spec.py
git commit -m "feat(spec): add spec versioning with major-version compatibility"
```

---

## Task 3: Spec models (ForgeDocument)

**Files:**
- Create: `forgelab/spec/models.py`
- Modify: `forgelab/spec/__init__.py`
- Test: `tests/test_spec.py` (append)

- [ ] **Step 1: Write the failing test (append to `tests/test_spec.py`)**

```python
import pytest
from pydantic import ValidationError

from forgelab.spec.models import Domain, ForgeDocument, Node


def _valid_doc_dict():
    return {
        "forgelab_version": SPEC_VERSION,
        "domain": "hardware",
        "meta": {"name": "blinky", "generator": "test"},
        "nodes": [
            {"id": "r1", "type": "component", "props": {"value": "330R"}, "children": []}
        ],
    }


def test_valid_document_parses():
    doc = ForgeDocument.model_validate(_valid_doc_dict())
    assert doc.forgelab_version == SPEC_VERSION
    assert doc.domain == Domain.HARDWARE
    assert doc.nodes[0].id == "r1"


def test_document_requires_forgelab_version():
    data = _valid_doc_dict()
    del data["forgelab_version"]
    with pytest.raises(ValidationError):
        ForgeDocument.model_validate(data)


def test_unknown_domain_rejected():
    data = _valid_doc_dict()
    data["domain"] = "quantum"
    with pytest.raises(ValidationError):
        ForgeDocument.model_validate(data)


def test_node_children_nest():
    node = Node.model_validate(
        {"id": "p", "type": "group", "children": [{"id": "c", "type": "component"}]}
    )
    assert node.children[0].id == "c"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_spec.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'forgelab.spec.models'`

- [ ] **Step 3: Write `forgelab/spec/models.py`**

```python
"""The ForgeLab IR data models.

These models are intentionally generic: a ForgeDocument is a typed envelope
(version + domain + metadata) wrapping a graph of generic ``Node`` objects.
Domain-specific node vocabularies are layered on top in later work.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Domain(str, Enum):
    """Launch domains ForgeLab targets."""

    HARDWARE = "hardware"
    MECHANICAL = "mechanical"
    THREED = "threed"


class DocumentMeta(BaseModel):
    """Free-form-ish metadata about a document."""

    model_config = ConfigDict(extra="allow")

    name: str
    generator: str | None = None
    description: str | None = None


class Node(BaseModel):
    """A generic node in the ForgeLab design graph."""

    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    props: dict[str, Any] = Field(default_factory=dict)
    children: list[Node] = Field(default_factory=list)


class ForgeDocument(BaseModel):
    """Root of a ForgeLab design document.

    ``forgelab_version`` declares which spec version the document conforms to.
    """

    model_config = ConfigDict(extra="forbid")

    forgelab_version: str
    domain: Domain
    meta: DocumentMeta
    nodes: list[Node] = Field(default_factory=list)


Node.model_rebuild()
```

- [ ] **Step 4: Update `forgelab/spec/__init__.py`**

```python
"""The ForgeLab intermediate representation (IR)."""

from forgelab.spec.models import Domain, DocumentMeta, ForgeDocument, Node
from forgelab.spec.version import SPEC_VERSION, is_compatible

__all__ = [
    "SPEC_VERSION",
    "is_compatible",
    "Domain",
    "DocumentMeta",
    "ForgeDocument",
    "Node",
]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_spec.py -v`
Expected: PASS (8 passed)

- [ ] **Step 6: Commit**

```bash
git add forgelab/spec/models.py forgelab/spec/__init__.py tests/test_spec.py
git commit -m "feat(spec): add ForgeDocument, Node, and Domain IR models"
```

---

## Task 4: JSON Schema export

**Files:**
- Create: `forgelab/spec/schema.py`
- Modify: `forgelab/spec/__init__.py`
- Test: `tests/test_spec.py` (append)

- [ ] **Step 1: Write the failing test (append to `tests/test_spec.py`)**

```python
from forgelab.spec.schema import json_schema


def test_json_schema_describes_forge_document():
    schema = json_schema()
    assert schema["title"] == "ForgeDocument"
    assert "forgelab_version" in schema["properties"]
    assert "forgelab_version" in schema["required"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_spec.py::test_json_schema_describes_forge_document -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'forgelab.spec.schema'`

- [ ] **Step 3: Write `forgelab/spec/schema.py`**

```python
"""Export the ForgeLab IR as JSON Schema for non-Python consumers."""

from typing import Any

from forgelab.spec.models import ForgeDocument


def json_schema() -> dict[str, Any]:
    """Return the JSON Schema for a ForgeDocument."""
    return ForgeDocument.model_json_schema()
```

- [ ] **Step 4: Update `forgelab/spec/__init__.py` exports**

Add `from forgelab.spec.schema import json_schema` and append `"json_schema"` to `__all__`.

```python
"""The ForgeLab intermediate representation (IR)."""

from forgelab.spec.models import Domain, DocumentMeta, ForgeDocument, Node
from forgelab.spec.schema import json_schema
from forgelab.spec.version import SPEC_VERSION, is_compatible

__all__ = [
    "SPEC_VERSION",
    "is_compatible",
    "Domain",
    "DocumentMeta",
    "ForgeDocument",
    "Node",
    "json_schema",
]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_spec.py -v`
Expected: PASS (9 passed)

- [ ] **Step 6: Commit**

```bash
git add forgelab/spec/schema.py forgelab/spec/__init__.py tests/test_spec.py
git commit -m "feat(spec): add JSON Schema export"
```

---

## Task 5: Core errors and validate()

**Files:**
- Create: `forgelab/core/__init__.py`
- Create: `forgelab/core/errors.py`
- Create: `forgelab/core/validate.py`
- Test: `tests/test_core.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_core.py`:

```python
import pytest

from forgelab.core import IncompatibleVersionError, validate
from forgelab.spec import SPEC_VERSION, ForgeDocument


def _valid_doc_dict():
    return {
        "forgelab_version": SPEC_VERSION,
        "domain": "hardware",
        "meta": {"name": "blinky", "generator": "test"},
        "nodes": [{"id": "r1", "type": "component"}],
    }


def test_validate_returns_forge_document():
    doc = validate(_valid_doc_dict())
    assert isinstance(doc, ForgeDocument)
    assert doc.meta.name == "blinky"


def test_validate_rejects_incompatible_version():
    data = _valid_doc_dict()
    data["forgelab_version"] = "999.0.0"
    with pytest.raises(IncompatibleVersionError):
        validate(data)


def test_validate_rejects_malformed_document():
    with pytest.raises(Exception):
        validate({"forgelab_version": SPEC_VERSION})  # missing domain/meta
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_core.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'forgelab.core'`

- [ ] **Step 3: Write `forgelab/core/errors.py`**

```python
"""ForgeLab error hierarchy."""


class ForgeError(Exception):
    """Base class for all ForgeLab errors."""


class IncompatibleVersionError(ForgeError):
    """Raised when a document's spec version is incompatible with this library."""


class UnknownToolError(ForgeError):
    """Raised when no importer/exporter is registered for a tool name."""
```

- [ ] **Step 4: Write `forgelab/core/validate.py`**

```python
"""Validate untrusted input against the ForgeLab IR."""

from typing import Any

from forgelab.core.errors import IncompatibleVersionError
from forgelab.spec import ForgeDocument
from forgelab.spec.version import is_compatible


def validate(data: dict[str, Any]) -> ForgeDocument:
    """Parse and validate ``data`` into a ForgeDocument.

    Raises:
        IncompatibleVersionError: if the document's spec major version differs.
        pydantic.ValidationError: if the document is structurally invalid.
    """
    version = data.get("forgelab_version")
    if not isinstance(version, str) or not is_compatible(version):
        raise IncompatibleVersionError(
            f"Document forgelab_version {version!r} is not compatible with this library."
        )
    return ForgeDocument.model_validate(data)
```

- [ ] **Step 5: Write `forgelab/core/__init__.py`**

```python
"""The ForgeLab compiler core: validation, registry, and pipeline."""

from forgelab.core.errors import (
    ForgeError,
    IncompatibleVersionError,
    UnknownToolError,
)
from forgelab.core.validate import validate

__all__ = [
    "ForgeError",
    "IncompatibleVersionError",
    "UnknownToolError",
    "validate",
]
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_core.py -v`
Expected: PASS (3 passed)

- [ ] **Step 7: Commit**

```bash
git add forgelab/core/__init__.py forgelab/core/errors.py forgelab/core/validate.py tests/test_core.py
git commit -m "feat(core): add error hierarchy and validate()"
```

---

## Task 6: Importer/Exporter base ABCs and registry

**Files:**
- Create: `forgelab/importers/__init__.py`
- Create: `forgelab/importers/base.py`
- Create: `forgelab/exporters/__init__.py`
- Create: `forgelab/exporters/base.py`
- Create: `forgelab/core/registry.py`
- Modify: `forgelab/core/__init__.py`
- Test: `tests/test_core.py` (append)

- [ ] **Step 1: Write the failing test (append to `tests/test_core.py`)**

```python
from forgelab.core import UnknownToolError
from forgelab.core.registry import Registry
from forgelab.exporters.base import Exporter
from forgelab.importers.base import Importer
from forgelab.spec import ForgeDocument


class _FakeImporter(Importer):
    tool_name = "fake"

    def to_ir(self, source: bytes) -> ForgeDocument:  # pragma: no cover - trivial
        raise NotImplementedError


def test_registry_register_and_get():
    reg = Registry()
    reg.register_importer(_FakeImporter)
    assert reg.get_importer("fake") is _FakeImporter


def test_registry_unknown_tool_raises():
    reg = Registry()
    with pytest.raises(UnknownToolError):
        reg.get_importer("missing")


def test_importer_is_abstract():
    with pytest.raises(TypeError):
        Importer()  # type: ignore[abstract]


def test_exporter_is_abstract():
    with pytest.raises(TypeError):
        Exporter()  # type: ignore[abstract]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_core.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'forgelab.importers'`

- [ ] **Step 3: Write `forgelab/importers/base.py`**

```python
"""Base class for importers: native tool format -> ForgeLab IR."""

from abc import ABC, abstractmethod

from forgelab.spec import ForgeDocument


class Importer(ABC):
    """Convert a tool's native file bytes into a ForgeDocument.

    Subclasses set ``tool_name`` and implement ``to_ir``.
    """

    tool_name: str = ""

    @abstractmethod
    def to_ir(self, source: bytes) -> ForgeDocument:
        """Parse ``source`` bytes into a validated ForgeDocument."""
        raise NotImplementedError
```

- [ ] **Step 4: Write `forgelab/exporters/base.py`**

```python
"""Base class for exporters: ForgeLab IR -> native tool format."""

from abc import ABC, abstractmethod

from forgelab.spec import ForgeDocument


class Exporter(ABC):
    """Convert a ForgeDocument into a tool's native file bytes.

    Subclasses set ``tool_name`` and implement ``from_ir``.
    """

    tool_name: str = ""

    @abstractmethod
    def from_ir(self, document: ForgeDocument) -> bytes:
        """Serialize ``document`` into the target tool's native bytes."""
        raise NotImplementedError
```

- [ ] **Step 5: Write the importers/exporters package `__init__.py` files**

Create `forgelab/importers/__init__.py`:

```python
"""Importers: native tool formats -> ForgeLab IR."""

from forgelab.importers.base import Importer

__all__ = ["Importer"]
```

Create `forgelab/exporters/__init__.py`:

```python
"""Exporters: ForgeLab IR -> native tool formats."""

from forgelab.exporters.base import Exporter

__all__ = ["Exporter"]
```

- [ ] **Step 6: Write `forgelab/core/registry.py`**

```python
"""Registry mapping tool names to importer/exporter classes."""

from forgelab.core.errors import UnknownToolError
from forgelab.exporters.base import Exporter
from forgelab.importers.base import Importer


class Registry:
    """Holds importer/exporter classes keyed by tool name."""

    def __init__(self) -> None:
        self._importers: dict[str, type[Importer]] = {}
        self._exporters: dict[str, type[Exporter]] = {}

    def register_importer(self, importer: type[Importer]) -> None:
        self._importers[importer.tool_name] = importer

    def register_exporter(self, exporter: type[Exporter]) -> None:
        self._exporters[exporter.tool_name] = exporter

    def get_importer(self, tool_name: str) -> type[Importer]:
        try:
            return self._importers[tool_name]
        except KeyError:
            raise UnknownToolError(f"No importer registered for tool {tool_name!r}") from None

    def get_exporter(self, tool_name: str) -> type[Exporter]:
        try:
            return self._exporters[tool_name]
        except KeyError:
            raise UnknownToolError(f"No exporter registered for tool {tool_name!r}") from None
```

- [ ] **Step 7: Update `forgelab/core/__init__.py`**

```python
"""The ForgeLab compiler core: validation, registry, and pipeline."""

from forgelab.core.errors import (
    ForgeError,
    IncompatibleVersionError,
    UnknownToolError,
)
from forgelab.core.registry import Registry
from forgelab.core.validate import validate

__all__ = [
    "ForgeError",
    "IncompatibleVersionError",
    "UnknownToolError",
    "Registry",
    "validate",
]
```

- [ ] **Step 8: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_core.py -v`
Expected: PASS (7 passed)

- [ ] **Step 9: Commit**

```bash
git add forgelab/importers forgelab/exporters forgelab/core/registry.py forgelab/core/__init__.py tests/test_core.py
git commit -m "feat(core): add importer/exporter ABCs and tool registry"
```

---

## Task 7: Domain importer/exporter stubs

**Files:**
- Create: `forgelab/importers/hardware.py`, `forgelab/importers/mechanical.py`, `forgelab/importers/threed.py`
- Create: `forgelab/exporters/hardware.py`, `forgelab/exporters/mechanical.py`, `forgelab/exporters/threed.py`
- Test: `tests/test_stubs.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_stubs.py`:

```python
import pytest

from forgelab.exporters.hardware import KiCadExporter
from forgelab.importers.hardware import KiCadImporter
from forgelab.importers.mechanical import FreeCADImporter
from forgelab.importers.threed import BlenderImporter
from forgelab.spec import Domain, DocumentMeta, ForgeDocument, SPEC_VERSION


def test_importer_stub_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        KiCadImporter().to_ir(b"")


def test_exporter_stub_raises_not_implemented():
    doc = ForgeDocument(
        forgelab_version=SPEC_VERSION,
        domain=Domain.HARDWARE,
        meta=DocumentMeta(name="x"),
    )
    with pytest.raises(NotImplementedError):
        KiCadExporter().from_ir(doc)


def test_stub_tool_names_set():
    assert KiCadImporter.tool_name == "kicad"
    assert FreeCADImporter.tool_name == "freecad"
    assert BlenderImporter.tool_name == "blender"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_stubs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'forgelab.importers.hardware'`

- [ ] **Step 3: Write `forgelab/importers/hardware.py`**

```python
"""Hardware-domain importers (KiCad, Altium, Gerber) -> ForgeLab IR.

These are stubs. Implementations land in dedicated follow-up work.
"""

from forgelab.importers.base import Importer
from forgelab.spec import ForgeDocument


class KiCadImporter(Importer):
    """Import a KiCad project/schematic into ForgeLab IR. (stub)"""

    tool_name = "kicad"

    def to_ir(self, source: bytes) -> ForgeDocument:
        raise NotImplementedError("KiCad import is not implemented yet.")


class AltiumImporter(Importer):
    """Import an Altium design into ForgeLab IR. (stub)"""

    tool_name = "altium"

    def to_ir(self, source: bytes) -> ForgeDocument:
        raise NotImplementedError("Altium import is not implemented yet.")


class GerberImporter(Importer):
    """Import Gerber fabrication data into ForgeLab IR. (stub)"""

    tool_name = "gerber"

    def to_ir(self, source: bytes) -> ForgeDocument:
        raise NotImplementedError("Gerber import is not implemented yet.")
```

- [ ] **Step 4: Write `forgelab/importers/mechanical.py`**

```python
"""Mechanical-CAD importers (Fusion 360, FreeCAD) -> ForgeLab IR. (stubs)"""

from forgelab.importers.base import Importer
from forgelab.spec import ForgeDocument


class Fusion360Importer(Importer):
    """Import a Fusion 360 model into ForgeLab IR. (stub)"""

    tool_name = "fusion360"

    def to_ir(self, source: bytes) -> ForgeDocument:
        raise NotImplementedError("Fusion 360 import is not implemented yet.")


class FreeCADImporter(Importer):
    """Import a FreeCAD model into ForgeLab IR. (stub)"""

    tool_name = "freecad"

    def to_ir(self, source: bytes) -> ForgeDocument:
        raise NotImplementedError("FreeCAD import is not implemented yet.")
```

- [ ] **Step 5: Write `forgelab/importers/threed.py`**

```python
"""3D / game importers (Blender, Unreal Engine) -> ForgeLab IR. (stubs)"""

from forgelab.importers.base import Importer
from forgelab.spec import ForgeDocument


class BlenderImporter(Importer):
    """Import a Blender scene into ForgeLab IR. (stub)"""

    tool_name = "blender"

    def to_ir(self, source: bytes) -> ForgeDocument:
        raise NotImplementedError("Blender import is not implemented yet.")


class UnrealImporter(Importer):
    """Import an Unreal Engine asset into ForgeLab IR. (stub)"""

    tool_name = "unreal"

    def to_ir(self, source: bytes) -> ForgeDocument:
        raise NotImplementedError("Unreal Engine import is not implemented yet.")
```

- [ ] **Step 6: Write `forgelab/exporters/hardware.py`**

```python
"""Hardware-domain exporters (KiCad, Altium, Gerber) from ForgeLab IR. (stubs)"""

from forgelab.exporters.base import Exporter
from forgelab.spec import ForgeDocument


class KiCadExporter(Exporter):
    """Export ForgeLab IR to a KiCad project. (stub)"""

    tool_name = "kicad"

    def from_ir(self, document: ForgeDocument) -> bytes:
        raise NotImplementedError("KiCad export is not implemented yet.")


class AltiumExporter(Exporter):
    """Export ForgeLab IR to an Altium design. (stub)"""

    tool_name = "altium"

    def from_ir(self, document: ForgeDocument) -> bytes:
        raise NotImplementedError("Altium export is not implemented yet.")


class GerberExporter(Exporter):
    """Export ForgeLab IR to Gerber fabrication data. (stub)"""

    tool_name = "gerber"

    def from_ir(self, document: ForgeDocument) -> bytes:
        raise NotImplementedError("Gerber export is not implemented yet.")
```

- [ ] **Step 7: Write `forgelab/exporters/mechanical.py`**

```python
"""Mechanical-CAD exporters (Fusion 360, FreeCAD) from ForgeLab IR. (stubs)"""

from forgelab.exporters.base import Exporter
from forgelab.spec import ForgeDocument


class Fusion360Exporter(Exporter):
    """Export ForgeLab IR to a Fusion 360 model. (stub)"""

    tool_name = "fusion360"

    def from_ir(self, document: ForgeDocument) -> bytes:
        raise NotImplementedError("Fusion 360 export is not implemented yet.")


class FreeCADExporter(Exporter):
    """Export ForgeLab IR to a FreeCAD model. (stub)"""

    tool_name = "freecad"

    def from_ir(self, document: ForgeDocument) -> bytes:
        raise NotImplementedError("FreeCAD export is not implemented yet.")
```

- [ ] **Step 8: Write `forgelab/exporters/threed.py`**

```python
"""3D / game exporters (Blender, Unreal Engine) from ForgeLab IR. (stubs)"""

from forgelab.exporters.base import Exporter
from forgelab.spec import ForgeDocument


class BlenderExporter(Exporter):
    """Export ForgeLab IR to a Blender scene. (stub)"""

    tool_name = "blender"

    def from_ir(self, document: ForgeDocument) -> bytes:
        raise NotImplementedError("Blender export is not implemented yet.")


class UnrealExporter(Exporter):
    """Export ForgeLab IR to an Unreal Engine asset. (stub)"""

    tool_name = "unreal"

    def from_ir(self, document: ForgeDocument) -> bytes:
        raise NotImplementedError("Unreal Engine export is not implemented yet.")
```

- [ ] **Step 9: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_stubs.py -v`
Expected: PASS (3 passed)

- [ ] **Step 10: Commit**

```bash
git add forgelab/importers forgelab/exporters tests/test_stubs.py
git commit -m "feat(domains): add hardware/mechanical/3d importer+exporter stubs"
```

---

## Task 8: Compiler pipeline

**Files:**
- Create: `forgelab/core/pipeline.py`
- Modify: `forgelab/core/__init__.py`
- Test: `tests/test_core.py` (append)

- [ ] **Step 1: Write the failing test (append to `tests/test_core.py`)**

```python
from forgelab.core.pipeline import default_registry, transform


def test_default_registry_has_kicad_importer():
    reg = default_registry()
    assert reg.get_importer("kicad").tool_name == "kicad"
    assert reg.get_exporter("blender").tool_name == "blender"


def test_transform_is_identity_by_default():
    doc = validate(_valid_doc_dict())
    out = transform(doc, passes=[])
    assert out == doc
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_core.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'forgelab.core.pipeline'`

- [ ] **Step 3: Write `forgelab/core/pipeline.py`**

```python
"""The ForgeLab compiler pipeline: import -> validate -> transform -> export.

This wires the registry to the bundled domain stubs and provides a transform
hook. Transform passes are callables ``ForgeDocument -> ForgeDocument``; the
default pipeline is the identity (no passes), ready for real passes later.
"""

from collections.abc import Callable, Sequence

from forgelab.core.registry import Registry
from forgelab.exporters.hardware import AltiumExporter, GerberExporter, KiCadExporter
from forgelab.exporters.mechanical import FreeCADExporter, Fusion360Exporter
from forgelab.exporters.threed import BlenderExporter, UnrealExporter
from forgelab.importers.hardware import AltiumImporter, GerberImporter, KiCadImporter
from forgelab.importers.mechanical import FreeCADImporter, Fusion360Importer
from forgelab.importers.threed import BlenderImporter, UnrealImporter
from forgelab.spec import ForgeDocument

TransformPass = Callable[[ForgeDocument], ForgeDocument]

_IMPORTERS = [
    KiCadImporter, AltiumImporter, GerberImporter,
    Fusion360Importer, FreeCADImporter,
    BlenderImporter, UnrealImporter,
]
_EXPORTERS = [
    KiCadExporter, AltiumExporter, GerberExporter,
    Fusion360Exporter, FreeCADExporter,
    BlenderExporter, UnrealExporter,
]


def default_registry() -> Registry:
    """Return a Registry pre-populated with the bundled domain stubs."""
    reg = Registry()
    for imp in _IMPORTERS:
        reg.register_importer(imp)
    for exp in _EXPORTERS:
        reg.register_exporter(exp)
    return reg


def transform(
    document: ForgeDocument, passes: Sequence[TransformPass] = ()
) -> ForgeDocument:
    """Apply transform passes in order. With no passes this is the identity."""
    for p in passes:
        document = p(document)
    return document
```

- [ ] **Step 4: Update `forgelab/core/__init__.py`**

```python
"""The ForgeLab compiler core: validation, registry, and pipeline."""

from forgelab.core.errors import (
    ForgeError,
    IncompatibleVersionError,
    UnknownToolError,
)
from forgelab.core.pipeline import default_registry, transform
from forgelab.core.registry import Registry
from forgelab.core.validate import validate

__all__ = [
    "ForgeError",
    "IncompatibleVersionError",
    "UnknownToolError",
    "Registry",
    "default_registry",
    "transform",
    "validate",
]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_core.py -v`
Expected: PASS (9 passed)

- [ ] **Step 6: Commit**

```bash
git add forgelab/core/pipeline.py forgelab/core/__init__.py tests/test_core.py
git commit -m "feat(core): add compiler pipeline with default registry and transform hook"
```

---

## Task 9: AI SDK helpers

**Files:**
- Create: `forgelab/sdk/__init__.py`
- Test: `tests/test_sdk.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_sdk.py`:

```python
import json

from forgelab.sdk import new_document, load, dump
from forgelab.spec import Domain, ForgeDocument, SPEC_VERSION


def test_new_document_stamps_version():
    doc = new_document(domain="hardware", name="blinky")
    assert isinstance(doc, ForgeDocument)
    assert doc.forgelab_version == SPEC_VERSION
    assert doc.domain == Domain.HARDWARE
    assert doc.meta.name == "blinky"


def test_dump_then_load_roundtrips():
    doc = new_document(domain="threed", name="scene")
    text = dump(doc)
    assert isinstance(text, str)
    restored = load(json.loads(text) if False else text)
    assert restored == doc
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_sdk.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'forgelab.sdk'`

- [ ] **Step 3: Write `forgelab/sdk/__init__.py`**

```python
"""The ForgeLab AI SDK.

Ergonomic helpers for AI agents to build, read, and serialize ForgeLab IR
without touching Pydantic internals. Everything an agent emits is plain JSON.
"""

import json

from forgelab.core import validate
from forgelab.spec import Domain, DocumentMeta, ForgeDocument
from forgelab.spec.version import SPEC_VERSION

__all__ = ["new_document", "load", "dump", "SPEC_VERSION"]


def new_document(domain: str, name: str, generator: str = "forgelab-sdk") -> ForgeDocument:
    """Create an empty, version-stamped ForgeDocument for ``domain``."""
    return ForgeDocument(
        forgelab_version=SPEC_VERSION,
        domain=Domain(domain),
        meta=DocumentMeta(name=name, generator=generator),
    )


def load(data: str | dict) -> ForgeDocument:
    """Validate JSON text or a dict into a ForgeDocument."""
    if isinstance(data, str):
        data = json.loads(data)
    return validate(data)


def dump(document: ForgeDocument, *, indent: int = 2) -> str:
    """Serialize a ForgeDocument to JSON text."""
    return document.model_dump_json(indent=indent)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_sdk.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add forgelab/sdk/__init__.py tests/test_sdk.py
git commit -m "feat(sdk): add agent helpers (new_document, load, dump)"
```

---

## Task 10: FastAPI compiler-as-a-service

**Files:**
- Create: `forgelab/api/__init__.py`
- Create: `forgelab/api/app.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_api.py`:

```python
from fastapi.testclient import TestClient

from forgelab.api.app import app
from forgelab.spec import SPEC_VERSION

client = TestClient(app)


def _valid_doc_dict():
    return {
        "forgelab_version": SPEC_VERSION,
        "domain": "hardware",
        "meta": {"name": "blinky", "generator": "test"},
        "nodes": [{"id": "r1", "type": "component"}],
    }


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["spec_version"] == SPEC_VERSION


def test_spec_returns_schema():
    r = client.get("/spec")
    assert r.status_code == 200
    assert r.json()["title"] == "ForgeDocument"


def test_validate_accepts_valid_document():
    r = client.post("/validate", json=_valid_doc_dict())
    assert r.status_code == 200
    assert r.json()["valid"] is True


def test_validate_rejects_bad_version():
    data = _valid_doc_dict()
    data["forgelab_version"] = "999.0.0"
    r = client.post("/validate", json=data)
    assert r.status_code == 400
    assert "valid" in r.json()
    assert r.json()["valid"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'forgelab.api'`

- [ ] **Step 3: Write `forgelab/api/app.py`**

```python
"""ForgeLab compiler-as-a-service (FastAPI).

Exposes the compiler over HTTP so AI agents can validate, import, export, and
transform ForgeLab IR. Import/export endpoints currently route to domain stubs
and return 501 until those land.
"""

from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from forgelab.core import (
    IncompatibleVersionError,
    UnknownToolError,
    default_registry,
    validate,
)
from forgelab.spec import SPEC_VERSION, json_schema

app = FastAPI(
    title="ForgeLab",
    summary="The LLVM of design — universal design IR + compiler.",
    version=SPEC_VERSION,
)
_registry = default_registry()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "spec_version": SPEC_VERSION}


@app.get("/spec")
def spec() -> dict[str, Any]:
    """Return the ForgeDocument JSON Schema."""
    return json_schema()


@app.post("/validate")
def validate_document(document: dict[str, Any]) -> JSONResponse:
    """Validate a posted ForgeLab document."""
    try:
        validate(document)
    except IncompatibleVersionError as exc:
        return JSONResponse(status_code=400, content={"valid": False, "error": str(exc)})
    except Exception as exc:  # pydantic ValidationError and friends
        return JSONResponse(status_code=400, content={"valid": False, "error": str(exc)})
    return JSONResponse(status_code=200, content={"valid": True})


@app.post("/export/{tool}")
def export_document(tool: str, document: dict[str, Any]) -> JSONResponse:
    """Export a document to a tool's native format (stubs return 501)."""
    try:
        doc = validate(document)
        exporter = _registry.get_exporter(tool)
    except UnknownToolError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=400, content={"valid": False, "error": str(exc)})
    try:
        exporter().from_ir(doc)
    except NotImplementedError as exc:
        return JSONResponse(status_code=501, content={"error": str(exc)})
    return JSONResponse(status_code=200, content={"ok": True})
```

- [ ] **Step 4: Write `forgelab/api/__init__.py`**

```python
"""ForgeLab HTTP API."""

from forgelab.api.app import app

__all__ = ["app"]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_api.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add forgelab/api tests/test_api.py
git commit -m "feat(api): add FastAPI compiler service (health, spec, validate, export)"
```

---

## Task 11: Sample example document

**Files:**
- Create: `examples/hardware/blinky.forge.json`
- Test: `tests/test_examples.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_examples.py`:

```python
import json
from pathlib import Path

from forgelab.core import validate

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_all_examples_validate():
    files = list(EXAMPLES.rglob("*.forge.json"))
    assert files, "expected at least one example document"
    for path in files:
        data = json.loads(path.read_text())
        validate(data)  # raises if invalid
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_examples.py -v`
Expected: FAIL — `AssertionError: expected at least one example document`

- [ ] **Step 3: Write `examples/hardware/blinky.forge.json`**

> Note: replace `"0.1.0"` with the current `SPEC_VERSION` value from `forgelab/spec/version.py` if it has changed.

```json
{
  "forgelab_version": "0.1.0",
  "domain": "hardware",
  "meta": {
    "name": "blinky",
    "generator": "forgelab-examples",
    "description": "A minimal LED blinker: one resistor and one LED."
  },
  "nodes": [
    {
      "id": "r1",
      "type": "component",
      "props": { "ref": "R1", "footprint": "0603", "value": "330R" },
      "children": []
    },
    {
      "id": "d1",
      "type": "component",
      "props": { "ref": "D1", "footprint": "0805", "value": "RED-LED" },
      "children": []
    },
    {
      "id": "net_led",
      "type": "net",
      "props": { "name": "LED_A", "connects": ["r1.2", "d1.1"] },
      "children": []
    }
  ]
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_examples.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add examples/hardware/blinky.forge.json tests/test_examples.py
git commit -m "feat(examples): add validating blinky hardware sample"
```

---

## Task 12: Docs — README, LICENSE, CONTRIBUTING, CHANGELOG

**Files:**
- Create: `README.md` (replace the stub)
- Create: `LICENSE`
- Create: `CONTRIBUTING.md`
- Create: `CHANGELOG.md`

- [ ] **Step 1: Write `LICENSE`**

Fetch the canonical Apache 2.0 text and write it verbatim to `LICENSE`:

Run: `curl -fsSL https://www.apache.org/licenses/LICENSE-2.0.txt -o LICENSE && head -2 LICENSE`
Expected: file begins with the Apache License header. If offline, paste the standard Apache-2.0 text. Append a copyright line: `Copyright 2026 ForgeLab Contributors`.

- [ ] **Step 2: Write `README.md`**

```markdown
# ForgeLab

**The LLVM of design.** ForgeLab is a universal design interchange format and
compiler that lets AI agents create, read, and transform design files across
tools and domains — without ever touching proprietary file formats.

ForgeLab defines a JSON-based **intermediate representation (IR)** that sits
between AI agents and design software. Any tool can *import* into ForgeLab IR;
any tool can *export* from it. Agents operate entirely in ForgeLab JSON.

```
native file ──import──▶ ForgeLab IR ──transform──▶ ForgeLab IR ──export──▶ native file
                          ▲                                        │
                          └──────────── AI agents ─────────────────┘
                                   (pure JSON, no proprietary formats)
```

## Why JSON?

The IR is JSON so it is **natively emittable by any LLM or AI agent** with no
special training. Every document declares a `forgelab_version` so tools can
reason about long-term compatibility.

## Launch domains

| Domain        | Tools (targeted)            |
| ------------- | --------------------------- |
| Hardware      | KiCad, Altium, Gerber       |
| Mechanical CAD| Fusion 360, FreeCAD         |
| 3D / Game     | Blender, Unreal Engine      |

> Importers and exporters for these tools are scaffolded as stubs today. The
> spec, validator, pipeline, SDK, and API are real and working.

## Install

```bash
pip install -e ".[dev,api]"
```

## Quickstart (SDK)

```python
from forgelab.sdk import new_document, dump, load

doc = new_document(domain="hardware", name="blinky")
text = dump(doc)          # JSON an agent can emit/consume
restored = load(text)     # validated back into a ForgeDocument
```

## Quickstart (API)

```bash
uvicorn forgelab.api.app:app --reload
```

| Method | Path             | Purpose                              |
| ------ | ---------------- | ------------------------------------ |
| GET    | `/health`        | Liveness + spec version              |
| GET    | `/spec`          | ForgeDocument JSON Schema            |
| POST   | `/validate`      | Validate a ForgeLab document         |
| POST   | `/export/{tool}` | Export IR to a tool (stub → 501)     |

## Repository layout

```
forgelab/
├── spec/        # IR models (Pydantic v2), versioning, JSON Schema export
├── core/        # validate(), registry, compiler pipeline, errors
├── importers/   # tool → IR  (base ABC + domain stubs)
├── exporters/   # IR → tool  (base ABC + domain stubs)
├── sdk/         # AI agent helpers
└── api/         # FastAPI compiler-as-a-service
```

## Status

Pre-alpha (v0.1). The IR, validation, pipeline, SDK, and API work end-to-end;
tool importers/exporters are stubs awaiting contribution.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Good first issues: implement an importer
or exporter for one tool against the `Importer`/`Exporter` base classes.

## License

[Apache 2.0](LICENSE).
```

- [ ] **Step 3: Write `CONTRIBUTING.md`**

```markdown
# Contributing to ForgeLab

Thanks for helping build the universal design interchange format!

## Development setup

```bash
git clone https://github.com/forgelab/forgelab
cd forgelab
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,api]"
```

## Workflow

1. Create a branch off `main`.
2. Write tests first (we use TDD). Tests live in `tests/`.
3. Implement until green.
4. Run the full check suite locally before pushing.

## Checks (must pass)

```bash
ruff check .          # lint
ruff format --check . # formatting
pyright               # type checking
pytest                # tests
```

CI runs all of these on every push and pull request.

## Adding an importer or exporter

This is the highest-leverage contribution. Each tool plugs in via a base class:

- Importers subclass `forgelab.importers.base.Importer`, set `tool_name`, and
  implement `to_ir(source: bytes) -> ForgeDocument`.
- Exporters subclass `forgelab.exporters.base.Exporter`, set `tool_name`, and
  implement `from_ir(document: ForgeDocument) -> bytes`.

Register new classes in `forgelab/core/pipeline.py:default_registry`. Importers
and exporters must depend on `forgelab.spec` only — never on each other.

## Spec changes

The IR lives in `forgelab/spec/`. Any change to `ForgeDocument` is a spec change:
bump `SPEC_VERSION` in `forgelab/spec/version.py` (major bump for breaking
changes) and note it in `CHANGELOG.md`.

## Commit style

Conventional commits: `feat:`, `fix:`, `docs:`, `test:`, `build:`, `refactor:`.

## Code of Conduct

Be excellent to each other. Harassment is not tolerated.
```

- [ ] **Step 4: Write `CHANGELOG.md`**

```markdown
# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Initial scaffold: `spec` IR models (`ForgeDocument`, `Node`, `Domain`) with a
  required `forgelab_version` field and major-version compatibility checks.
- `core` compiler: `validate()`, tool registry, and transform pipeline.
- Importer/exporter base ABCs plus stubs for KiCad, Altium, Gerber, Fusion 360,
  FreeCAD, Blender, and Unreal Engine.
- AI SDK helpers: `new_document`, `load`, `dump`.
- FastAPI compiler-as-a-service: `/health`, `/spec`, `/validate`, `/export/{tool}`.
- JSON Schema export of the IR.
- Tooling: Ruff, Pyright, Pytest, and GitHub Actions CI.

[Unreleased]: https://github.com/forgelab/forgelab/commits/main
```

- [ ] **Step 5: Commit**

```bash
git add README.md LICENSE CONTRIBUTING.md CHANGELOG.md
git commit -m "docs: add README, Apache-2.0 LICENSE, CONTRIBUTING, CHANGELOG"
```

---

## Task 13: CI workflow and final verification

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Write `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  check:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - name: Install
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev,api]"
      - name: Ruff lint
        run: ruff check .
      - name: Ruff format
        run: ruff format --check .
      - name: Pyright
        run: pyright
      - name: Pytest
        run: pytest
```

- [ ] **Step 2: Run the full local check suite**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pyright && .venv/bin/pytest`
Expected: ruff clean, pyright 0 errors, all tests pass. Fix any issues before committing (e.g. run `.venv/bin/ruff format .` if formatting fails).

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add lint, typecheck, and test workflow"
```

---

## Self-Review Notes

- **Spec coverage:** vision/README ✓ (T12), Apache-2.0 ✓ (T12), CONTRIBUTING ✓ (T12),
  spec backbone with `forgelab_version` ✓ (T2–T4), `core` validate/registry/pipeline ✓ (T5,T6,T8),
  importer/exporter stubs ✓ (T6,T7), SDK ✓ (T9), API compiler-as-a-service ✓ (T10),
  working slice (validate + example + API) ✓ (T5,T10,T11), Ruff/Pyright/Pytest/CI ✓ (T1,T13),
  errors `IncompatibleVersionError`/`UnknownToolError` ✓ (T5,T6).
- **Type consistency:** `Importer.to_ir`/`Exporter.from_ir`, `Registry.get_importer/get_exporter`,
  `tool_name`, `validate`, `default_registry`, `transform`, `new_document/load/dump`, `json_schema`
  used consistently across tasks.
- **Boundary rule:** importers/exporters import `forgelab.spec` only; `core.pipeline` is the single
  place that imports the domain stubs to assemble the registry.
- **Note on example version:** the example JSON hardcodes `0.1.0`; T11 step 3 flags keeping it in
  sync with `SPEC_VERSION`. `tests/test_examples.py` will fail loudly if they drift to an
  incompatible major.
