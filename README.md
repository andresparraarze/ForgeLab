# ForgeLab

> **The LLVM of design.** A universal, JSON-based interchange format and compiler that lets AI agents create, read, and transform design files across tools and domains — without ever touching proprietary formats.

[![CI](https://github.com/andresparraarze/ForgeLab/actions/workflows/ci.yml/badge.svg)](https://github.com/andresparraarze/ForgeLab/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![Spec](https://img.shields.io/badge/spec-v0.5.0-orange.svg)](forgelab/spec/version.py)
[![Status](https://img.shields.io/badge/status-pre--alpha-red.svg)](#status--roadmap)

ForgeLab defines a JSON **intermediate representation (IR)** between AI agents and design software. Any
tool can *import* its native files into the IR and *export* the IR back. Agents work **entirely in
ForgeLab JSON** — no proprietary formats, no special training.

```
native file ──import──▶ ForgeLab IR ──transform──▶ ForgeLab IR ──export──▶ native file
                          ▲                                        │
                          └──────────── AI agents ─────────────────┘
                                   (pure JSON, no proprietary formats)
```

**Contents:** [Tool support](#tool-support) · [Install](#install) · [Connect an agent](#connect-an-agent) ·
[Use from Python](#use-from-python) · [MCP tools](#mcp-tools) · [Multi-tool workflows](#multi-tool-workflows) ·
[How it works](#how-it-works) · [REST service & auth](#rest-service--auth) · [Status & roadmap](#status--roadmap) ·
[Contributing](#contributing)

## Tool support

| Domain         | Tool          | Import | Export | Notes                                        |
| -------------- | ------------- | :----: | :----: | -------------------------------------------- |
| Hardware       | KiCad         |   ✅   |   ✅   | `.kicad_pcb` round-trip (components/nets/board) |
| Hardware       | Altium        |   🚧   |   🚧   | stub — contributions welcome                 |
| Hardware       | Gerber        |   🚧   |   🚧   | stub — contributions welcome                 |
| Mechanical CAD | FreeCAD       |   ✅   |   ✅   | `.FCStd` round-trip (parts/bodies/features/sketches) |
| Mechanical CAD | Fusion 360    |   🚧   |   🚧   | stub                                         |
| 3D / Game      | glTF          |   ✅   |   ✅   | `.gltf` round-trip (meshes/materials/scene)  |
| 3D / Game      | Blender       |   ✅   |   ✅   | via glTF interchange; native `.blend` 🚧     |
| 3D / Game      | Unreal Engine |   🚧   |   🚧   | stub                                         |

✅ implemented · 🚧 stub (base classes in place, awaiting implementation)

## Install

Requires **Python 3.11+**. No KiCad or FreeCAD install needed — native files are parsed directly.

```bash
git clone https://github.com/andresparraarze/ForgeLab
cd ForgeLab
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,api]"
```

Optional extras — install what you need:

| Extra   | Enables                                          | Pulls in                                   |
| ------- | ------------------------------------------------ | ------------------------------------------ |
| `agent` | `ForgeAgent` (natural language → ForgeDocument)  | `anthropic`                                |
| `api`   | the REST service                                 | `uvicorn`                                  |
| `auth`  | OAuth 2.0 for the REST API / MCP HTTP            | `pyjwt`, `cryptography`, `python-multipart`|
| `mcp`   | the MCP server (`forgelab-mcp`)                  | `mcp`                                       |

```bash
pip install -e ".[mcp,agent]"   # e.g. everything an MCP-connected agent needs
```

## Connect an agent

The MCP server is the fastest way to put ForgeLab in an agent's hands.

**One line (Claude Code)** — installs into `~/.forgelab`, registers the server, sets up `~/forgelab-output`:

```bash
curl -fsSL https://raw.githubusercontent.com/andresparraarze/ForgeLab/main/scripts/install-claude-code.sh | bash
```

**`forgelab init` (any agent)** — interactive setup that registers the server (Claude Code) or prints
the config block to paste (Hermes, OpenClaw, any MCP client). Run `forgelab update` to upgrade later.

**Manual (Claude Code)** — register with an absolute venv path:

```bash
claude mcp add forgelab -- /path/to/ForgeLab/.venv/bin/forgelab-mcp --transport stdio
```

For Hermes, OpenClaw, and other clients, [docs/agent-bootstrap.md](docs/agent-bootstrap.md) has
copy-paste prompts that install, register, and verify the server.

Then ask Claude Code: *"generate a blinky LED board and export it to KiCad"* — it chains
`generate_document` → `export_document` and hands you the `.kicad_pcb`.

> `generate_document` needs `ANTHROPIC_API_KEY` in the **server's** environment; everything else works
> without it. Call `generation_status` to check before relying on it.

## Use from Python

**Natural language → a real KiCad file** with the AI SDK (requires `pip install "forgelab[agent]"`):

```python
from forgelab.sdk import ForgeAgent
from forgelab.exporters.hardware.kicad import KiCadExporter

agent = ForgeAgent()                                    # reads ANTHROPIC_API_KEY
doc = agent.design("a blinky LED board with one resistor and one LED",
                   domain="hardware")                   # NL -> validated ForgeDocument
with open("blinky.kicad_pcb", "wb") as f:
    f.write(KiCadExporter().from_ir(doc))               # -> real KiCad file
```

The lower-level, provider-agnostic building blocks:

```python
from forgelab.sdk import domain_schema, system_prompt, few_shot, validate_llm_output, new_document, dump, load

domain_schema("hardware")                         # tight JSON Schema for structured-output / tools
system_prompt("threed")                           # ready-made system prompt for any LLM
few_shot("threed")                                # (request, valid-JSON) examples
validate_llm_output(raw_text, domain="hardware")  # clean + parse + validate, or raise
load(dump(new_document(domain="hardware", name="blinky")))  # hand-build documents
```

**Round-trip any supported file.** Import to IR, edit as JSON, export back — and `import → export →
import` is an identity over the IR:

```python
from forgelab.importers.hardware.kicad import KiCadImporter
from forgelab.exporters.hardware.kicad import KiCadExporter

doc = KiCadImporter().to_ir(open("examples/hardware/blinky.kicad_pcb", "rb").read())
print([n.id for n in doc.nodes if n.type == "component"])   # ['R1', 'D1']

kicad_bytes = KiCadExporter().from_ir(doc)                  # ForgeDocument -> .kicad_pcb
assert KiCadImporter().to_ir(kicad_bytes) == doc            # stable round-trip
```

The same pattern works for the other domains:

- **glTF** — `GltfImporter` / `GltfExporter` (`forgelab.{importers,exporters}.threed.gltf`). Mesh
  geometry is decoded into plain JSON arrays (positions, indices), so agents read and edit scenes
  directly. The threed domain is **Y-up** (glTF's native axis).
- **FreeCAD** — `FreeCADImporter` / `FreeCADExporter` (`forgelab.{importers,exporters}.mechanical`).
  The parametric feature tree (parts, bodies, sketches with dimensions, pads, pockets) becomes plain
  JSON nodes. Parsing uses only the standard library (`zipfile` + `xml.etree`). Exported `.FCStd`
  files open in FreeCAD with the tree intact — press **Refresh** (`Ctrl+R`) once to build geometry
  from the parametric definitions. Validated against FreeCAD 1.1.

Sample designs for each domain live in [`examples/`](examples/).

## MCP tools

Whichever client you connect, the agent sees the same nine tools. Over stdio all are available
locally; over HTTP each requires its scope on the bearer token.

| Tool | What it does | Scope |
| --- | --- | --- |
| `list_domains`, `list_formats`   | discover supported domains and format tools     | `forge:read` |
| `get_domain_schema`, `get_prompt`| JSON Schema + prompt templates per domain       | `forge:read` |
| `validate_document`              | validate a ForgeLab document                    | `forge:read` |
| `generation_status`              | report whether `generate_document` is usable    | `forge:read` |
| `export_document`, `import_file` | IR ↔ native files (KiCad, glTF, FreeCAD)        | `forge:export` |
| `generate_document`              | natural language → validated ForgeDocument      | `forge:generate` |

Run the server standalone (`pip install "forgelab[mcp]"`):

```bash
forgelab-mcp --transport stdio                                      # local, no auth
FORGELAB_AUTH_ENABLED=true forgelab-mcp --transport streamable-http --port 8001   # remote, OAuth
```

For HTTP discovery metadata, optionally set `FORGELAB_MCP_ISSUER_URL` (OAuth authorization server)
and `FORGELAB_MCP_RESOURCE_URL` (this server's public URL).

## Multi-tool workflows

ForgeLab sits next to tool-specific MCP servers (KiCad MCP, Blender MCP, FreeCAD MCP, Unreal MCP):
ForgeLab generates and compiles the design, the tool MCP opens it. The handoff is a file on disk.

- `export_document` takes an optional **`output_path`**. When set, ForgeLab writes the file and
  returns `{"tool", "path", "bytes_written"}` (instead of inline content) — pass `path` straight to
  the tool MCP.
- **`FORGELAB_OUTPUT_DIR`** is the default directory for bare filenames (`"blinky.kicad_pcb"`).
  Absolute paths are used as-is.

Wire ForgeLab and the tool MCPs to one shared folder in `.mcp.json`:

```json
{
  "mcpServers": {
    "forgelab": {
      "command": "/path/to/ForgeLab/.venv/bin/forgelab-mcp",
      "args": ["--transport", "stdio"],
      "env": { "ANTHROPIC_API_KEY": "sk-...", "FORGELAB_OUTPUT_DIR": "/home/you/designs" }
    },
    "kicad": { "command": "kicad-mcp", "env": { "KICAD_PROJECT_DIR": "/home/you/designs" } }
  }
}
```

Prompt *"Design a blinky LED board, then open it in KiCad"* and the agent chains:
`generate_document` → `export_document(tool="kicad", output_path="blinky.kicad_pcb")` →
`kicad.open_project(path=…)`. The same chain works for `threed`+`gltf` (Blender/Unreal) and
`mechanical`+`freecad` (FreeCAD). (Tool-MCP commands above are placeholders — use each server's own
install instructions and point it at `FORGELAB_OUTPUT_DIR`.)

## How it works

A ForgeLab document is a small typed envelope — `forgelab_version`, `domain`, `meta` — wrapping a
generic graph of `Node` objects. Domain vocabularies layer on top: a hardware board is a `board` node
plus `net` and `component` nodes, each carrying a validated typed payload in its `props`.

Importers and exporters depend only on the spec and on shared format primitives (`forgelab.formats`,
e.g. the S-expression parser) — never on each other. Every tool is an independent, testable plugin,
so adding the next one is a contained change.

```
forgelab/
├── spec/        # IR models (Pydantic v2), versioning, JSON Schema, domain vocabularies
├── core/        # validate(), registry, compiler pipeline, errors
├── formats/     # shared zero-dependency format primitives (S-expression, glTF, FCStd)
├── importers/   # tool → IR  (base ABC + KiCad, glTF, FreeCAD)
├── exporters/   # IR → tool  (base ABC + KiCad, glTF, FreeCAD)
├── sdk/         # AI agent helpers (schemas, prompts, validation, ForgeAgent)
├── auth/        # shared OAuth 2.0 (verification, dev authorization server, scopes)
├── mcp/         # MCP server (stdio + OAuth-protected Streamable HTTP)
├── api/         # FastAPI compiler-as-a-service
└── cli.py       # `forgelab init` agent setup
```

## REST service & auth

ForgeLab also runs as a compiler-as-a-service (`pip install "forgelab[api]"`):

```bash
uvicorn forgelab.api.app:app --reload
```

| Method | Path             | Purpose                      |
| ------ | ---------------- | ---------------------------- |
| GET    | `/health`        | liveness + spec version      |
| GET    | `/spec`          | ForgeDocument JSON Schema    |
| POST   | `/validate`      | validate a ForgeLab document |
| POST   | `/export/{tool}` | export IR to a tool's format |

The REST API and the MCP HTTP transport can be protected with **OAuth 2.0** (off by default; install
`forgelab[auth]`). Set `FORGELAB_AUTH_ENABLED=true` and either `FORGELAB_AUTH_MODE=dev` (built-in
HS256 issuer) or `=jwks` with your IdP's `ISSUER`/`AUDIENCE`/`JWKS_URL`. Scopes: `forge:read`
(validate/spec/schema), `forge:export` (import/export), `forge:generate` (AI generation).

```bash
TOKEN=$(curl -s -X POST localhost:8000/oauth/token \
  -d grant_type=client_credentials \
  -d client_id=forgelab-dev -d client_secret=forgelab-dev-secret \
  -d scope="forge:read" | jq -r .access_token)

curl -s -X POST localhost:8000/validate \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d @doc.forge.json
```

## Status & roadmap

**Pre-alpha** (library v0.1, spec v0.5.0). The IR, validator, compiler pipeline, REST API, three
round-trips (**KiCad**, **glTF**, **FreeCAD**), the **AI SDK**, the **OAuth 2.0** module, and the
**MCP server** all work and are covered by tests. Remaining tool integrations are scaffolded stubs.
APIs may change before 1.0.

Every document carries a `forgelab_version`; compatibility is major-based (`SPEC_VERSION` in
`forgelab/spec/version.py`). See [CHANGELOG.md](CHANGELOG.md) for changes.

- [x] Core IR, validator, registry, compiler pipeline; AI SDK + REST service
- [x] KiCad `.kicad_pcb`, glTF `.gltf` (Blender), and FreeCAD `.FCStd` round-trips
- [x] OAuth 2.0 auth + MCP server (stdio + Streamable HTTP)
- [x] Multi-tool workflows + zero-friction agent setup (installer, `forgelab init`, bootstrap prompts)
- [ ] Publish to PyPI so `pip install forgelab` works without cloning
- [ ] Hardware: Gerber, Altium · Mechanical: Fusion 360 · 3D: Unreal, glTF textures/animations, `.glb`
- [ ] Transform passes (design-rule checks, layer remaps) over the IR; HTTP `/import` endpoint

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The highest-leverage start is an importer/exporter for one
tool against the `Importer`/`Exporter` base classes — the KiCad pair is a complete worked example.

```bash
ruff check . && ruff format --check . && pyright && pytest
```

## License

[Apache 2.0](LICENSE).
