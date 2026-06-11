# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- One-command agent setup: `scripts/install-claude-code.sh` (one-line Claude
  Code installer), a `forgelab init` CLI that registers the MCP server with
  Claude Code or prints the config for Hermes/OpenClaw/other agents, and
  copy-paste bootstrap prompts in `docs/agent-bootstrap.md`.
- `export_document` gained an optional `output_path` (writes the exported file
  to disk and returns its path) and the `FORGELAB_OUTPUT_DIR` default output
  directory for multi-MCP workflows.
- MCP server (`forgelab/mcp/`): exposes ForgeLab as MCP tools over stdio (local)
  and OAuth-protected Streamable HTTP (remote) using the official MCP SDK. Tools:
  `validate_document`, `get_domain_schema`, `get_prompt`, `list_domains`,
  `list_formats` (`forge:read`); `export_document`, `import_file`
  (`forge:export`); `generate_document` (`forge:generate`, returns a clear error
  when `ANTHROPIC_API_KEY` is unset). Reuses the `forgelab.auth` module as the
  resource-server verifier. Run with `forgelab-mcp --transport stdio|streamable-http`.
  Optional `[mcp]` extra.
- `Registry.tool_names()` read accessor reporting per-tool import/export availability.
- Shared OAuth 2.0 auth module (`forgelab/auth/`): pluggable token verification
  (built-in dev HS256 issuer + external JWKS/RS256 verifier), a self-contained
  dev authorization server supporting `client_credentials` and
  `authorization_code`+PKCE(S256) with RFC 8414 discovery, and a FastAPI
  `require_auth(*scopes)` dependency. Scopes: `forge:read`, `forge:export`,
  `forge:generate`. Optional `[auth]` extra.
- REST API endpoints `/validate` (`forge:read`) and `/export/{tool}`
  (`forge:export`) are now scope-protected; `/health` and `/spec` stay public.
  Auth is off by default (`FORGELAB_AUTH_ENABLED=false`).
- Mechanical CAD domain: typed vocabulary (`forgelab/spec/mechanical.py` —
  Part/Body/Sketch/SketchGeometry/Constraint/Pad/Pocket/Placement), a stdlib-only
  FCStd codec (`forgelab/formats/fcstd.py`), real FreeCAD `.FCStd`
  importer/exporter with an IR-level round-trip guarantee, and a box-with-hole
  example.
- Mechanical domain registered in the AI SDK (`domain_schema`/`system_prompt`/
  `few_shot`/`validate_llm_output` now support `"mechanical"`).
- AI SDK (`forgelab/sdk/`): `domain_schema()` tight per-domain JSON Schema,
  `system_prompt()`/`few_shot()` prompt templates, `validate_llm_output()` for
  cleaning and validating raw LLM output, and `ForgeAgent` (Claude-backed,
  configurable model, natural language -> validated `ForgeDocument`).
- `Scene` model in the 3D vocabulary; `LLMOutputError` in the core error
  hierarchy; optional `agent` extra (`pip install "forgelab[agent]"`).
- Initial scaffold: `spec` IR models (`ForgeDocument`, `Node`, `Domain`) with a
  required `forgelab_version` field and major-version compatibility checks.
- `core` compiler: `validate()`, tool registry, and transform pipeline.
- Importer/exporter base ABCs plus stubs for KiCad, Altium, Gerber, Fusion 360,
  FreeCAD, Blender, and Unreal Engine.
- AI SDK helpers: `new_document`, `load`, `dump`.
- FastAPI compiler-as-a-service: `/health`, `/spec`, `/validate`, `/export/{tool}`.
- JSON Schema export of the IR.
- Tooling: Ruff, Pyright, Pytest, and GitHub Actions CI.
- KiCad PCB importer and exporter with a verified IR-level round-trip
  (components, nets, and board constraints preserved).
- Typed hardware spec vocabulary (`Component`, `Pad`, `Net`, `BoardLayer`,
  `OutlineSegment`, `DesignRules`, `BoardConstraints`) serialized into the
  generic Node graph.
- `forgelab.formats` package with a zero-dependency S-expression parser/writer.
- Real `examples/hardware/blinky.kicad_pcb` board.
- 3D / game domain: typed `threed` vocabulary (`Material`, `Mesh`, `Primitive`,
  `Transform`, `Object3D`) serialized into the generic Node graph, with scene
  hierarchy expressed via `Node.children`.
- glTF importer and exporter (`tool_name="gltf"`) with a verified IR-level
  `.gltf` round-trip; mesh geometry is fully decoded into JSON arrays (no opaque
  buffers). Registered in the default pipeline registry.
- glTF accessor/buffer codec in `forgelab.formats` (zero-dependency,
  base64-embedded buffers).
- Real `examples/threed/cube.gltf` (red cube) and its generated `cube.forge.json`.

### Changed
- `SPEC_VERSION` bumped to `0.5.0` (additive hardware, 3D, AI-SDK, then
  mechanical vocabularies; root model unchanged; backward compatible —
  compatibility remains major-based). Example `.forge.json` files regenerated.
- `forgelab.importers.mechanical` and `forgelab.exporters.mechanical` are now
  packages (FreeCAD implemented; Fusion 360 native stubs preserved).
- Importers/exporters may now depend on `forgelab.formats` (shared neutral
  format primitives) in addition to `forgelab.spec`.
- `forgelab.importers.threed` and `forgelab.exporters.threed` are now packages
  (glTF implemented; Blender/Unreal native stubs preserved).

[Unreleased]: https://github.com/forgelab/forgelab/commits/main
