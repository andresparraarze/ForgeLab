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
- [Use ForgeLab from your agent](#use-forgelab-from-your-agent)
  - [Claude Code](#claude-code)
  - [Hermes](#hermes)
  - [OpenClaw](#openclaw)
- [Multi-tool workflows](#multi-tool-workflows)
- [Quickstart](#quickstart)
  - [Build IR with the AI SDK](#build-ir-with-the-ai-sdk)
  - [Round-trip a KiCad board](#round-trip-a-kicad-board)
  - [Round-trip a glTF scene](#round-trip-a-gltf-scene)
  - [Round-trip a FreeCAD model](#round-trip-a-freecad-model)
  - [Run the compiler service](#run-the-compiler-service)
  - [Authentication (optional)](#authentication-optional)
  - [MCP server (optional)](#mcp-server-optional)
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
`.kicad_pcb` S-expression format directly, so **no KiCad installation is required** (same for
FreeCAD: `.FCStd` is parsed with the standard library).

Optional extras, install what you need:

| Extra | Enables | Pulls in |
| --- | --- | --- |
| `agent` | `ForgeAgent` (natural language → ForgeDocument) | `anthropic` |
| `api` | running the REST service | `uvicorn` |
| `auth` | OAuth 2.0 protection for the REST API / MCP HTTP | `pyjwt`, `cryptography`, `python-multipart` |
| `mcp` | the MCP server (`forgelab-mcp`) | `mcp` |

```bash
pip install -e ".[mcp,agent]"   # e.g. everything an MCP-connected agent needs
```

## Use ForgeLab from your agent

The MCP server is the fastest way to put ForgeLab in an agent's hands. Three
ways to connect, from easiest to most manual:

**1. One line (Claude Code):**

```bash
curl -fsSL https://raw.githubusercontent.com/andresparraarze/ForgeLab/main/scripts/install-claude-code.sh | bash
```

Checks Python, creates a venv in `~/.forgelab`, installs `forgelab[mcp,agent]`,
registers the MCP server with Claude Code, and sets up `~/forgelab-output` as
the export directory. Done.

**2. `forgelab init` (any agent):** if you already have ForgeLab installed,
run the interactive setup — it asks which agent you use and where exports
should go, then registers the server (Claude Code) or prints the exact config
block to paste (Hermes / OpenClaw / anything else):

```bash
forgelab init
```

**3. Paste a bootstrap prompt:** let your agent set itself up.
[docs/agent-bootstrap.md](docs/agent-bootstrap.md) has copy-paste prompts for
Hermes, OpenClaw, and any MCP-compatible agent that install ForgeLab, register
the server, and verify the tools with `list_domains`.

**Updating:** once installed, upgrade to the latest version with one command —
it refreshes the `~/.forgelab` install from GitHub and prints the new spec
version:

```bash
forgelab update
```

For manual setup, the per-client details follow. The examples use stdio
(local, no auth); for a shared/remote server, run
`forgelab-mcp --transport streamable-http` behind OAuth (see
[MCP server](#mcp-server-optional)) and register it as an HTTP MCP server instead.
`generate_document` needs `ANTHROPIC_API_KEY` in the server's environment;
everything else works without it.

### Claude Code

Register the server with the `claude mcp` CLI (use the venv's absolute path so
it works regardless of the shell's environment):

```bash
claude mcp add forgelab -- /path/to/ForgeLab/.venv/bin/forgelab-mcp --transport stdio
```

Or add it to `.mcp.json` in your project to share it with your team:

```json
{
  "mcpServers": {
    "forgelab": {
      "command": "/path/to/ForgeLab/.venv/bin/forgelab-mcp",
      "args": ["--transport", "stdio"],
      "env": { "ANTHROPIC_API_KEY": "sk-..." }
    }
  }
}
```

Then ask Claude Code things like *"generate a blinky LED board and export it to
KiCad"* — it will chain `generate_document` → `export_document` and hand you the
`.kicad_pcb` content.

### Hermes

Hermes speaks MCP over Streamable HTTP. Run the server with auth enabled,
mint a token from the built-in dev authorization server (or your IdP), and
point Hermes at the endpoint:

```bash
FORGELAB_AUTH_ENABLED=true forgelab-mcp --transport streamable-http --port 8001
```

Configure the Hermes MCP connection with:

- **URL:** `http://your-host:8001/mcp`
- **Authorization:** `Bearer <token>` — get one via
  `POST /oauth/token` on the REST API (see [Authentication](#authentication-optional)),
  requesting the scopes the agent needs (`forge:read forge:export forge:generate`).

For local/trusted Hermes deployments that support stdio servers, the
`forgelab-mcp --transport stdio` command works there too.

### OpenClaw

OpenClaw consumes MCP servers via its standard MCP configuration. For a local
setup, register the stdio command:

```json
{
  "mcpServers": {
    "forgelab": {
      "command": "/path/to/ForgeLab/.venv/bin/forgelab-mcp",
      "args": ["--transport", "stdio"]
    }
  }
}
```

For a remote OpenClaw deployment, use the OAuth-protected HTTP endpoint exactly
as in the Hermes setup: URL `http://your-host:8001/mcp` plus a bearer token with
the appropriate `forge:*` scopes.

### What the agent gets

Whichever client you use, the agent sees the same eight tools:

| Tool | What it does | Scope (HTTP) |
| --- | --- | --- |
| `list_domains`, `list_formats` | discover supported domains and format tools | `forge:read` |
| `get_domain_schema`, `get_prompt` | JSON Schema + prompt templates per domain | `forge:read` |
| `validate_document` | validate a ForgeLab document | `forge:read` |
| `export_document`, `import_file` | IR ↔ native files (KiCad, glTF, FreeCAD) | `forge:export` |
| `generate_document` | natural language → validated ForgeDocument | `forge:generate` |

Over stdio everything is available locally; over HTTP each tool requires its
scope on the bearer token. `generate_document` needs `ANTHROPIC_API_KEY` set on
the **server** and returns a clear error if it is missing.

## Multi-tool workflows

ForgeLab is designed to sit next to tool-specific MCP servers (KiCad MCP,
Blender MCP, FreeCAD MCP, Unreal MCP): ForgeLab generates and compiles the
design, the tool MCP opens it. The handoff is a file on disk:

- `export_document` takes an optional **`output_path`**. When provided,
  ForgeLab writes the exported file to disk and returns
  `{"tool", "path", "bytes_written"}` instead of inline content — the agent
  passes `path` straight to the tool MCP.
- **`FORGELAB_OUTPUT_DIR`** sets the default output directory: a bare filename
  (`"blinky.kicad_pcb"`) is written there. Unset, bare filenames go to the
  current working directory. Absolute paths and paths containing directories
  are used as-is.

A single `.mcp.json` wiring ForgeLab together with tool MCPs into one shared
folder:

```json
{
  "mcpServers": {
    "forgelab": {
      "command": "/path/to/ForgeLab/.venv/bin/forgelab-mcp",
      "args": ["--transport", "stdio"],
      "env": {
        "ANTHROPIC_API_KEY": "sk-...",
        "FORGELAB_OUTPUT_DIR": "/home/you/designs"
      }
    },
    "kicad": {
      "command": "kicad-mcp",
      "env": { "KICAD_PROJECT_DIR": "/home/you/designs" }
    },
    "blender": { "command": "blender-mcp" },
    "freecad": { "command": "freecad-mcp" },
    "unreal":  { "command": "unreal-mcp" }
  }
}
```

(The tool-MCP commands and env vars above are placeholders — use the install
instructions of whichever KiCad/Blender/FreeCAD/Unreal MCP server you run, and
point it at the same directory as `FORGELAB_OUTPUT_DIR`.)

Example prompt to Claude Code:

> "Design a blinky LED board with one resistor and one LED, then open it in
> KiCad."

The agent's tool-call chain:

1. `forgelab.generate_document(prompt="a blinky LED board…", domain="hardware")`
   → validated ForgeDocument (JSON).
2. `forgelab.export_document(document=…, tool="kicad", output_path="blinky.kicad_pcb")`
   → `{"path": "/home/you/designs/blinky.kicad_pcb", "bytes_written": …}`.
3. `kicad.open_project(path="/home/you/designs/blinky.kicad_pcb")` (or the
   equivalent tool on your KiCad MCP) — the board opens in KiCad.

The same chain works for the other domains: `domain="threed"` +
`tool="gltf"` → Blender MCP imports the `.gltf`; `domain="mechanical"` +
`tool="freecad"` → FreeCAD MCP opens the `.FCStd`; Unreal consumes glTF
exports the same way.

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

Exported `.FCStd` files use FreeCAD's real document schema and **open directly
in FreeCAD** — shapes recompute from the parametric definitions on load
(validated against FreeCAD 1.1). The importer also reads genuine
FreeCAD-authored files (canonical subset: parts, bodies, sketches with
line/circle geometry and dimensional constraints, pads, pockets — Origin
planes/axes and other unmodeled objects are skipped). The IR round-trip
identity is preserved via a `ForgeLab.Document.xml` sidecar entry that FreeCAD
ignores.

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

### Authentication (optional)

The REST API and the MCP server's HTTP transport can be protected with OAuth 2.0.
It is **off by default**. Enable it with environment variables:

```bash
export FORGELAB_AUTH_ENABLED=true       # turn auth on
export FORGELAB_AUTH_MODE=dev           # built-in dev issuer (HS256)
# or point at an external IdP:
# export FORGELAB_AUTH_MODE=jwks
# export FORGELAB_AUTH_ISSUER=https://your-idp/
# export FORGELAB_AUTH_AUDIENCE=forgelab
# export FORGELAB_AUTH_JWKS_URL=https://your-idp/.well-known/jwks.json
```

Get a token from the built-in dev server and call a protected endpoint:

```bash
TOKEN=$(curl -s -X POST localhost:8000/oauth/token \
  -d grant_type=client_credentials \
  -d client_id=forgelab-dev -d client_secret=forgelab-dev-secret \
  -d scope="forge:read" | jq -r .access_token)

curl -s -X POST localhost:8000/validate \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d @doc.forge.json
```

Scopes: `forge:read` (validate/spec/schema), `forge:export` (import/export),
`forge:generate` (AI generation). Install with `pip install "forgelab[auth]"`.

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
error if it is unset. For HTTP discovery metadata you may also set
`FORGELAB_MCP_ISSUER_URL` (the OAuth authorization server) and
`FORGELAB_MCP_RESOURCE_URL` (this server's public URL).

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
├── spec/        # IR models (Pydantic v2), versioning, JSON Schema export, domain vocabularies
├── core/        # validate(), registry, compiler pipeline, errors
├── formats/     # shared, zero-dependency format primitives (S-expression, glTF, FCStd)
├── importers/   # tool → IR  (base ABC + per-domain packages; KiCad, glTF, FreeCAD implemented)
├── exporters/   # IR → tool  (base ABC + per-domain packages; KiCad, glTF, FreeCAD implemented)
├── sdk/         # AI agent helpers (schemas, prompts, validation, ForgeAgent)
├── auth/        # shared OAuth 2.0 (token verification, dev authorization server, scopes)
├── mcp/         # MCP server (stdio + OAuth-protected Streamable HTTP)
├── api/         # FastAPI compiler-as-a-service
└── cli.py       # `forgelab init` agent setup
scripts/         # one-line Claude Code installer
docs/            # agent bootstrap prompts, design specs and plans
examples/        # real sample designs (one native file + generated .forge.json per domain)
tests/           # pytest suite, including all three round-trip guarantees
```

## Spec versioning

Every document carries a `forgelab_version`. Compatibility is **major-based**: a document validates
against any library sharing its major version. The current spec is **v0.5.0** (`SPEC_VERSION` in
`forgelab/spec/version.py`). Any change to the `ForgeDocument` root or a breaking change to a domain
vocabulary bumps the version — see [CONTRIBUTING.md](CONTRIBUTING.md) and [CHANGELOG.md](CHANGELOG.md).

## Project status

**Pre-alpha (v0.1 of the library, v0.5.0 of the spec).** The IR, validator, compiler pipeline, API,
three end-to-end round-trips — the **KiCad `.kicad_pcb`** (hardware), the **glTF `.gltf`** (3D /
game), and the **FreeCAD `.FCStd`** (mechanical CAD) importer/exporter pairs — the **AI SDK**
(schema export, prompt templates, output validation, and a Claude-backed `ForgeAgent`), the
**OAuth 2.0 auth module**, and the **MCP server** (stdio + Streamable HTTP) all work and are
covered by tests. The remaining tool integrations are scaffolded stubs awaiting implementation.
APIs may change before 1.0.

## Roadmap

- [x] Core IR, validator, registry, and compiler pipeline
- [x] AI SDK and FastAPI compiler service
- [x] Typed hardware vocabulary + S-expression format primitive
- [x] KiCad `.kicad_pcb` importer/exporter round-trip
- [x] 3D / Game: Blender via glTF round-trip (meshes, materials, scene hierarchy)
- [ ] Hardware: Gerber and Altium
- [x] Mechanical CAD: FreeCAD `.FCStd` importer/exporter round-trip
- [x] Shared OAuth 2.0 auth (scopes, dev authorization server, JWKS verification)
- [x] MCP server (stdio + OAuth-protected Streamable HTTP) for Claude Code / Hermes / OpenClaw
- [x] Multi-tool workflow support (`export_document` `output_path` + `FORGELAB_OUTPUT_DIR`)
- [x] Zero-friction agent setup (one-line installer, `forgelab init` CLI, agent bootstrap prompts)
- [ ] Publish to PyPI so `pip install forgelab` works without cloning the repo
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
