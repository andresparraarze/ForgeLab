# KiCad Round-Trip Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working `.kicad_pcb` → ForgeDocument → `.kicad_pcb` round-trip that preserves all components, nets, and board constraints, backed by a typed hardware spec layer and a shared S-expression format primitive.

**Architecture:** A zero-dependency S-expression parser/writer (`forgelab/formats/sexpr.py`) is shared by both sides. A typed hardware vocabulary (`forgelab/spec/hardware.py`) serializes into the generic `Node` graph (component/net/board nodes). The KiCad importer parses `.kicad_pcb` text into these typed models; the exporter rebuilds a functional `.kicad_pcb` from them. Correctness is proven by an IR-level semantic round-trip (`import → export → import` equality) since KiCad itself is not installed.

**Tech Stack:** Python 3.11+ (dev 3.14), Pydantic v2, pytest. No new runtime dependencies.

---

## Environment note for the implementer

Run all commands from the repo root `/home/andresparraarze/Documents/ForgeLab`. A virtualenv exists at `.venv`. Use `.venv/bin/pytest`, `.venv/bin/ruff`, and for type-checking put the venv on PATH so pyright resolves deps:

```bash
PATH="$PWD/.venv/bin:$PATH" pyright <paths>
```

The package is installed editable, so new modules under `forgelab/` are importable immediately. After each task, before committing, ensure `ruff check`, `ruff format`, pyright, and the relevant tests are clean. `Node` uses `extra="forbid"`, so only `id`/`type`/`props`/`children` are allowed on a node; all hardware data lives inside `props`.

---

## File Structure

Created:
- `forgelab/formats/__init__.py` — re-exports `parse`, `dumps`, `Symbol`, `SExprError`
- `forgelab/formats/sexpr.py` — generic S-expression tokenizer/parser/writer
- `forgelab/spec/hardware.py` — typed hardware models + node-type constants
- `forgelab/importers/hardware/__init__.py` — re-exports the three importers
- `forgelab/importers/hardware/kicad.py` — `KiCadImporter` + `KiCadParseError`
- `forgelab/importers/hardware/altium.py` — `AltiumImporter` stub (moved)
- `forgelab/importers/hardware/gerber.py` — `GerberImporter` stub (moved)
- `forgelab/exporters/hardware/__init__.py` — re-exports the three exporters
- `forgelab/exporters/hardware/kicad.py` — `KiCadExporter`
- `forgelab/exporters/hardware/altium.py` — `AltiumExporter` stub (moved)
- `forgelab/exporters/hardware/gerber.py` — `GerberExporter` stub (moved)
- `examples/hardware/blinky.kicad_pcb` — real example board
- `tests/test_sexpr.py`, `tests/test_spec_hardware.py`, `tests/test_kicad_importer.py`,
  `tests/test_kicad_exporter.py`, `tests/test_kicad_roundtrip.py`

Modified:
- `forgelab/spec/version.py` — `SPEC_VERSION = "0.2.0"`
- `forgelab/spec/__init__.py` — export hardware models + node-type constants
- `tests/test_stubs.py` — KiCad no longer a stub
- `examples/hardware/blinky.forge.json` — regenerated from the importer
- `CHANGELOG.md`, `CONTRIBUTING.md`

Deleted:
- `forgelab/importers/hardware.py`, `forgelab/exporters/hardware.py`

---

## Task 1: Spec version bump to 0.2.0

**Files:**
- Modify: `forgelab/spec/version.py`
- Test: `tests/test_spec.py` (existing tests already assert semver shape; add a value check)

- [ ] **Step 1: Write the failing test (append to `tests/test_spec.py`)**

```python
def test_spec_version_is_0_2_0():
    assert SPEC_VERSION == "0.2.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_spec.py::test_spec_version_is_0_2_0 -v`
Expected: FAIL — `assert '0.1.0' == '0.2.0'`

- [ ] **Step 3: Bump the version**

In `forgelab/spec/version.py` change the constant:

```python
SPEC_VERSION = "0.2.0"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_spec.py -q`
Expected: PASS (all spec tests, including the new one)

- [ ] **Step 5: Commit**

```bash
git add forgelab/spec/version.py tests/test_spec.py
git commit -m "feat(spec): bump SPEC_VERSION to 0.2.0 for hardware vocabulary"
```

---

## Task 2: S-expression parser

**Files:**
- Create: `forgelab/formats/__init__.py`
- Create: `forgelab/formats/sexpr.py`
- Test: `tests/test_sexpr.py`

Design notes for the implementer:
- Atoms parse to: bare tokens → `Symbol` (a `str` subclass), quoted tokens → plain `str`, numeric tokens → `int` or `float`.
- A `Symbol` is a `str` subclass so comparisons like `tree[0] == "kicad_pcb"` work, while the writer can tell symbols (emit bare) from strings (emit quoted).
- `dumps` quotes plain `str`, emits `Symbol`/numbers bare, and recurses into lists.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sexpr.py`:

```python
import pytest

from forgelab.formats.sexpr import Symbol, SExprError, dumps, parse


def test_parse_simple_list():
    tree = parse('(kicad_pcb (version 20221018))')
    assert tree[0] == "kicad_pcb"
    assert isinstance(tree[0], Symbol)
    assert tree[1][0] == "version"
    assert tree[1][1] == 20221018


def test_parse_quoted_string_vs_symbol():
    tree = parse('(property "Reference" R1)')
    assert tree[1] == "Reference"
    assert not isinstance(tree[1], Symbol)  # quoted -> plain str
    assert isinstance(tree[2], Symbol)      # bare  -> Symbol


def test_parse_floats():
    tree = parse('(at 100.5 -50.25 90)')
    assert tree[1] == 100.5
    assert tree[2] == -50.25
    assert tree[3] == 90


def test_parse_nested():
    tree = parse('(a (b (c 1)) (d 2))')
    assert tree[1][1][0] == "c"
    assert tree[1][1][1] == 1
    assert tree[2][1] == 2


def test_quoted_string_with_spaces_and_escapes():
    tree = parse('(name "hello world" "with \\"quote\\"")')
    assert tree[1] == "hello world"
    assert tree[2] == 'with "quote"'


def test_dumps_roundtrips_through_parse():
    tree = parse('(kicad_pcb (version 20221018) (net 1 "GND") (at 1.5 2.5 90))')
    assert parse(dumps(tree)) == tree


def test_dumps_quotes_strings_and_bares_symbols():
    text = dumps([Symbol("net"), 1, "GND"])
    assert text == '(net 1 "GND")'


def test_parse_malformed_raises():
    with pytest.raises(SExprError):
        parse('(unbalanced (parens)')
    with pytest.raises(SExprError):
        parse('nothing-here')  # top level must be a list
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_sexpr.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'forgelab.formats'`

- [ ] **Step 3: Write `forgelab/formats/sexpr.py`**

```python
"""A minimal, zero-dependency S-expression parser and writer.

Atoms parse as: quoted tokens -> plain ``str``; bare tokens -> ``Symbol`` (a
``str`` subclass); numeric tokens -> ``int``/``float``. Lists are Python lists.
The ``Symbol`` distinction lets the writer re-emit bare symbols without quotes
while quoting genuine strings.
"""

from __future__ import annotations

SExpr = "list | str | Symbol | int | float"


class Symbol(str):
    """A bare (unquoted) S-expression atom."""

    __slots__ = ()


class SExprError(ValueError):
    """Raised when S-expression text cannot be parsed."""


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c in "()":
            tokens.append(c)
            i += 1
        elif c == '"':
            j = i + 1
            buf: list[str] = []
            while j < n:
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j + 1])
                    j += 2
                elif text[j] == '"':
                    break
                else:
                    buf.append(text[j])
                    j += 1
            if j >= n:
                raise SExprError("unterminated string literal")
            tokens.append('"' + "".join(buf) + '"')
            i = j + 1
        else:
            j = i
            while j < n and text[j] not in ' \t\r\n()"':
                j += 1
            tokens.append(text[i:j])
            i = j
    return tokens


def _atom(token: str) -> str | Symbol | int | float:
    if token.startswith('"') and token.endswith('"'):
        return token[1:-1]
    try:
        return int(token)
    except ValueError:
        pass
    try:
        return float(token)
    except ValueError:
        pass
    return Symbol(token)


def parse(text: str) -> list:
    """Parse S-expression ``text`` whose top level is a single list."""
    tokens = _tokenize(text)
    if not tokens or tokens[0] != "(":
        raise SExprError("top-level S-expression must be a list")
    pos = 0

    def parse_list() -> list:
        nonlocal pos
        assert tokens[pos] == "("
        pos += 1
        out: list = []
        while pos < len(tokens):
            tok = tokens[pos]
            if tok == "(":
                out.append(parse_list())
            elif tok == ")":
                pos += 1
                return out
            else:
                out.append(_atom(tok))
                pos += 1
        raise SExprError("unbalanced parentheses")

    result = parse_list()
    if pos != len(tokens):
        raise SExprError("trailing tokens after top-level list")
    return result


def _dump_atom(value: object) -> str:
    if isinstance(value, Symbol):
        return str(value)
    if isinstance(value, bool):  # guard: bool is an int subclass
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value) if isinstance(value, float) else str(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    raise SExprError(f"cannot serialize atom of type {type(value).__name__}")


def dumps(tree: object, *, indent: int = 0, _level: int = 0) -> str:
    """Serialize an S-expression tree back to text.

    With ``indent == 0`` (default) the output is compact on one line per list.
    """
    if not isinstance(tree, list):
        return _dump_atom(tree)
    inner = " ".join(dumps(item, indent=indent) for item in tree)
    return f"({inner})"
```

- [ ] **Step 4: Write `forgelab/formats/__init__.py`**

```python
"""Neutral file-format primitives shared by importers and exporters."""

from forgelab.formats.sexpr import SExpr, SExprError, Symbol, dumps, parse

__all__ = ["SExpr", "SExprError", "Symbol", "dumps", "parse"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_sexpr.py -v`
Expected: PASS (8 passed)

- [ ] **Step 6: Lint, typecheck**

Run: `.venv/bin/ruff check forgelab/formats tests/test_sexpr.py && .venv/bin/ruff format forgelab/formats tests/test_sexpr.py && PATH="$PWD/.venv/bin:$PATH" pyright forgelab/formats`
Expected: clean, 0 errors. (If `SExpr = "..."` triggers a pyright complaint, leave it — it is a documentation alias string, not used as a type annotation anywhere.)

- [ ] **Step 7: Commit**

```bash
git add forgelab/formats tests/test_sexpr.py
git commit -m "feat(formats): add zero-dependency S-expression parser/writer"
```

---

## Task 3: Typed hardware spec models

**Files:**
- Create: `forgelab/spec/hardware.py`
- Modify: `forgelab/spec/__init__.py`
- Test: `tests/test_spec_hardware.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_spec_hardware.py`:

```python
import pytest
from pydantic import ValidationError

from forgelab.spec import (
    NODE_BOARD,
    NODE_COMPONENT,
    NODE_NET,
    BoardConstraints,
    BoardLayer,
    Component,
    DesignRules,
    Net,
    OutlineSegment,
    Pad,
)


def test_node_type_constants():
    assert NODE_COMPONENT == "component"
    assert NODE_NET == "net"
    assert NODE_BOARD == "board"


def test_component_roundtrips_through_dict():
    comp = Component(
        reference="R1",
        value="330R",
        footprint="Resistor_SMD:R_0603_1608Metric",
        layer="F.Cu",
        at=[100.0, 50.0, 0.0],
        pads=[Pad(number="1", net="LED_A"), Pad(number="2", net="GND")],
        uuid="abc",
    )
    restored = Component.model_validate(comp.model_dump())
    assert restored == comp
    assert restored.pads[0].net == "LED_A"


def test_component_at_must_have_three_values():
    with pytest.raises(ValidationError):
        Component(
            reference="R1",
            value="330R",
            footprint="x",
            layer="F.Cu",
            at=[1.0, 2.0],
        )


def test_net_and_board_validate():
    net = Net(code=1, name="GND")
    assert net.code == 1
    board = BoardConstraints(
        kicad_version="20221018",
        generator="pcbnew",
        layers=[BoardLayer(ordinal=0, canonical_name="F.Cu", layer_type="signal")],
        outline=[OutlineSegment(start=[0.0, 0.0], end=[10.0, 0.0])],
        design_rules=DesignRules(
            clearance=0.2, track_width=0.25, via_diameter=0.8, via_drill=0.4
        ),
    )
    assert board.layers[0].canonical_name == "F.Cu"
    assert board.design_rules.clearance == 0.2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_spec_hardware.py -v`
Expected: FAIL — `ImportError: cannot import name 'Component' from 'forgelab.spec'`

- [ ] **Step 3: Write `forgelab/spec/hardware.py`**

```python
"""Typed hardware (PCB) vocabulary for the ForgeLab IR.

These models describe printed-circuit-board concepts — components, pads, nets,
layers, and board constraints. They are not a new document root: they serialize
into the generic ``Node`` graph (see the node-type constants). Importers build
these models and store ``model_dump()`` in ``Node.props``; exporters rebuild
them with ``model_validate(node.props)``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

NODE_COMPONENT = "component"
NODE_NET = "net"
NODE_BOARD = "board"


class Pad(BaseModel):
    """A single pad on a component, and the net it connects to."""

    model_config = ConfigDict(extra="forbid")

    number: str
    net: str = ""


class Component(BaseModel):
    """A placed footprint on the board."""

    model_config = ConfigDict(extra="forbid")

    reference: str
    value: str
    footprint: str
    layer: str
    at: list[float]
    pads: list[Pad] = Field(default_factory=list)
    uuid: str | None = None

    @field_validator("at")
    @classmethod
    def _at_is_xyr(cls, value: list[float]) -> list[float]:
        if len(value) != 3:
            raise ValueError("at must be [x, y, rotation]")
        return value


class Net(BaseModel):
    """A named electrical net."""

    model_config = ConfigDict(extra="forbid")

    code: int
    name: str


class BoardLayer(BaseModel):
    """One entry in the board's layer stack."""

    model_config = ConfigDict(extra="forbid")

    ordinal: int
    canonical_name: str
    layer_type: str
    user_name: str | None = None


class OutlineSegment(BaseModel):
    """A straight segment of the board outline (Edge.Cuts)."""

    model_config = ConfigDict(extra="forbid")

    start: list[float]
    end: list[float]

    @field_validator("start", "end")
    @classmethod
    def _is_xy(cls, value: list[float]) -> list[float]:
        if len(value) != 2:
            raise ValueError("outline point must be [x, y]")
        return value


class DesignRules(BaseModel):
    """Core board design rules."""

    model_config = ConfigDict(extra="forbid")

    clearance: float
    track_width: float
    via_diameter: float
    via_drill: float


class BoardConstraints(BaseModel):
    """Document-level board constraints: stack, outline, and rules."""

    model_config = ConfigDict(extra="forbid")

    kicad_version: str
    generator: str
    layers: list[BoardLayer] = Field(default_factory=list)
    outline: list[OutlineSegment] = Field(default_factory=list)
    design_rules: DesignRules
```

- [ ] **Step 4: Update `forgelab/spec/__init__.py`**

Add the hardware imports and names. The file currently is:

```python
"""The ForgeLab intermediate representation (IR)."""

from forgelab.spec.models import DocumentMeta, Domain, ForgeDocument, Node
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

Replace it with:

```python
"""The ForgeLab intermediate representation (IR)."""

from forgelab.spec.hardware import (
    NODE_BOARD,
    NODE_COMPONENT,
    NODE_NET,
    BoardConstraints,
    BoardLayer,
    Component,
    DesignRules,
    Net,
    OutlineSegment,
    Pad,
)
from forgelab.spec.models import DocumentMeta, Domain, ForgeDocument, Node
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
    "NODE_BOARD",
    "NODE_COMPONENT",
    "NODE_NET",
    "BoardConstraints",
    "BoardLayer",
    "Component",
    "DesignRules",
    "Net",
    "OutlineSegment",
    "Pad",
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_spec_hardware.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Lint, typecheck**

Run: `.venv/bin/ruff check forgelab/spec tests/test_spec_hardware.py && .venv/bin/ruff format forgelab/spec tests/test_spec_hardware.py && PATH="$PWD/.venv/bin:$PATH" pyright forgelab/spec`
Expected: clean, 0 errors.

- [ ] **Step 7: Commit**

```bash
git add forgelab/spec/hardware.py forgelab/spec/__init__.py tests/test_spec_hardware.py
git commit -m "feat(spec): add typed hardware vocabulary (Component, Net, BoardConstraints)"
```

---

## Task 4: Restructure hardware importer/exporter into packages

This task only moves the existing stubs into packages and keeps everything green. KiCad is still a
stub after this task; it gets implemented in Tasks 6–7.

**Files:**
- Delete: `forgelab/importers/hardware.py`, `forgelab/exporters/hardware.py`
- Create: `forgelab/importers/hardware/__init__.py`, `altium.py`, `gerber.py`, and a temporary
  `kicad.py` stub
- Create: `forgelab/exporters/hardware/__init__.py`, `altium.py`, `gerber.py`, and a temporary
  `kicad.py` stub

- [ ] **Step 1: Delete the single-module files**

```bash
git rm forgelab/importers/hardware.py forgelab/exporters/hardware.py
```

- [ ] **Step 2: Create `forgelab/importers/hardware/altium.py`**

```python
"""Altium importer (stub)."""

from forgelab.importers.base import Importer
from forgelab.spec import ForgeDocument


class AltiumImporter(Importer):
    """Import an Altium design into ForgeLab IR. (stub)"""

    tool_name = "altium"

    def to_ir(self, source: bytes) -> ForgeDocument:
        raise NotImplementedError("Altium import is not implemented yet.")
```

- [ ] **Step 3: Create `forgelab/importers/hardware/gerber.py`**

```python
"""Gerber importer (stub)."""

from forgelab.importers.base import Importer
from forgelab.spec import ForgeDocument


class GerberImporter(Importer):
    """Import Gerber fabrication data into ForgeLab IR. (stub)"""

    tool_name = "gerber"

    def to_ir(self, source: bytes) -> ForgeDocument:
        raise NotImplementedError("Gerber import is not implemented yet.")
```

- [ ] **Step 4: Create a temporary `forgelab/importers/hardware/kicad.py` stub**

```python
"""KiCad importer (stub — implemented in a later task)."""

from forgelab.importers.base import Importer
from forgelab.spec import ForgeDocument


class KiCadImporter(Importer):
    """Import a KiCad PCB into ForgeLab IR. (stub)"""

    tool_name = "kicad"

    def to_ir(self, source: bytes) -> ForgeDocument:
        raise NotImplementedError("KiCad import is not implemented yet.")
```

- [ ] **Step 5: Create `forgelab/importers/hardware/__init__.py`**

```python
"""Hardware-domain importers (KiCad, Altium, Gerber) -> ForgeLab IR."""

from forgelab.importers.hardware.altium import AltiumImporter
from forgelab.importers.hardware.gerber import GerberImporter
from forgelab.importers.hardware.kicad import KiCadImporter

__all__ = ["AltiumImporter", "GerberImporter", "KiCadImporter"]
```

- [ ] **Step 6: Create the three exporter files**

Create `forgelab/exporters/hardware/altium.py`:

```python
"""Altium exporter (stub)."""

from forgelab.exporters.base import Exporter
from forgelab.spec import ForgeDocument


class AltiumExporter(Exporter):
    """Export ForgeLab IR to an Altium design. (stub)"""

    tool_name = "altium"

    def from_ir(self, document: ForgeDocument) -> bytes:
        raise NotImplementedError("Altium export is not implemented yet.")
```

Create `forgelab/exporters/hardware/gerber.py`:

```python
"""Gerber exporter (stub)."""

from forgelab.exporters.base import Exporter
from forgelab.spec import ForgeDocument


class GerberExporter(Exporter):
    """Export ForgeLab IR to Gerber fabrication data. (stub)"""

    tool_name = "gerber"

    def from_ir(self, document: ForgeDocument) -> bytes:
        raise NotImplementedError("Gerber export is not implemented yet.")
```

Create a temporary `forgelab/exporters/hardware/kicad.py` stub:

```python
"""KiCad exporter (stub — implemented in a later task)."""

from forgelab.exporters.base import Exporter
from forgelab.spec import ForgeDocument


class KiCadExporter(Exporter):
    """Export ForgeLab IR to a KiCad PCB. (stub)"""

    tool_name = "kicad"

    def from_ir(self, document: ForgeDocument) -> bytes:
        raise NotImplementedError("KiCad export is not implemented yet.")
```

- [ ] **Step 7: Create `forgelab/exporters/hardware/__init__.py`**

```python
"""Hardware-domain exporters (KiCad, Altium, Gerber) from ForgeLab IR."""

from forgelab.exporters.hardware.altium import AltiumExporter
from forgelab.exporters.hardware.gerber import GerberExporter
from forgelab.exporters.hardware.kicad import KiCadExporter

__all__ = ["AltiumExporter", "GerberExporter", "KiCadExporter"]
```

- [ ] **Step 8: Run the full suite to confirm nothing broke**

Run: `.venv/bin/pytest -q`
Expected: PASS — the existing `tests/test_stubs.py`, `tests/test_pipeline.py`, etc. still pass because `forgelab.importers.hardware` and `forgelab.exporters.hardware` still expose the same names.

- [ ] **Step 9: Lint, typecheck**

Run: `.venv/bin/ruff check forgelab/importers forgelab/exporters && .venv/bin/ruff format forgelab/importers forgelab/exporters && PATH="$PWD/.venv/bin:$PATH" pyright forgelab/importers forgelab/exporters`
Expected: clean, 0 errors.

- [ ] **Step 10: Commit**

```bash
git add -A forgelab/importers forgelab/exporters
git commit -m "refactor(domains): split hardware importer/exporter into packages"
```

---

## Task 5: Real example board `blinky.kicad_pcb`

The example is created before the importer so importer tests have a fixture. It is hand-written and
must parse with the Task 2 parser.

**Files:**
- Create: `examples/hardware/blinky.kicad_pcb`
- Test: `tests/test_kicad_importer.py` (only the "fixture parses" test in this task)

- [ ] **Step 1: Write `examples/hardware/blinky.kicad_pcb`**

```
(kicad_pcb (version 20221018) (generator pcbnew)
  (general (thickness 1.6))
  (paper "A4")
  (layers
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
    (44 "Edge.Cuts" user)
  )
  (setup
    (pad_to_mask_clearance 0)
    (clearance 0.2)
    (trace_width 0.25)
    (via_diameter 0.8)
    (via_drill 0.4)
  )
  (net 0 "")
  (net 1 "GND")
  (net 2 "+3V3")
  (net 3 "LED_A")
  (footprint "Resistor_SMD:R_0603_1608Metric" (layer "F.Cu")
    (uuid "11111111-1111-1111-1111-111111111111")
    (at 100 50 0)
    (property "Reference" "R1")
    (property "Value" "330R")
    (pad "1" smd roundrect (at -0.7875 0 0) (size 0.875 0.95) (layers "F.Cu") (net 2 "+3V3"))
    (pad "2" smd roundrect (at 0.7875 0 0) (size 0.875 0.95) (layers "F.Cu") (net 3 "LED_A"))
  )
  (footprint "LED_SMD:LED_0805_2012Metric" (layer "F.Cu")
    (uuid "22222222-2222-2222-2222-222222222222")
    (at 110 50 0)
    (property "Reference" "D1")
    (property "Value" "RED")
    (pad "1" smd roundrect (at -1 0 0) (size 1.2 1.4) (layers "F.Cu") (net 3 "LED_A"))
    (pad "2" smd roundrect (at 1 0 0) (size 1.2 1.4) (layers "F.Cu") (net 1 "GND"))
  )
  (gr_line (start 90 40) (end 130 40) (layer "Edge.Cuts") (width 0.1))
  (gr_line (start 130 40) (end 130 60) (layer "Edge.Cuts") (width 0.1))
  (gr_line (start 130 60) (end 90 60) (layer "Edge.Cuts") (width 0.1))
  (gr_line (start 90 60) (end 90 40) (layer "Edge.Cuts") (width 0.1))
)
```

- [ ] **Step 2: Write the fixture-parses test**

Create `tests/test_kicad_importer.py`:

```python
from pathlib import Path

from forgelab.formats import parse

FIXTURE = (
    Path(__file__).resolve().parent.parent / "examples" / "hardware" / "blinky.kicad_pcb"
)


def test_fixture_parses_as_kicad_pcb():
    tree = parse(FIXTURE.read_text())
    assert tree[0] == "kicad_pcb"
```

- [ ] **Step 3: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_kicad_importer.py -v`
Expected: PASS (1 passed). (If it fails to parse, the example has a syntax error — fix the example, not the parser.)

- [ ] **Step 4: Commit**

```bash
git add examples/hardware/blinky.kicad_pcb tests/test_kicad_importer.py
git commit -m "feat(examples): add real blinky.kicad_pcb board"
```

---

## Task 6: KiCad importer

**Files:**
- Modify (replace stub): `forgelab/importers/hardware/kicad.py`
- Test: `tests/test_kicad_importer.py` (append)

Design notes:
- Helper accessors over the parsed tree: `_find_all(node, tag)` returns child lists whose head is
  `tag`; `_find(node, tag)` returns the first or `None`; `_value(node, tag)` returns the first arg
  after `tag`.
- Net nodes are emitted **sorted by code** for a canonical IR (so round-trip equality holds
  regardless of source ordering).
- Component nodes are emitted in file order.
- Pads store the net **name** (not code).

- [ ] **Step 1: Write the failing tests (append to `tests/test_kicad_importer.py`)**

```python
from forgelab.importers.hardware.kicad import KiCadImporter, KiCadParseError
from forgelab.spec import (
    NODE_BOARD,
    NODE_COMPONENT,
    NODE_NET,
    BoardConstraints,
    Component,
    Net,
)
import pytest


def _import():
    return KiCadImporter().to_ir(FIXTURE.read_bytes())


def test_import_has_board_nets_components():
    doc = _import()
    boards = [n for n in doc.nodes if n.type == NODE_BOARD]
    nets = [n for n in doc.nodes if n.type == NODE_NET]
    comps = [n for n in doc.nodes if n.type == NODE_COMPONENT]
    assert len(boards) == 1
    assert len(nets) == 4  # "", GND, +3V3, LED_A
    assert len(comps) == 2


def test_import_components_have_expected_data():
    doc = _import()
    comps = {
        n.id: Component.model_validate(n.props)
        for n in doc.nodes
        if n.type == NODE_COMPONENT
    }
    r1 = comps["R1"]
    assert r1.value == "330R"
    assert r1.footprint == "Resistor_SMD:R_0603_1608Metric"
    assert r1.at == [100.0, 50.0, 0.0]
    assert {p.number: p.net for p in r1.pads} == {"1": "+3V3", "2": "LED_A"}
    d1 = comps["D1"]
    assert d1.value == "RED"
    assert {p.number: p.net for p in d1.pads} == {"1": "LED_A", "2": "GND"}


def test_import_board_constraints():
    doc = _import()
    board = next(n for n in doc.nodes if n.type == NODE_BOARD)
    bc = BoardConstraints.model_validate(board.props)
    assert bc.kicad_version == "20221018"
    assert bc.design_rules.clearance == 0.2
    assert bc.design_rules.track_width == 0.25
    assert len(bc.outline) == 4  # rectangle
    assert len(bc.layers) == 3


def test_import_nets_sorted_by_code():
    doc = _import()
    nets = [Net.model_validate(n.props) for n in doc.nodes if n.type == NODE_NET]
    assert [n.code for n in nets] == [0, 1, 2, 3]


def test_import_garbage_raises_parse_error():
    with pytest.raises(KiCadParseError):
        KiCadImporter().to_ir(b"not a kicad file")
    with pytest.raises(KiCadParseError):
        KiCadImporter().to_ir(b"(other_root (version 1))")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_kicad_importer.py -v`
Expected: FAIL — `ImportError: cannot import name 'KiCadParseError'` / stub raises `NotImplementedError`.

- [ ] **Step 3: Replace `forgelab/importers/hardware/kicad.py`**

```python
"""KiCad PCB (.kicad_pcb) importer: S-expression text -> ForgeLab IR.

Parses the KiCad board file into the typed hardware vocabulary and stores each
component/net/board as a node in the generic IR graph. Depends only on
``forgelab.spec`` and ``forgelab.formats`` (never on importers/exporters/core).
"""

from __future__ import annotations

from forgelab.formats import SExprError, parse
from forgelab.importers.base import Importer
from forgelab.spec import (
    NODE_BOARD,
    NODE_COMPONENT,
    NODE_NET,
    BoardConstraints,
    BoardLayer,
    Component,
    DesignRules,
    DocumentMeta,
    Domain,
    ForgeDocument,
    Net,
    Node,
    OutlineSegment,
    Pad,
)
from forgelab.spec.version import SPEC_VERSION


class KiCadParseError(SExprError):
    """Raised when a document is not a valid KiCad PCB."""


def _find_all(node: list, tag: str) -> list[list]:
    return [c for c in node if isinstance(c, list) and c and c[0] == tag]


def _find(node: list, tag: str) -> list | None:
    found = _find_all(node, tag)
    return found[0] if found else None


def _value(node: list, tag: str, default: object = None) -> object:
    child = _find(node, tag)
    if child is None or len(child) < 2:
        return default
    return child[1]


def _floats(values: list) -> list[float]:
    return [float(v) for v in values]


class KiCadImporter(Importer):
    """Import a KiCad PCB into ForgeLab IR."""

    tool_name = "kicad"

    def to_ir(self, source: bytes) -> ForgeDocument:
        try:
            tree = parse(source.decode("utf-8"))
        except SExprError as exc:
            raise KiCadParseError(str(exc)) from exc
        if not tree or tree[0] != "kicad_pcb":
            raise KiCadParseError("root element is not (kicad_pcb ...)")

        board = self._read_board(tree)
        nets = self._read_nets(tree)
        components = self._read_components(tree)

        nodes: list[Node] = [
            Node(id=NODE_BOARD, type=NODE_BOARD, props=board.model_dump())
        ]
        for net in sorted(nets, key=lambda n: n.code):
            nodes.append(
                Node(id=f"net:{net.code}", type=NODE_NET, props=net.model_dump())
            )
        for comp in components:
            nodes.append(
                Node(id=comp.reference, type=NODE_COMPONENT, props=comp.model_dump())
            )

        return ForgeDocument(
            forgelab_version=SPEC_VERSION,
            domain=Domain.HARDWARE,
            meta=DocumentMeta(name="blinky", generator="forgelab-kicad"),
            nodes=nodes,
        )

    def _read_board(self, tree: list) -> BoardConstraints:
        version = str(_value(tree, "version", "20221018"))
        generator = str(_value(tree, "generator", "pcbnew"))

        layers: list[BoardLayer] = []
        layers_block = _find(tree, "layers")
        if layers_block is not None:
            for entry in layers_block[1:]:
                if isinstance(entry, list) and len(entry) >= 3:
                    layers.append(
                        BoardLayer(
                            ordinal=int(entry[0]),
                            canonical_name=str(entry[1]),
                            layer_type=str(entry[2]),
                            user_name=str(entry[3]) if len(entry) > 3 else None,
                        )
                    )

        setup = _find(tree, "setup") or []
        rules = DesignRules(
            clearance=float(_value(setup, "clearance", 0.2)),
            track_width=float(_value(setup, "trace_width", 0.25)),
            via_diameter=float(_value(setup, "via_diameter", 0.8)),
            via_drill=float(_value(setup, "via_drill", 0.4)),
        )

        outline: list[OutlineSegment] = []
        for line in _find_all(tree, "gr_line"):
            layer = _value(line, "layer")
            if layer != "Edge.Cuts":
                continue
            start = _find(line, "start")
            end = _find(line, "end")
            if start and end:
                outline.append(
                    OutlineSegment(
                        start=_floats(start[1:3]), end=_floats(end[1:3])
                    )
                )

        return BoardConstraints(
            kicad_version=version,
            generator=generator,
            layers=layers,
            outline=outline,
            design_rules=rules,
        )

    def _read_nets(self, tree: list) -> list[Net]:
        nets: list[Net] = []
        for net in _find_all(tree, "net"):
            if len(net) >= 3:
                nets.append(Net(code=int(net[1]), name=str(net[2])))
            elif len(net) == 2:
                nets.append(Net(code=int(net[1]), name=""))
        return nets

    def _read_components(self, tree: list) -> list[Component]:
        components: list[Component] = []
        for fp in _find_all(tree, "footprint"):
            footprint_id = str(fp[1]) if len(fp) > 1 else ""
            layer = str(_value(fp, "layer", "F.Cu"))
            uuid = _value(fp, "uuid")
            at_node = _find(fp, "at")
            at = _floats(at_node[1:4]) if at_node else [0.0, 0.0, 0.0]
            if len(at) == 2:
                at = [at[0], at[1], 0.0]

            reference = ""
            value = ""
            for prop in _find_all(fp, "property"):
                if len(prop) >= 3 and prop[1] == "Reference":
                    reference = str(prop[2])
                elif len(prop) >= 3 and prop[1] == "Value":
                    value = str(prop[2])

            pads: list[Pad] = []
            for pad in _find_all(fp, "pad"):
                number = str(pad[1]) if len(pad) > 1 else ""
                net_node = _find(pad, "net")
                net_name = str(net_node[2]) if net_node and len(net_node) >= 3 else ""
                pads.append(Pad(number=number, net=net_name))

            components.append(
                Component(
                    reference=reference,
                    value=value,
                    footprint=footprint_id,
                    layer=layer,
                    at=at,
                    pads=pads,
                    uuid=str(uuid) if uuid is not None else None,
                )
            )
        return components
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_kicad_importer.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Lint, typecheck**

Run: `.venv/bin/ruff check forgelab/importers/hardware tests/test_kicad_importer.py && .venv/bin/ruff format forgelab/importers/hardware tests/test_kicad_importer.py && PATH="$PWD/.venv/bin:$PATH" pyright forgelab/importers/hardware`
Expected: clean, 0 errors.

- [ ] **Step 6: Commit**

```bash
git add forgelab/importers/hardware/kicad.py tests/test_kicad_importer.py
git commit -m "feat(kicad): implement KiCad PCB importer"
```

---

## Task 7: KiCad exporter

**Files:**
- Modify (replace stub): `forgelab/exporters/hardware/kicad.py`
- Test: `tests/test_kicad_exporter.py`

Design notes:
- Build the S-expr tree using `Symbol` for all tags and bare tokens, plain `str` for quoted values.
- Net code lookup: build `name -> code` from the board's net table; a pad whose net name is unknown
  or empty maps to code 0.
- Emit nets sorted by code; emit code-0 `""` net even if missing.
- Numbers: emit `int` when the float is integral (e.g. `100.0 -> 100`) so output matches the source
  style and the round-trip stays stable; otherwise emit the float.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_kicad_exporter.py`:

```python
from forgelab.exporters.hardware.kicad import KiCadExporter
from forgelab.formats import parse
from forgelab.spec import (
    NODE_BOARD,
    NODE_COMPONENT,
    NODE_NET,
    BoardConstraints,
    Component,
    DesignRules,
    DocumentMeta,
    Domain,
    ForgeDocument,
    Net,
    Pad,
)
from forgelab.spec.version import SPEC_VERSION


def _doc():
    board = BoardConstraints(
        kicad_version="20221018",
        generator="forgelab",
        layers=[],
        outline=[],
        design_rules=DesignRules(
            clearance=0.2, track_width=0.25, via_diameter=0.8, via_drill=0.4
        ),
    )
    nets = [Net(code=0, name=""), Net(code=1, name="GND"), Net(code=2, name="LED_A")]
    comp = Component(
        reference="R1",
        value="330R",
        footprint="Resistor_SMD:R_0603_1608Metric",
        layer="F.Cu",
        at=[100.0, 50.0, 0.0],
        pads=[Pad(number="1", net="LED_A"), Pad(number="2", net="GND")],
        uuid="abc",
    )
    from forgelab.spec import Node

    nodes = [Node(id=NODE_BOARD, type=NODE_BOARD, props=board.model_dump())]
    nodes += [
        Node(id=f"net:{n.code}", type=NODE_NET, props=n.model_dump()) for n in nets
    ]
    nodes.append(Node(id="R1", type=NODE_COMPONENT, props=comp.model_dump()))
    return ForgeDocument(
        forgelab_version=SPEC_VERSION,
        domain=Domain.HARDWARE,
        meta=DocumentMeta(name="t", generator="test"),
        nodes=nodes,
    )


def test_export_produces_valid_kicad_root():
    out = KiCadExporter().from_ir(_doc())
    tree = parse(out.decode("utf-8"))
    assert tree[0] == "kicad_pcb"


def test_export_contains_nets_and_footprint():
    out = KiCadExporter().from_ir(_doc()).decode("utf-8")
    assert '(net 1 "GND")' in out
    assert "Resistor_SMD:R_0603_1608Metric" in out
    assert '(property "Reference" "R1")' in out


def test_export_resolves_pad_net_codes():
    tree = parse(KiCadExporter().from_ir(_doc()).decode("utf-8"))
    footprints = [c for c in tree if isinstance(c, list) and c and c[0] == "footprint"]
    pads = [c for c in footprints[0] if isinstance(c, list) and c and c[0] == "pad"]
    pad_nets = {}
    for pad in pads:
        net = next(c for c in pad if isinstance(c, list) and c[0] == "net")
        pad_nets[pad[1]] = (net[1], net[2])
    assert pad_nets["1"] == (2, "LED_A")
    assert pad_nets["2"] == (1, "GND")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_kicad_exporter.py -v`
Expected: FAIL — stub raises `NotImplementedError`.

- [ ] **Step 3: Replace `forgelab/exporters/hardware/kicad.py`**

```python
"""KiCad PCB (.kicad_pcb) exporter: ForgeLab IR -> S-expression text.

Rebuilds the typed hardware vocabulary from the IR node graph and emits a
complete, functional ``kicad_pcb`` S-expression. Depends only on
``forgelab.spec`` and ``forgelab.formats`` (never on importers/exporters/core).
"""

from __future__ import annotations

from forgelab.exporters.base import Exporter
from forgelab.formats import Symbol, dumps
from forgelab.spec import (
    NODE_BOARD,
    NODE_COMPONENT,
    NODE_NET,
    BoardConstraints,
    Component,
    DesignRules,
    ForgeDocument,
    Net,
)

_DEFAULT_LAYERS = [
    [0, Symbol("F.Cu"), Symbol("signal")],
    [31, Symbol("B.Cu"), Symbol("signal")],
    [44, Symbol("Edge.Cuts"), Symbol("user")],
]


def _num(value: float) -> int | float:
    """Emit integral floats as ints so output matches KiCad's style."""
    return int(value) if float(value).is_integer() else float(value)


def _S(tag: str, *args: object) -> list:
    """Build an S-expression list headed by a bare ``tag`` symbol."""
    return [Symbol(tag), *args]


class KiCadExporter(Exporter):
    """Export ForgeLab IR to a KiCad PCB."""

    tool_name = "kicad"

    def from_ir(self, document: ForgeDocument) -> bytes:
        board = self._board(document)
        nets = self._nets(document)
        components = self._components(document)
        name_to_code = {n.name: n.code for n in nets}

        tree: list = [Symbol("kicad_pcb")]
        tree.append(_S("version", int(board.kicad_version) if board.kicad_version.isdigit() else board.kicad_version))
        tree.append(_S("generator", Symbol("forgelab")))
        tree.append(_S("general", _S("thickness", 1.6)))
        tree.append(_S("paper", "A4"))
        tree.append(self._layers_block(board))
        tree.append(self._setup_block(board.design_rules))
        for net in sorted(nets, key=lambda n: n.code):
            tree.append(_S("net", net.code, net.name))
        for comp in components:
            tree.append(self._footprint(comp, name_to_code))
        for seg in board.outline:
            tree.append(
                _S(
                    "gr_line",
                    _S("start", _num(seg.start[0]), _num(seg.start[1])),
                    _S("end", _num(seg.end[0]), _num(seg.end[1])),
                    _S("layer", "Edge.Cuts"),
                    _S("width", 0.1),
                )
            )

        return dumps(tree).encode("utf-8")

    def _board(self, document: ForgeDocument) -> BoardConstraints:
        for node in document.nodes:
            if node.type == NODE_BOARD:
                return BoardConstraints.model_validate(node.props)
        return BoardConstraints(
            kicad_version="20221018",
            generator="forgelab",
            layers=[],
            outline=[],
            design_rules=DesignRules(
                clearance=0.2, track_width=0.25, via_diameter=0.8, via_drill=0.4
            ),
        )

    def _nets(self, document: ForgeDocument) -> list[Net]:
        nets = [
            Net.model_validate(n.props)
            for n in document.nodes
            if n.type == NODE_NET
        ]
        if not any(n.code == 0 for n in nets):
            nets.insert(0, Net(code=0, name=""))
        return nets

    def _components(self, document: ForgeDocument) -> list[Component]:
        return [
            Component.model_validate(n.props)
            for n in document.nodes
            if n.type == NODE_COMPONENT
        ]

    def _layers_block(self, board: BoardConstraints) -> list:
        entries: list = [Symbol("layers")]
        rows = (
            [
                [
                    layer.ordinal,
                    Symbol(layer.canonical_name),
                    Symbol(layer.layer_type),
                ]
                + ([layer.user_name] if layer.user_name else [])
                for layer in board.layers
            ]
            if board.layers
            else [list(row) for row in _DEFAULT_LAYERS]
        )
        entries.extend(rows)
        return entries

    def _setup_block(self, rules: DesignRules) -> list:
        return _S(
            "setup",
            _S("pad_to_mask_clearance", 0),
            _S("clearance", _num(rules.clearance)),
            _S("trace_width", _num(rules.track_width)),
            _S("via_diameter", _num(rules.via_diameter)),
            _S("via_drill", _num(rules.via_drill)),
        )

    def _footprint(self, comp: Component, name_to_code: dict[str, int]) -> list:
        fp: list = [Symbol("footprint"), comp.footprint, _S("layer", comp.layer)]
        if comp.uuid is not None:
            fp.append(_S("uuid", comp.uuid))
        fp.append(_S("at", _num(comp.at[0]), _num(comp.at[1]), _num(comp.at[2])))
        fp.append(_S("property", "Reference", comp.reference))
        fp.append(_S("property", "Value", comp.value))
        for pad in comp.pads:
            code = name_to_code.get(pad.net, 0)
            fp.append(
                _S(
                    "pad",
                    pad.number,
                    Symbol("smd"),
                    Symbol("roundrect"),
                    _S("layers", "F.Cu"),
                    _S("net", code, pad.net),
                )
            )
        return fp
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_kicad_exporter.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Lint, typecheck**

Run: `.venv/bin/ruff check forgelab/exporters/hardware tests/test_kicad_exporter.py && .venv/bin/ruff format forgelab/exporters/hardware tests/test_kicad_exporter.py && PATH="$PWD/.venv/bin:$PATH" pyright forgelab/exporters/hardware`
Expected: clean, 0 errors. (If ruff flags the long `version` line, let `ruff format` reflow it.)

- [ ] **Step 6: Commit**

```bash
git add forgelab/exporters/hardware/kicad.py tests/test_kicad_exporter.py
git commit -m "feat(kicad): implement KiCad PCB exporter"
```

---

## Task 8: Semantic round-trip test

**Files:**
- Test: `tests/test_kicad_roundtrip.py`

This is the headline guarantee. It exercises only already-built code, so no implementation step.

- [ ] **Step 1: Write the round-trip tests**

Create `tests/test_kicad_roundtrip.py`:

```python
from pathlib import Path

from forgelab.exporters.hardware.kicad import KiCadExporter
from forgelab.formats import parse
from forgelab.importers.hardware.kicad import KiCadImporter
from forgelab.spec import NODE_COMPONENT, NODE_NET, Component

FIXTURE = (
    Path(__file__).resolve().parent.parent / "examples" / "hardware" / "blinky.kicad_pcb"
)


def test_semantic_roundtrip_is_stable():
    imp = KiCadImporter()
    exp = KiCadExporter()
    doc1 = imp.to_ir(FIXTURE.read_bytes())
    text = exp.from_ir(doc1)
    doc2 = imp.to_ir(text)
    assert doc1 == doc2


def test_roundtrip_preserves_counts_and_connectivity():
    imp = KiCadImporter()
    exp = KiCadExporter()
    doc1 = imp.to_ir(FIXTURE.read_bytes())
    doc2 = imp.to_ir(exp.from_ir(doc1))

    def comps(doc):
        return {
            n.id: Component.model_validate(n.props)
            for n in doc.nodes
            if n.type == NODE_COMPONENT
        }

    def net_names(doc):
        return sorted(n.props["name"] for n in doc.nodes if n.type == NODE_NET)

    c1, c2 = comps(doc1), comps(doc2)
    assert c1.keys() == c2.keys()
    for ref in c1:
        assert {p.number: p.net for p in c1[ref].pads} == {
            p.number: p.net for p in c2[ref].pads
        }
    assert net_names(doc1) == net_names(doc2)


def test_exported_file_is_valid_sexpr():
    doc = KiCadImporter().to_ir(FIXTURE.read_bytes())
    out = KiCadExporter().from_ir(doc)
    tree = parse(out.decode("utf-8"))
    assert tree[0] == "kicad_pcb"
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_kicad_roundtrip.py -v`
Expected: PASS (3 passed). If `test_semantic_roundtrip_is_stable` fails, diff `doc1` vs `doc2`
(`doc1.model_dump()` vs `doc2.model_dump()`) — the usual cause is non-canonical ordering (nets must
be sorted by code on import) or number formatting (`_num` must collapse integral floats). Fix the
importer/exporter, not the test.

- [ ] **Step 3: Commit**

```bash
git add tests/test_kicad_roundtrip.py
git commit -m "test(kicad): add semantic round-trip guarantee"
```

---

## Task 9: Update stub tests (KiCad is now real)

**Files:**
- Modify: `tests/test_stubs.py`

- [ ] **Step 1: Replace `tests/test_stubs.py`**

The current file asserts the KiCad importer/exporter raise `NotImplementedError`. KiCad is now
implemented, so switch those assertions to the still-stubbed Altium classes and keep the tool-name
checks. Write exactly this file:

```python
import pytest

from forgelab.exporters.hardware import AltiumExporter
from forgelab.importers.hardware import AltiumImporter, KiCadImporter
from forgelab.importers.mechanical import FreeCADImporter
from forgelab.importers.threed import BlenderImporter
from forgelab.spec import SPEC_VERSION, Domain, DocumentMeta, ForgeDocument


def test_importer_stub_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        AltiumImporter().to_ir(b"")


def test_exporter_stub_raises_not_implemented():
    doc = ForgeDocument(
        forgelab_version=SPEC_VERSION,
        domain=Domain.HARDWARE,
        meta=DocumentMeta(name="x"),
    )
    with pytest.raises(NotImplementedError):
        AltiumExporter().from_ir(doc)


def test_stub_tool_names_set():
    assert KiCadImporter.tool_name == "kicad"
    assert AltiumImporter.tool_name == "altium"
    assert FreeCADImporter.tool_name == "freecad"
    assert BlenderImporter.tool_name == "blender"
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_stubs.py -v`
Expected: PASS (3 passed)

- [ ] **Step 3: Lint**

Run: `.venv/bin/ruff check tests/test_stubs.py && .venv/bin/ruff format tests/test_stubs.py`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add tests/test_stubs.py
git commit -m "test(stubs): point stub assertions at Altium (KiCad now implemented)"
```

---

## Task 10: Regenerate `blinky.forge.json` from the importer

**Files:**
- Modify: `examples/hardware/blinky.forge.json`

`tests/test_examples.py` already asserts every `*.forge.json` under `examples/` validates via
`forgelab.core.validate`. We regenerate the JSON so it reflects the new typed-node structure and is
stamped `0.2.0`.

- [ ] **Step 1: Regenerate the file**

Run this one-off command from the repo root:

```bash
.venv/bin/python -c "
import json
from pathlib import Path
from forgelab.importers.hardware.kicad import KiCadImporter
doc = KiCadImporter().to_ir(Path('examples/hardware/blinky.kicad_pcb').read_bytes())
Path('examples/hardware/blinky.forge.json').write_text(doc.model_dump_json(indent=2) + '\n')
print(doc.forgelab_version, len(doc.nodes), 'nodes')
"
```

Expected output: `0.2.0 7 nodes` (1 board + 4 nets + 2 components).

- [ ] **Step 2: Verify it validates and the suite is green**

Run: `.venv/bin/pytest tests/test_examples.py -v`
Expected: PASS (1 passed)

- [ ] **Step 3: Commit**

```bash
git add examples/hardware/blinky.forge.json
git commit -m "feat(examples): regenerate blinky.forge.json from KiCad import (0.2.0)"
```

---

## Task 11: Docs — CHANGELOG and CONTRIBUTING boundary rule

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `CONTRIBUTING.md`

- [ ] **Step 1: Update `CHANGELOG.md`**

Under `## [Unreleased]` / `### Added`, append these bullets after the existing ones:

```markdown
- KiCad PCB importer and exporter with a verified IR-level round-trip
  (components, nets, and board constraints preserved).
- Typed hardware spec vocabulary (`Component`, `Pad`, `Net`, `BoardLayer`,
  `OutlineSegment`, `DesignRules`, `BoardConstraints`) serialized into the
  generic Node graph.
- `forgelab.formats` package with a zero-dependency S-expression parser/writer.
- Real `examples/hardware/blinky.kicad_pcb` board.

### Changed
- `SPEC_VERSION` bumped to `0.2.0` (additive hardware vocabulary; backward
  compatible — version compatibility remains major-based).
- Importers/exporters may now depend on `forgelab.formats` (shared neutral
  format primitives) in addition to `forgelab.spec`.
```

- [ ] **Step 2: Update the boundary rule in `CONTRIBUTING.md`**

Find this line under "Adding an importer or exporter":

```markdown
Register new classes in `forgelab/core/pipeline.py:default_registry`. Importers
and exporters must depend on `forgelab.spec` only — never on each other.
```

Replace it with:

```markdown
Register new classes in `forgelab/core/pipeline.py:default_registry`. Importers
and exporters must depend on `forgelab.spec` and `forgelab.formats` only — never
on each other and never on `forgelab.core`. Shared file-format primitives (such
as the S-expression parser) live in `forgelab.formats`.
```

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md CONTRIBUTING.md
git commit -m "docs: record KiCad round-trip, 0.2.0, and formats boundary rule"
```

---

## Task 12: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run the entire gate suite**

```bash
export PATH="$PWD/.venv/bin:$PATH"
ruff check . && ruff format --check . && pyright && pytest
```

Expected: ruff clean, ruff format clean, pyright 0 errors, all tests pass (the prior 28 plus the new
sexpr/hardware/importer/exporter/round-trip tests). If `ruff format --check` flags any file, run
`ruff format .`, re-run the suite, and amend the relevant commit or add a follow-up formatting commit.

- [ ] **Step 2: Confirm the round-trip end to end by hand (sanity)**

```bash
.venv/bin/python -c "
from pathlib import Path
from forgelab.importers.hardware.kicad import KiCadImporter
from forgelab.exporters.hardware.kicad import KiCadExporter
src = Path('examples/hardware/blinky.kicad_pcb').read_bytes()
d1 = KiCadImporter().to_ir(src)
d2 = KiCadImporter().to_ir(KiCadExporter().from_ir(d1))
print('round-trip equal:', d1 == d2)
print('components:', [n.id for n in d1.nodes if n.type=='component'])
"
```

Expected: `round-trip equal: True` and `components: ['R1', 'D1']`.

- [ ] **Step 3: Commit any formatting fixups (only if Step 1 required them)**

```bash
git add -A
git commit -m "style: apply ruff formatting"
```

---

## Self-Review Notes

- **Spec coverage:** module restructure ✓ (T4); `forgelab/formats/` S-expr primitive + boundary
  change ✓ (T2, T11); typed hardware models ✓ (T3); importer ✓ (T6); exporter ✓ (T7); functional
  output ✓ (T7 emits full header/layers/setup/nets/footprints/outline); round-trip strategy ✓ (T8);
  real example board ✓ (T5); regenerated forge.json ✓ (T10); 0.2.0 bump ✓ (T1); stub-test update ✓
  (T9); CHANGELOG/CONTRIBUTING ✓ (T11); error handling (`SExprError`, `KiCadParseError`, export
  defaults, pad→code 0) ✓ (T2, T6, T7).
- **Determinism for round-trip equality:** nets sorted by code on import (T6) AND on export (T7);
  integral floats collapsed to ints via `_num` (T7); components kept in file order both ways. These
  three together make `doc1 == doc2` hold.
- **Type/name consistency:** `Component.at` is `[x,y,rotation]` length 3 everywhere; `Pad.net` holds
  the net **name** in importer (T6), exporter (T7), and tests (T6/T7/T8); node types use the
  `NODE_COMPONENT/NODE_NET/NODE_BOARD` constants consistently; `KiCadParseError` defined in T6 and
  used in T6 tests; `forgelab.formats` API (`parse`, `dumps`, `Symbol`, `SExprError`) consistent
  across T2/T6/T7/T8.
- **Boundary:** importer (T6) and exporter (T7) import only `forgelab.spec` and `forgelab.formats`;
  neither imports `forgelab.core` or each other; `KiCadParseError` subclasses `SExprError` (from
  formats) rather than a `core` error.
- **Placeholder scan:** the only "do not do this" snippet is the explicitly-labeled anti-example in
  T9 Step 1, immediately followed by the exact correct file to write.
