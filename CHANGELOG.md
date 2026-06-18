# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- MCP server: new `generation_status` tool reports whether `generate_document`
  is usable on this server (needs both `ANTHROPIC_API_KEY` set and the `agent`
  extra installed) without calling it. When unavailable it returns a `reason`
  and an `alternative` telling the agent to build against the schema
  (`get_domain_schema` + `get_prompt`) and validate once — so agents can skip a
  wasted `generate_document` round trip that would only fail.

### Changed
- SDK prompts: each domain's `system_prompt` now instructs the agent to build
  the complete document in a single pass — consult the schema first, assemble
  every node and prop, then call `validate_document` once — rather than
  iterating with repeated validation calls. Surfaced to external agents through
  the MCP `get_prompt` tool.
- threed domain: `system_prompt` (via `get_prompt`) and the `mesh`/`material`
  reference field descriptions in the JSON schema (via `get_domain_schema`) now
  state explicitly that references must use the target node's `id`, not its
  display `name`, with a `mat_red` (id) vs `vermilion` (name) example — so
  agents stop referencing materials/meshes by name.
- threed domain: documented the **Y-up** coordinate convention (matching glTF's
  native axis) in the spec, the glTF exporter, and `system_prompt` (via
  `get_prompt`). Agents are now told to author height on the Y axis, not Z —
  a Z-up document gets double-converted by Blender's Y-up→Z-up importer and
  lands tipped 90°. The exporter already passes coordinates straight through
  (no rotation); the fix is making the contract explicit so geometry imports
  upright.
- `export_document`: the `output_path` description now tells agents to prefer a
  bare filename (e.g. `"castle.gltf"`) so output lands in the configured
  `FORGELAB_OUTPUT_DIR`, and to pass an absolute path only when writing
  elsewhere — agents were passing absolute paths and bypassing the configured
  directory.

### Fixed
- KiCad exporter: pads no longer stack at the footprint origin. Every pad was
  emitted with `(at 0 0)`, so a multi-pin part (e.g. a 29-pad HTSSOP-28) visually
  collapsed onto a single point. The `Pad` model gained an optional `at` ([x, y]
  offset from the footprint origin) plus optional `size`/`shape`; the exporter
  now emits each pad's real `at` when provided, and when it is omitted spreads
  pads on a centred deterministic grid so they never overlap. The importer reads
  pad `at`/`size`/`shape` back (round-trip stable). `system_prompt('hardware')`
  (via `get_prompt`) and the `Pad.at` JSON-schema description (via
  `get_domain_schema`) now tell agents to set each pad's physical offset.
- glTF exporter: a `mesh`/`material` reference that doesn't match a node id
  (commonly a display name used by mistake) now raises a clear error naming the
  bad reference and listing the valid ids, instead of a cryptic `KeyError` that
  silently failed the export. Surfaced through `export_document` as
  `export failed for 'gltf': ...`.
- Blender export: the unimplemented-`.blend` error now tells the agent to use
  `tool='gltf'` instead (Blender imports glTF natively), rather than a bare
  "not implemented" that left the agent to discover the alternative by trial.
- FreeCAD exporter: the body container is now visible on open (`Visibility=true`
  in `GuiDocument.xml`) alongside its tip feature, matching FreeCAD's normal
  PartDesign display state — the body node is no longer greyed-out requiring a
  click of the eye icon. The body shows the tip's fully-cut solid (verified in
  FreeCAD 1.1: the body renders the holed solid, not the bare base plate);
  intermediate features, sketches and origin datums stay hidden.
- FreeCAD exporter: a through-all pocket now actually cuts when `reversed` is
  not set. `Type=1` (ThroughAll) was already correct and the `Length` is ignored
  by FreeCAD for ThroughAll; the real cause was direction — a ThroughAll pocket
  cuts one way, so when its sketch sat on the far side of the solid it removed
  nothing (the bore left the plate volume unchanged). Through-all pockets are now
  emitted with `Midplane=true` so they cut symmetrically through everything
  regardless of pad direction. Features that arrive with `length=0` also get a
  part-scaled fallback length so the `Length` property is never `0`. Validated in
  FreeCAD 1.1: a 60×30×10 (18000mm³) plate with an unreversed through-bore now
  recomputes to 15989.4mm³.
- FreeCAD exporter: the generated `GuiDocument.xml` now makes **only** the body's
  tip feature (the last solid in the chain — typically the final pocket) visible,
  hiding the body container, intermediate features, sketches and origin datums.
  Previously the body container was also marked visible, which could leave the
  part rendering as the bare base plate with the pocket cuts not shown until
  visibility was reset by hand in the Python console; showing only the tip makes
  the complete holed solid appear after a single recompute. The `GuiDocument`
  also now carries an isometric orthographic camera framed to the part's bounding
  box, so the part fits the view on open instead of starting off-screen.
- FreeCAD exporter: a Pad/Pocket `profile` now resolves when it references its
  sketch by the sketch's label/name (or is stale in a single-sketch body), not
  only by exact node id. Previously such a feature wrote an empty `Profile`
  link, so FreeCAD reported "<feature> no object linked" on open and built no
  solid. The profile is resolved by node id, then sketch label, then the sole
  sketch of the feature's body — the same lookup used for body references.
- FreeCAD exporter: a sketch now keeps its `AttachmentSupport` (and lands in its
  body's group) when its `body` is referenced by the body's label or left blank
  in a single-body part — not only when it exactly matches the body's node id.
  Previously such a sketch silently lost its datum-plane attachment, so it never
  oriented and the feature failed to build. The body is now resolved by node id,
  then by label, then (in a single-body part) the sole body. The `plane` value
  was always carried through correctly via the sidecar; the missing link was
  body resolution, not the plane.
- FreeCAD exporter: exported `.FCStd` files now render the solid shaded instead
  of wireframe-only. Previously no `GuiDocument.xml` view providers were written,
  so FreeCAD's defaults hid every solid and showed only the sketches as
  wireframe. The exporter now generates a `GuiDocument.xml` that makes each body
  and its tip feature visible (shaded "Flat Lines") and hides intermediate
  features, sketches, and origin datums (validated in FreeCAD 1.1's GUI). Note:
  the files carry no precomputed OpenCASCADE shapes, so a single **Refresh**
  (`Ctrl+R`) on open builds the geometry and resolves the Pad/Pocket `Profile`
  links — no manual `touch()` required.
- FreeCAD exporter: nodes nested via `Node.children` are no longer dropped.
  Agents express the part→body→feature hierarchy either as a flat node list or
  by nesting children; the exporter only iterated top-level `document.nodes`, so
  a nested document exported just the `App::Part` and its origin (`Count=9`) and
  silently omitted every `PartDesign::Body` / `Sketcher::SketchObject` /
  `PartDesign::Pad` / `PartDesign::Pocket`. Added `ForgeDocument.walk()` /
  `Node.walk()` (depth-first, pre-order) and the exporter now walks the whole
  tree. Flattening is lossless for the mechanical domain (body/part/feature
  relationships live in node props, not the tree shape).
- Installer: the PATH export now persists in new zsh sessions on Arch/
  EndeavourOS. zsh relocates its dotfiles via `$ZDOTDIR` (commonly
  `~/.config/zsh`), so writing to a bare `~/.zshrc` left the export in a file
  zsh never reads — users had to `source ~/.zshrc` every session. The installer
  now asks zsh where its dotfiles live and writes to `$ZDOTDIR/.zshrc`
  (interactive shells) and `$ZDOTDIR/.zprofile` (login shells: terminal
  emulators run as login shells, SSH, display managers), falling back to
  `$HOME` when `$ZDOTDIR` is unset or zsh is absent.
- FreeCAD exporter: every sketch with a body now emits `AttachmentSupport`
  regardless of how its plane is spelled. The attachment was gated on the plane
  being the exact string `XY_Plane`/`XZ_Plane`/`YZ_Plane`, so an agent writing
  `"XY"`, `"Front"`, `"Top"`, or leaving it blank produced an unattached sketch
  that never oriented and whose geometry never rendered. Plane names are now
  normalized (`XY`/`Top`→XY, `XZ`/`Front`→XZ, `YZ`/`Right`→YZ, unknown→XY).
  Added a `motor-mount` example (vertical flange on the XZ plane via the short
  `"XZ"` spelling); validated with FreeCAD 1.1 — plain recompute builds all
  solids and the flange orients vertically.
- FreeCAD exporter: sketches on non-XY datum planes (XZ/YZ) now orient
  correctly. Each body emits its own `App::Origin` and every sketch attaches to
  the body's datum plane via `AttachmentSupport` + `MapMode` (FlatFace) —
  FreeCAD ignores a plain `Placement` on an in-body sketch, which had left all
  sketches flat in XY and made pocket/pad profiles appear unlinked. Rotations
  are now written in the axis-angle form FreeCAD actually reads (a hardcoded
  `A="0"` had silently flattened every non-identity rotation). Validated with
  FreeCAD 1.1: a vertical-face pocket recomputes and cuts on plain open.
- FreeCAD importer recovers a sketch's datum plane from `AttachmentSupport`
  when reading genuine FreeCAD files.
- `forgelab update` now passes `--force-reinstall --no-cache-dir` to pip, so
  it always pulls the latest code from git instead of reporting "Requirement
  already satisfied" when the version string is unchanged.
- Exported FCStd objects are now marked `Touched="1"`, so FreeCAD rebuilds
  all geometry on a plain open + recompute — previously nothing rendered until
  every object was manually touched (live-testing report: features appeared
  missing because no shape was ever computed).
- FreeCAD exporter now writes genuine FreeCAD-schema `.FCStd` files that open
  directly in FreeCAD (validated with FreeCAD 1.1: all objects restore and
  recompute, pocket cut verified by volume). Real `App::Part`/`App::Origin`/
  `PartDesign::Body`/`Sketcher::SketchObject` (GeomLineSegment/GeomCircle)/
  `PartDesign::Pad`/`PartDesign::Pocket` serialization plus a minimal
  `GuiDocument.xml`; shapes recompute on load (no `.brp` files needed). The IR
  round-trip identity is preserved via a `ForgeLab.Document.xml` sidecar.
- FreeCAD importer now also reads genuine FreeCAD-authored files (canonical
  subset; Origin helpers and unmodeled object types are skipped) in addition
  to the sidecar and legacy ForgeLab-dialect files.
- AI SDK JSON Schema now pins `forgelab_version` to the installed
  `SPEC_VERSION` (`const`), so models cannot invent versions like "1.0".
- Mechanical FreeCAD export no longer raises `KeyError` when optional IR
  fields (e.g. a body's `part`) are omitted — props are validated through the
  domain models first, filling defaults.
- KiCad 9 compatibility (live-testing fixes): design rules moved from
  `(setup ...)` into a `(net_class Default ...)` block with `(add_net ...)`
  entries (importer reads both, so old boards still import); every exported pad
  now carries required `(at 0 0)` and `(size 1.6 1.6)` fields; board-outline
  `gr_line` uses `(stroke (width ...) (type solid))` instead of the
  pre-KiCad-6 bare `(width ...)`. Verified with `kicad-cli pcb export svg`
  (exit 0). `examples/hardware/blinky.kicad_pcb` regenerated at format
  version 20240108.
- glTF exporter now also exports object nodes nested as children of the scene
  node (previously only top-level objects were emitted; nested ones were
  silently dropped).
- `system_prompt()` states the installed `SPEC_VERSION` and `few_shot()`
  rewrites its example's `forgelab_version` to it, so agents never copy a
  stale hardcoded version from shipped example files.

### Added
- `forgelab update` CLI command: upgrades the `~/.forgelab` install from
  GitHub and prints the new spec version.
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
