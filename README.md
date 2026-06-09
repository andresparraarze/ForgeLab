# ForgeLab

> **The LLVM of design.** A universal, JSON-based design interchange format and compiler that lets AI agents create, read, and transform design files across tools and domains — without ever touching proprietary file formats.

[![CI](https://github.com/andresparraarze/ForgeLab/actions/workflows/ci.yml/badge.svg)](https://github.com/andresparraarze/ForgeLab/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![Spec](https://img.shields.io/badge/spec-v0.5.0-orange.svg)](forgelab/spec/version.py)
[![Status](https://img.shields.io/badge/status-pre--alpha-red.svg)](#project-status)

ForgeLab defines a JSON **intermediate representation (IR)** that sits between AI agents and design
software. Any tool can *import* its native files into ForgeLab IR; any tool can *export* ForgeLab IR
back to its native format. Agents operate **entirely in ForgeLab JSON** — no proprietary formats, no
special training.

```
native file ──import──▶ ForgeLab IR ──transform──▶ ForgeLab IR ──export──▶ native file
                          ▲                                        │
                          └──────────── AI agents ─────────────────┘
                                   (pure JSON, no proprietary formats)
```

## Table of Contents

- [Why ForgeLab](#why-forgelab)
- [Tool support](#tool-support)
- [Install](#install)
- [Quickstart](#quickstart)
  - [Build IR with the AI SDK](#build-ir-with-the-ai-sdk)
  - [Round-trip a KiCad board](#round-trip-a-kicad-board)
  - [Round-trip a glTF scene](#round-trip-a-gltf-scene)
  - [Round-trip a FreeCAD model](#round-trip-a-freecad-model)
  - [Run the compiler service](#run-the-compiler-service)
- [How it works](#how-it-works)
- [Repository layout](#repository-layout)
- [Spec versioning](#spec-versioning)
- [Project status](#project-status)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

## Why ForgeLab

- **JSON-native for AI.** The IR is plain JSON, so any LLM or agent can emit and consume it directly
  — no custom file writers, no proprietary SDKs, no special training.
- **Tool-agnostic.** Importers and exporters plug into a shared IR. Add a tool once and it
  interoperates with every other tool ForgeLab supports.
- **Versioned for the long haul.** Every document declares a `forgelab_version`, so tooling can
  reason about compatibility as the spec evolves.
- **Typed where it counts.** Domain vocabularies (e.g. hardware: components, nets, board
  constraints) are validated Pydantic models that serialize into a generic, universal node graph.

## Tool support

| Domain         | Tool          | Import | Export | Notes                                        |
| -------------- | ------------- | :----: | :----: | -------------------------------------------- |
| Hardware       | KiCad         |   ✅   |   ✅   | `.kicad_pcb` round-trip (components/nets/board) |
| Hardware       | Altium        |   🚧   |   🚧   | stub — contributions welcome                 |
| Hardware       | Gerber        |   🚧   |   🚧   | stub — contributions welcome                 |
| Mechanical CAD | FreeCAD       |   ✅   |   ✅   | `.FCStd` round-trip (parts/bodies/features/sketch dimensions) |
| Mechanical CAD | Fusion 360    |   🚧   |   🚧   | stub                                         |
| 3D / Game      | glTF (.gltf)  |   ✅   |   ✅   | `.gltf` round-trip (meshes/materials/scene hierarchy) |
| 3D / Game      | Blender       |   ✅   |   ✅   | via glTF interchange; native `.blend` 🚧     |
| 3D / Game      | Unreal Engine |   🚧   |   🚧   | stub                                         |

✅ implemented · 🚧 stub (base classes in place, awaiting implementation)

## Install

Requires Python 3.11+.

```bash
git clone https://github.com/andresparraarze/ForgeLab
cd ForgeLab
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,api]"
```

ForgeLab has no heavy runtime dependencies — just Pydantic and FastAPI. The KiCad support parses the
`.kicad_pcb` S-expression format directly, so **no KiCad installation is required**.

## Quickstart

### Build IR with the AI SDK

The AI SDK takes a natural-language prompt to a validated, ready-to-compile
`ForgeDocument` — natural language to a real KiCad file in ~10 lines:

```python
from forgelab.sdk import ForgeAgent
from forgelab.exporters.hardware.kicad import KiCadExporter

agent = ForgeAgent()                                    # reads ANTHROPIC_API_KEY
doc = agent.design("a blinky LED board with one resistor and one LED",
                   domain="hardware")                   # NL -> validated ForgeDocument
with open("blinky.kicad_pcb", "wb") as f:
    f.write(KiCadExporter().from_ir(doc))               # -> real KiCad file
```

`ForgeAgent` forces Claude to emit ForgeLab JSON through a per-domain JSON
Schema, then validates it before returning. Requires the optional extra:
`pip install "forgelab[agent]"`.

The lower-level building blocks are independent and provider-agnostic:

```python
from forgelab.sdk import domain_schema, system_prompt, few_shot, validate_llm_output

domain_schema("hardware")        # tight JSON Schema for structured-output / tools
system_prompt("threed")          # ready-made system prompt for any LLM
few_shot("threed")               # (request, valid-JSON) examples
validate_llm_output(raw_text, domain="hardware")  # clean + parse + validate, or raise
```

And the original primitives still work for hand-built documents:

```python
from forgelab.sdk import new_document, dump, load

doc = new_document(domain="hardware", name="blinky")
restored = load(dump(doc))
assert restored == doc
```

### Round-trip a KiCad board

Import a real `.kicad_pcb`, work with it as JSON, and export a functional board back out:

```python
from forgelab.importers.hardware.kicad import KiCadImporter
from forgelab.exporters.hardware.kicad import KiCadExporter

source = open("examples/hardware/blinky.kicad_pcb", "rb").read()

doc = KiCadImporter().to_ir(source)          # .kicad_pcb -> ForgeDocument
components = [n.id for n in doc.nodes if n.type == "component"]
print(components)                            # ['R1', 'D1']

kicad_bytes = KiCadExporter().from_ir(doc)   # ForgeDocument -> .kicad_pcb

# The round-trip is stable: import -> export -> import is an identity over the IR.
assert KiCadImporter().to_ir(kicad_bytes) == doc
```

### Round-trip a glTF scene

Import a `.gltf` 3D scene, work with the geometry as JSON, and export it back:

```python
from forgelab.importers.threed.gltf import GltfImporter
from forgelab.exporters.threed.gltf import GltfExporter

source = open("examples/threed/cube.gltf", "rb").read()

doc = GltfImporter().to_ir(source)           # .gltf -> ForgeDocument
objects = [n.id for n in doc.nodes if n.type == "object"]
print(objects)                               # ['Cube']

gltf_bytes = GltfExporter().from_ir(doc)     # ForgeDocument -> .gltf

# The round-trip is stable: import -> export -> import is an identity over the IR.
assert GltfImporter().to_ir(gltf_bytes) == doc
```

Mesh geometry is fully decoded into plain JSON arrays (positions, indices) — no
opaque binary buffers — so an agent can read and edit the scene directly.

### Round-trip a FreeCAD model

Import a FreeCAD `.FCStd` mechanical model, work with the feature tree as JSON,
and export it back:

```python
from forgelab.importers.mechanical import FreeCADImporter
from forgelab.exporters.mechanical import FreeCADExporter

source = open("examples/mechanical/box-with-hole.FCStd", "rb").read()

doc = FreeCADImporter().to_ir(source)         # .FCStd -> ForgeDocument
features = [n.id for n in doc.nodes if n.type in ("pad", "pocket")]
print(features)                               # ['Pad', 'Pocket']

fcstd_bytes = FreeCADExporter().from_ir(doc)  # ForgeDocument -> .FCStd

# The round-trip is stable: import -> export -> import is an identity over the IR.
assert FreeCADImporter().to_ir(fcstd_bytes) == doc
```

The parametric feature tree — parts, bodies, sketches with dimensions, pads
(extrusions) and pockets (cuts) — is captured as plain JSON nodes with link
references, so an agent can read and edit the model directly. Parsing uses only
the standard library (`zipfile` + `xml.etree`), so **no FreeCAD installation is
required**.

### Run the compiler service

ForgeLab also ships as a compiler-as-a-service so agents can call it over HTTP:

```bash
uvicorn forgelab.api.app:app --reload
```

| Method | Path             | Purpose                          |
| ------ | ---------------- | -------------------------------- |
| GET    | `/health`        | Liveness + spec version          |
| GET    | `/spec`          | ForgeDocument JSON Schema        |
| POST   | `/validate`      | Validate a ForgeLab document     |
| POST   | `/export/{tool}` | Export IR to a tool's format     |

## How it works

A ForgeLab document is a small typed envelope — `forgelab_version`, `domain`, `meta` — wrapping a
generic graph of `Node` objects. Domain vocabularies layer on top of that graph: a hardware board,
for example, is a `board` node plus `net` and `component` nodes, each carrying a validated typed
payload in its `props`.

```
.kicad_pcb ──▶ KiCadImporter ──▶ ForgeDocument ──▶ KiCadExporter ──▶ .kicad_pcb
                                   (validate / transform)
```

Importers and exporters depend only on the spec and on shared format primitives (`forgelab.formats`,
e.g. the S-expression parser) — never on each other. That keeps every tool an independent,
testable plugin and makes adding the next one a contained change.

## Repository layout

```
forgelab/
├── spec/        # IR models (Pydantic v2), versioning, JSON Schema export, hardware vocabulary
├── core/        # validate(), registry, compiler pipeline, errors
├── formats/     # shared, zero-dependency format primitives (S-expression, glTF, FCStd)
├── importers/   # tool → IR  (base ABC + per-domain packages; KiCad implemented)
├── exporters/   # IR → tool  (base ABC + per-domain packages; KiCad implemented)
├── sdk/         # AI agent helpers
└── api/         # FastAPI compiler-as-a-service
examples/        # real sample designs (e.g. hardware/blinky.kicad_pcb + its ForgeLab JSON)
tests/           # pytest suite, including the KiCad round-trip guarantee
```

## Spec versioning

Every document carries a `forgelab_version`. Compatibility is **major-based**: a document validates
against any library sharing its major version. The current spec is **v0.5.0** (`SPEC_VERSION` in
`forgelab/spec/version.py`). Any change to the `ForgeDocument` root or a breaking change to a domain
vocabulary bumps the version — see [CONTRIBUTING.md](CONTRIBUTING.md) and [CHANGELOG.md](CHANGELOG.md).

## Project status

**Pre-alpha (v0.1 of the library, v0.5.0 of the spec).** The IR, validator, compiler pipeline, API,
three end-to-end round-trips — the **KiCad `.kicad_pcb`** (hardware), the **glTF `.gltf`** (3D /
game), and the **FreeCAD `.FCStd`** (mechanical CAD) importer/exporter pairs — and the **AI SDK**
(schema export, prompt templates, output validation, and a Claude-backed `ForgeAgent`) all work and
are covered by tests. The remaining tool integrations are scaffolded stubs awaiting implementation.
APIs may change before 1.0.

## Roadmap

- [x] Core IR, validator, registry, and compiler pipeline
- [x] AI SDK and FastAPI compiler service
- [x] Typed hardware vocabulary + S-expression format primitive
- [x] KiCad `.kicad_pcb` importer/exporter round-trip
- [x] 3D / Game: Blender via glTF round-trip (meshes, materials, scene hierarchy)
- [ ] Hardware: Gerber and Altium
- [x] Mechanical CAD: FreeCAD `.FCStd` importer/exporter round-trip
- [ ] Mechanical CAD: Fusion 360
- [ ] 3D / Game: Unreal Engine, glTF textures/animations, and `.glb` binary container
- [ ] Transform passes (e.g. design-rule checks, layer remaps) over the IR
- [ ] HTTP `/import` endpoint and a CLI

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). The highest-leverage starting
point is implementing an importer/exporter for one tool against the `Importer`/`Exporter` base
classes; the KiCad pair is a complete worked example to model new tools on.

```bash
ruff check . && ruff format --check . && pyright && pytest
```

## License

[Apache 2.0](LICENSE).
