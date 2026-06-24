# ForgeLab

ForgeLab lets AI agents design hardware, mechanical parts, and 3D models — and export them to real tool files — without ever touching a proprietary format.

> **The LLVM of design.** One JSON intermediate representation; every tool imports and exports it.

| Domain         | Tool             |
| -------------- | ---------------- |
| Hardware       | KiCad            |
| Mechanical CAD | FreeCAD          |
| 3D / Game      | Blender / glTF   |

[![CI](https://github.com/andresparraarze/ForgeLab/actions/workflows/ci.yml/badge.svg)](https://github.com/andresparraarze/ForgeLab/actions/workflows/ci.yml)

## Install in 30 seconds

### Claude Code

```bash
curl -fsSL https://raw.githubusercontent.com/andresparraarze/ForgeLab/main/scripts/install-claude-code.sh | bash
```

That's it. Ask Claude Code to design anything.

### Hermes Agent

Paste this prompt:

> Install ForgeLab on this machine. Clone https://github.com/andresparraarze/ForgeLab, create a venv at ~/.forgelab/venv, install forgelab[mcp,agent] into it, start the MCP server with streamable-http transport on port 8001, and confirm the tools are available by calling list_domains. Then tell me what domains are supported.

### OpenClaw

Paste this prompt:

> Install ForgeLab and add it to your MCP configuration. Clone https://github.com/andresparraarze/ForgeLab, create a venv at ~/.forgelab/venv, install forgelab[mcp,agent], add the stdio MCP server to your config at ~/.forgelab/venv/bin/forgelab-mcp --transport stdio, verify by calling list_domains, and confirm what design domains are available.

## What you can do

Just tell your agent what you want:

- *"Design an Arduino Mega clone board and export it to KiCad"*
- *"Generate a NEMA17 motor mount plate with M3 mounting holes and export to FreeCAD"*
- *"Create a low-poly sci-fi space station with solar panels and a docking port for Blender"*

## How it works

```
native file ──import──▶ ForgeLab IR ──transform──▶ ForgeLab IR ──export──▶ native file
                          ▲                                        │
                          └──────────── AI agents ─────────────────┘
                                   (pure JSON, no proprietary formats)
```

Every tool imports its native files into one JSON IR and exports the IR back. Agents work entirely in ForgeLab JSON — no proprietary formats, no special training.

## Tool support

| Domain         | Tool          | Import | Export | Notes                                        |
| -------------- | ------------- | :----: | :----: | -------------------------------------------- |
| Hardware       | KiCad         |   ✅   |   ✅   | `.kicad_pcb` round-trip (components/nets/board) |
| Hardware       | Altium        |   🚧   |   🚧   | stub — contributions welcome                 |
| Hardware       | Gerber        |   🚧   |   🚧   | stub — contributions welcome                 |
| Mechanical CAD | FreeCAD       |   ✅   |   ✅   | `.FCStd` round-trip (parts/bodies/features/sketches) |
| Mechanical CAD | Fusion 360    |   🚧   |   🚧   | stub                                         |
| 3D / Game      | glTF          |   ✅   |   ✅   | `.gltf` round-trip (meshes/materials/scene)  |
| 3D / Game      | OBJ           |   ✅   |        | import `.obj` (+ companion `.mtl`); fan-triangulated, per-object meshes |
| 3D / Game      | STL           |   ✅   |        | import ASCII or binary `.stl` (single mesh, default material) |
| 3D / Game      | Blender script|        |   ✅   | export `tool='blender_script'` → runnable `.py` (native objects, materials, primitives, camera + lighting) |
| 3D / Game      | Blender       |   ✅   |   ✅   | via glTF interchange; native `.blend` 🚧     |
| 3D / Game      | Unreal Engine |   🚧   |   🚧   | stub                                         |

✅ implemented · 🚧 stub (base classes in place, awaiting implementation)

## MCP tools

Twenty-seven tools, same for every client. Over stdio all are local; over HTTP each needs its scope on the bearer token.

### Read

| Tool | Description |
| --- | --- |
| `list_domains` | List supported design domains |
| `list_formats` | List format tools (KiCad, glTF, FreeCAD) |
| `get_domain_schema` | JSON Schema for a domain |
| `get_prompt` | System-prompt template for a domain |
| `get_projection_schema` | What each projection level keeps or strips |
| `generation_status` | Whether `generate_document` is usable |
| `list_components` | Pre-built component names grouped by category |
| `get_component` | A component's footprint + datasheet pad geometry |

### Edit

| Tool | Description |
| --- | --- |
| `validate_document` | Validate a document, inline or by file path |
| `load_document` | Summarize a saved `.forge.json` (metadata only) |
| `patch_document` | Apply an RFC 6902 JSON Patch to a saved document |
| `diff_documents` | RFC 6902 patch transforming document A into B |
| `verify_sync` | Check a native file is still in sync with its source document |
| `generate_bom` | Bill of materials from a hardware document (JSON or CSV) |

### Project

A `.forge.project` file ties multiple domain documents together with a shared dimension table (one source of truth) and informational cross-domain constraints.

| Tool | Description |
| --- | --- |
| `create_project` | Create a project, inferring shared dimensions from linked documents |
| `load_project` | Summarize a project: shared dimensions + per-document status |
| `update_project` | Change shared dimensions, optionally re-checking all documents |
| `export_project` | Export every linked document to its native format in one call |

### Calculate

| Tool | Description |
| --- | --- |
| `calculate_pad_positions` | DIP/SOIC/SOP/QFP pad offsets |
| `calculate_polygon` | Regular-polygon vertices |
| `calculate_rotation_matrix` | glTF `[x, y, z, w]` quaternion |
| `calculate_trace_width` | IPC-2221 trace width |
| `calculate_board_layout` | Margin-aware component grid |

### Export

| Tool | Description |
| --- | --- |
| `export_document` | IR → native file (KiCad, glTF, FreeCAD, Blender `.py`) |
| `import_file` | Native file → IR (KiCad, glTF, OBJ, STL, FreeCAD) |

### Generate

| Tool | Description |
| --- | --- |
| `generate_document` | Natural language → validated ForgeDocument |
| `analyze_image` | Photo → ForgeLab document skeleton (vision) |

## Token optimization

- **Work by file path.** `validate_document` and `export_document` take a `document_path`; agents write a document once and process it by path — no large JSON in context.
- **Edit by patch.** `patch_document` applies an RFC 6902 JSON Patch, so changing one component is a few hundred bytes, not a full re-emission.
- **Project what you need.** Pass `projection` (`metadata`/`topology`/`geometry`/`full`) to receive only the relevant slice; stripping happens server-side.
- **Compute, don't guess.** The five `calculate_*` tools handle geometry and electrical math deterministically instead of inline.

## Project status

**Pre-alpha** (library v0.1, spec v0.5.0). The IR, validator, compiler pipeline, REST API, three round-trips (**KiCad**, **glTF**, **FreeCAD**), the **AI SDK**, the **OAuth 2.0** module, and the **MCP server** all work and are covered by tests. Remaining tool integrations (Altium, Gerber, Fusion 360, Unreal) are scaffolded stubs. APIs may change before 1.0.

## Roadmap

- [x] Core IR, validator, registry, compiler pipeline; AI SDK + REST service
- [x] KiCad `.kicad_pcb`, glTF `.gltf` (Blender), and FreeCAD `.FCStd` round-trips
- [x] OAuth 2.0 auth + MCP server (stdio + Streamable HTTP)
- [x] Multi-tool workflows + zero-friction agent setup (installer, `forgelab init`, bootstrap prompts)
- [ ] Publish to PyPI so `pip install forgelab` works without cloning
- [ ] Hardware: Gerber, Altium · Mechanical: Fusion 360 · 3D: Unreal, glTF textures/animations, `.glb`
- [ ] Transform passes (design-rule checks, layer remaps) over the IR; HTTP `/import` endpoint

**Planned domains** — new vocabularies and compile targets beyond the current hardware/mechanical/3D trio:

- [ ] Robotics domain — URDF/ROS output: link/joint/sensor vocabulary compiling to URDF files for robot kinematic simulation in ROS alongside FreeCAD mechanical models
- [ ] Microfluidics domain — lab-on-a-chip design: treat mixers/reservoirs as components and fluid channels as traces, compiling to Gerber files for photomask lithography (natural extension of the hardware domain)
- [ ] BIM domain — building information modeling: wall/floor/door/window/room vocabulary compiling to IFC for architectural floor plans, structural framing, and MEP system routing

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The highest-leverage start is an importer/exporter for one tool against the `Importer`/`Exporter` base classes — the KiCad pair is a complete worked example.

```bash
ruff check . && ruff format --check . && pyright && pytest
```

## License

[Apache 2.0](LICENSE).
