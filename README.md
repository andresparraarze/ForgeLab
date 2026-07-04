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

### Codex CLI

Assumes ForgeLab is already installed (the Claude Code curl script above, or
a manual install, has been run) — Codex just needs to be pointed at the same
venv:

```bash
codex mcp add forgelab --env FORGELAB_OUTPUT_DIR=$HOME/forgelab-output -- $HOME/.forgelab/venv/bin/forgelab-mcp --transport stdio
```

That's it. Ask Codex to design anything. Run `/mcp` inside a Codex session to
confirm ForgeLab's tools are listed.

## What you can do

Just tell your agent what you want:

- *"Design a wireless temperature sensor with ESP32, DHT22, USB-C power, and a 3D-printable enclosure"*

ForgeLab produces a complete project: KiCad PCB + FreeCAD enclosure sized to fit the board + Blender product render script + BOM — all from one prompt, all dimensionally coherent via a shared project file.

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
| Hardware       | KiCad         |   ✅   |   ✅   | `.kicad_pcb` round-trip (components/nets/board), routed track/via export |
| Hardware       | Altium        |   🚧   |   🚧   | stub — contributions welcome                 |
| Hardware       | Gerber        |   🚧   |   ✅   | export RS-274X layer set + Excellon drill, zipped (F/B copper, mask, silk, outline) |
| Mechanical CAD | FreeCAD       |   ✅   |   ✅   | `.FCStd` round-trip (parts/bodies/features/sketches, loft/sweep/fillet/shell/revolve) |
| Mechanical CAD | Fusion 360    |   🚧   |   🚧   | stub                                         |
| 3D / Game      | glTF          |   ✅   |   ✅   | `.gltf` round-trip (meshes/materials/scene)  |
| 3D / Game      | OBJ           |   ✅   |        | import `.obj` (+ companion `.mtl`); fan-triangulated, per-object meshes |
| 3D / Game      | STL           |   ✅   |        | import ASCII or binary `.stl` (single mesh, default material) |
| 3D / Game      | Blender script|        |   ✅   | export `tool='blender_script'` → runnable `.py` product render (native objects + modifier stack, daylight-sky world, CYCLES/EEVEE `PREVIEW` toggle, 85mm 3/4 camera, ground plane, auto-render to PNG) |
| 3D / Game      | Blender       |   ✅   |   ✅   | via glTF interchange; native `.blend` 🚧     |
| 3D / Game      | Unreal Engine |   🚧   |   🚧   | stub                                         |

✅ implemented · 🚧 stub (base classes in place, awaiting implementation)

In the hardware domain, agents don't have to hand-guess XY coordinates: build
the document with components and nets but rough (or no) positions, then call
**`auto_place`** before `validate_document`/`export_document`. A shelf-packing
algorithm sizes each component from its real pad geometry (plus a keepout
margin) and packs everything inside the board outline — guaranteed zero
overlap and zero components off the board. Large parts (QFPs/QFNs/modules,
by footprint area) are kept away from the board edges (`large_component_inset`,
default 5mm) so the autorouter keeps escape channels on all their sides —
tuned empirically, this lifted the Arduino Uno example from 22 to 25 routed
nets. Mark a manually positioned
component `"locked": true` (e.g. an edge connector) and the rest packs around
it; the returned `board_utilization` percentage signals when the board needs
to grow. `validate_document` backs this up with a hard board-outline
containment check: a component whose pad footprint extends outside the
outline fails validation at document time — not after opening KiCad — and the
error message points at `auto_place` as the fix.

**Coordinate convention (hardware domain):** the IR is **Y-up** — millimetres,
origin at the board outline's lower-left corner, +X right, +Y up, rotation in
degrees counterclockwise — the way a person naturally reasons about parts on a
board. Format tools translate at the boundary, never inside the IR: Gerber
output is natively Y-up and passes coordinates through unchanged, while KiCad
files are Y-down, so the KiCad exporter/importer mirror Y about the outline's
vertical centre (and negate pad-local offsets) on the way out and in — round
trips stay exact. A dedicated test pins specific coordinates on both sides so
a frame regression fails CI immediately.

The pipeline ends fab-ready: `export_document(tool='gerber',
output_path='board_gerbers.zip')` writes a zip a fab house can accept —
front/back copper (routed tracks, via annulars, flashed pad apertures),
soldermask openings, silkscreen reference designators, board outline, and an
Excellon drill file with one hole per via — validated against a real Gerber
parser (gerbonara reads back every layer and recognizes the full stack). Run
`check_gerber_completeness` first: it re-checks the fab rules on the routed
geometry and warns if the board has no tracks yet. The full workflow:
**build → `auto_place` → `route_board` → `check_fabrication` →
`export_document(tool='gerber')` → upload to JLCPCB/PCBWay/OSH Park.**

After placement, **`route_board`** turns the netlist into real copper: a
2-layer grid-based maze router (Lee's algorithm) connects every net with
`track` and `via` nodes that the KiCad exporter emits as actual
`(segment ...)`/`(via ...)` S-expressions, and `check_fabrication` validates
the routed geometry — not just the declared design rules — against the fab's
minimum trace width and clearance. The full hardware workflow is: build (or
generate) the document → `auto_place` → `route_board` → `validate_document` →
`export_document(tool='kicad')`. Set expectations correctly: this is a basic
router for simple-to-moderate boards (the Arduino Uno / ESP32 dev-board
range), not a replacement for a commercial autorouter on dense designs. Nets
the maze search cannot connect come back in `nets_failed` for manual routing
instead of failing the run — on the packed Arduino Uno example, 25 of 32
multi-pad nets route at the default 0.2mm grid (placement's escape-channel
inset for large parts bought the last three), with the remaining failures
concentrated on residual congestion and the highest-fanout power nets.

The mechanical domain covers both of FreeCAD's modelling styles. Use
**PartDesign** (`sketch`/`pad`/`pocket`) for prismatic engineering parts —
brackets, mounts, plates, enclosures — built by extruding and cutting closed 2D
profiles. Use the **Part workbench** (`loft`/`sweep`/`fillet`/`shell`/`revolve`) for
organic or curved shapes — grips, handles, knobs, ergonomic surfaces — where
the exported file carries only the feature description and FreeCAD's own
OpenCASCADE kernel computes the real NURBS geometry on recompute. Choose
`loft` for asymmetric shapes whose cross-section changes along a path (see
`examples/mechanical/organic_grip.forge.json`); choose `revolve` for
axially-symmetric round shapes — knobs, caps, bottle-like grips — where one
closed profile spun around an axis is easier to specify correctly than
stacked loft sections (see `examples/mechanical/rounded_knob.forge.json`).

In the threed domain, objects can carry a **Blender modifier stack** — an
ordered `modifiers` list of `subsurf`, `bevel`, `boolean` and `solidify`
entries that the Blender script exporter compiles to native
`obj.modifiers.new(...)` calls (boolean targets are created first via a
dependency sort and hidden from render). Blender's own modifier evaluation
computes the real smooth geometry when the script runs, so agents describe
organic shapes as primitives + modifiers instead of hand-computing triangles:
**cube (or cylinder) + `subsurf` + `bevel`** is the go-to pattern for a smooth
rounded shape, and a `boolean` difference carves indents and cutouts (see
`examples/threed/organic_handle.forge.json`).

### Render-critique loop for iterative refinement

Agents can now *see* what they built and fix it without Blender installed or
a human checking screenshots. `preview_render` (the `preview` extra:
matplotlib + numpy, pure pip) renders a document's triangle meshes flat-shaded
from three angles into one PNG; `critique_render` sends that PNG — plus an
optional reference image — to the vision model with the design intent and
returns structured feedback. ForgeLab provides the primitives; the calling
agent drives the loop:

```
preview_render("car.forge.json", "car.png")
critique_render("car.png", "a low-slung sports car with a long hood")
  -> {"matches_intent": false, "score": 6,
      "issues": [{"severity": "critical",
                  "description": "only three wheels are visible",
                  "likely_cause": "missing rear-left wheel object"}],
      "suggested_changes": ["add a fourth wheel at the rear-left"]}
patch_document(...)          # apply the suggested changes
preview_render(...)          # re-render
critique_render(...)         # re-judge; repeat until the score is acceptable
```

Previews draw the baked triangle geometry (modifier stacks are evaluated by
Blender, so they show the base meshes). Check `generation_status` first:
`preview_render` needs `pip install "forgelab[preview]"`, and
`critique_render` needs `ANTHROPIC_API_KEY` plus the `agent` extra.

## MCP tools

Thirty-five tools, same for every client. Over stdio all are local; over HTTP each needs its scope on the bearer token.

### Read

| Tool | Description |
| --- | --- |
| `list_domains` | List supported design domains |
| `list_formats` | List format tools (KiCad, glTF, FreeCAD) |
| `get_domain_schema` | JSON Schema for a domain |
| `get_prompt` | System-prompt template for a domain |
| `get_projection_schema` | What each projection level keeps or strips |
| `generation_status` | Whether the API-backed and preview tools are usable |
| `preview_render` | Flat-shaded multi-angle PNG preview of a threed document (local, no Blender; `preview` extra) |
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
| `check_fabrication` | Validate a board against a PCB fab's rules (JLCPCB/PCBWay/OSH Park) |
| `check_gerber_completeness` | Pre-flight a board before Gerber export (fab rules + routed copper) |
| `list_fab_profiles` | Available fab profiles and their key constraints |

### Project

A `.forge.project` file ties multiple domain documents together with a shared dimension table (one source of truth) and informational cross-domain constraints.

| Tool | Description |
| --- | --- |
| `create_project` | Create a project, inferring shared dimensions from linked documents |
| `load_project` | Summarize a project: shared dimensions + per-document status |
| `update_project` | Change shared dimensions, optionally re-checking all documents |
| `export_project` | Export every linked document to its native format in one call |
| `get_history` | Recent change history (`.forge.history`) for a document or project |
| `get_project_summary` | Quick project status: docs, dims, exports, last change — no docs loaded |

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
| `auto_place` | Pack a hardware document's components inside the board outline (no overlaps, locked components respected) |
| `route_board` | Autoroute a placed board: 2-layer maze routing into real KiCad track/via copper (unroutable nets reported, not fatal) |
| `analyze_image` | Photo → ForgeLab document skeleton (vision) |
| `critique_render` | Vision critique of a rendered preview vs the design intent — structured issues + suggested changes |

## Token optimization

- **Work by file path.** `validate_document` and `export_document` take a `document_path`; agents write a document once and process it by path — no large JSON in context.
- **Edit by patch.** `patch_document` applies an RFC 6902 JSON Patch, so changing one component is a few hundred bytes, not a full re-emission.
- **Project what you need.** Pass `projection` (`metadata`/`topology`/`geometry`/`full`) to receive only the relevant slice; stripping happens server-side.
- **Compute, don't guess.** The five `calculate_*` tools handle geometry and electrical math deterministically instead of inline.
- **Project files.** Tie board, enclosure, and render documents together with shared dimensions as a single source of truth; export all formats in one call via `export_project`.

## Project status

**Pre-alpha** (library v0.1, spec v0.5.0). Three working domains (**hardware**, **mechanical**, **3D**), **36 MCP tools**, and **672 tests** green. Shipped: the IR, validator, compiler pipeline, and REST API; three round-trips (**KiCad**, **glTF**, **FreeCAD**) plus **OBJ/STL import** and a **Blender script** export that renders a finished product shot; the **project** concept (shared dimensions across board + enclosure + render, exported in one call); a **component library** of 32 pre-built parts with datasheet pad geometry; the **AI SDK**, the **OAuth 2.0** module, and the **MCP server**. Remaining tool integrations (Altium, Fusion 360, Unreal, and Gerber *import*) are scaffolded stubs. APIs may change before 1.0.

## Roadmap

- [x] Core IR, validator, registry, compiler pipeline; AI SDK + REST service
- [x] KiCad `.kicad_pcb`, glTF `.gltf` (Blender), and FreeCAD `.FCStd` round-trips
- [x] OAuth 2.0 auth + MCP server (stdio + Streamable HTTP)
- [x] Multi-tool workflows + zero-friction agent setup (installer, `forgelab init`, bootstrap prompts)
- [ ] Publish to PyPI so `pip install forgelab` works without cloning
- [ ] Hardware: Gerber import, Altium · Mechanical: Fusion 360 · 3D: Unreal, glTF textures/animations, `.glb`
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
